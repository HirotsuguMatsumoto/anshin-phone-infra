#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from contextlib import contextmanager, ExitStack
from pathlib import Path
from unittest.mock import patch


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
RENDER_CONFIG_PATH = REPOSITORY_DIR / "deploy/asterisk/scripts/render_config.py"
TEMPLATE_DIR = REPOSITORY_DIR / "deploy/asterisk/config"


def load_render_config():
    spec = importlib.util.spec_from_file_location("phase1_render_config", RENDER_CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load render_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManagementComposeTest(unittest.TestCase):
    def test_management_build_context_uses_sibling_or_explicit_backend(self):
        import json
        import subprocess

        with tempfile.TemporaryDirectory(prefix="phone-compose-layout-") as directory:
            for override in (None, str(Path(directory) / "explicit-backend")):
                with self.subTest(override=override):
                    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
                    env["ANSHIN_PHONE_SECRET_DIR"] = directory
                    if override:
                        env["ANSHIN_PHONE_BACKEND_DIR"] = override
                    result = subprocess.run(
                        ["docker", "compose", "--file", str(REPOSITORY_DIR / "compose.management.yaml"),
                         "config", "--format", "json"],
                        cwd=directory, env=env, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    services = json.loads(result.stdout)["services"]
                    expected = override or str(REPOSITORY_DIR.parent / "anshin-phone-backend")
                    for name in ("backend", "backend-migrate"):
                        self.assertEqual(services[name]["build"]["context"], expected)

    def render_production(self, *, omit: str | None = None, bind_ip: str | None = None, maintenance=False):
        import json
        import subprocess
        with tempfile.TemporaryDirectory(prefix="phone-compose-") as directory:
            env = {key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT") if key in os.environ}
            env.update({
                "ANSHIN_PHONE_SECRET_DIR": directory,
                "ANSHIN_PHONE_BACKEND_IMAGE": "ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:" + "a" * 64,
            })
            if bind_ip is not None:
                env['ANSHIN_PHONE_BACKEND_BIND_IP'] = bind_ip
            if omit:
                env.pop(omit)
            result = subprocess.run(["docker", "compose", *(['--profile', 'maintenance'] if maintenance else []),
                "--file", str(REPOSITORY_DIR / "compose.production.yaml"),
                "config", "--format", "json"], cwd=directory, env=env, capture_output=True, text=True)
            return result, json.loads(result.stdout) if result.returncode == 0 else None

    def test_management_production_requires_no_carrier_and_uses_fixed_image(self):
        result, model = self.render_production()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(model["services"]), {"postgres", "backend", "backend-migrate"})
        self.assertRegex(model['services']['postgres']['image'], r'^postgres@sha256:[0-9a-f]{64}$')
        for name in ("backend", "backend-migrate"):
            service = model["services"][name]
            self.assertNotIn("build", service)
            self.assertEqual(service['platform'], 'linux/amd64')
            self.assertIn("@sha256:", service["image"])
            self.assertEqual(service["environment"]["ANSHIN_PHONE_TELEPHONY_ENABLED"], "false")
            self.assertEqual(service["environment"]["ANSHIN_PHONE_FAX_RETENTION_POLICY"], "cloco_previous_month")
            self.assertFalse(service["environment"].get("ANSHIN_PHONE_FAX_RETENTION_SECONDS"))
        self.assertEqual(model["services"]["backend"]["image"], model["services"]["backend-migrate"]["image"])
        self.assertIn("phone-auth-egress", model["services"]["backend"]["networks"])
        self.assertEqual(set(model["services"]["postgres"]["networks"]), {"phone-data"})
        self.assertTrue(model["networks"]["phone-data"]["internal"])
        self.assertNotIn("carrier_sip_password", model["secrets"])
        ports = model["services"]["backend"]["ports"]
        self.assertTrue(all(port["host_ip"] == "127.0.0.1" for port in ports))

    def test_production_never_falls_back_to_local_retention_or_source_build(self):
        for required in ("ANSHIN_PHONE_BACKEND_IMAGE",):
            with self.subTest(required=required):
                result, model = self.render_production(omit=required)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(model)

    def test_production_compose_accepts_phone_private_binding_only_on_backend(self):
        result, model = self.render_production(bind_ip='10.91.40.10')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(model['services']['backend']['ports'][0]['host_ip'], '10.91.40.10')
        self.assertEqual(model['services']['backend']['ports'][0]['target'], 8000)
        self.assertNotIn('ports', model['services']['postgres'])
        self.assertNotIn('ports', model['services']['backend-migrate'])

    def test_production_retention_input_is_accepted_by_backend_settings(self):
        import json
        import subprocess
        import sys
        from resolve_phone_backend import resolve_backend

        result, model = self.render_production(maintenance=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        retention = model['services']['backend-retention']
        self.assertEqual(retention['image'], model['services']['backend']['image'])
        self.assertEqual(retention['user'], '10001:10001')
        self.assertEqual(retention['restart'], 'no')
        self.assertEqual(retention['profiles'], ['maintenance'])
        self.assertEqual(retention['entrypoint'], ['python', '-m', 'app.core.fax_retention'])
        self.assertEqual(set(retention['networks']), {'phone-data'})
        for inherited in ('ports', 'depends_on', 'cap_add'):
            self.assertFalse(retention.get(inherited))
        backend = resolve_backend(REPOSITORY_DIR, os.getenv("ANSHIN_PHONE_BACKEND_DIR"))
        for name in ("backend", "backend-migrate", "backend-retention"):
            with self.subTest(service=name):
                env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
                env.update(model["services"][name]["environment"])
                # Only credentials are synthetic; all policy/mode inputs come from Compose.
                env.update({
                    "ANSHIN_PHONE_DB_PASSWORD": "compose-test-only",
                    "ANSHIN_PHONE_INTERNAL_TOKEN": "compose-test-only",
                    "ANSHIN_PHONE_SIP_MASTER_SECRET": "compose-test-only",
                    "ANSHIN_PHONE_FAX_STORAGE_KEY": "7" * 64,
                })
                result = subprocess.run([sys.executable, "-c",
                    "import json,runpy,sys; s=runpy.run_path(sys.argv[1])['get_settings'](); "
                    "print(json.dumps([s.environment,s.fax_retention_policy,s.fax_retention_seconds,s.telephony_enabled]))",
                    str(backend / "app/core/config.py")], env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), ["production", "cloco_previous_month", None, False])


class ProductionRuntimeTest(unittest.TestCase):
    def runtime(self, directory, *, migration_failure=False, migration_timeout=False, stop_failure=False,
                candidate_health_failure=False, rollback_health_failure=False,
                settings_unknown=False, migration_unknown=False, compose_extra_files=()):
        import json
        import subprocess
        from production_runtime import Runtime, RuntimeFailure
        calls = []
        root = Path(directory)
        state = {'image': 'ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:' + 'a' * 64,
                 'candidate_failed': False}

        def runner(argv, **kwargs):
            calls.append((argv, kwargs['env']))
            output = ''
            code = 0
            if argv[:3] == ['docker', 'image', 'inspect']:
                output = 'b' * 40
            elif argv[:2] == ['docker', 'inspect']:
                output = state['image']
            elif 'compose' in argv and 'ps' in argv:
                output = ('abc123' if '--quiet' in argv else
                          json.dumps([{'Service': name, 'State': 'running', 'Health': 'healthy'}
                                      for name in ('backend', 'postgres')]))
            elif 'compose' in argv and 'up' in argv and argv[-1] == 'backend':
                state['image'] = kwargs['env']['ANSHIN_PHONE_BACKEND_IMAGE']
            elif 'compose' in argv and 'exec' in argv:
                if candidate_health_failure and state['image'].endswith('b' * 64):
                    code = 1
                    state['candidate_failed'] = True
                elif rollback_health_failure and state['candidate_failed']:
                    code = 1
            elif 'backend-migrate' in argv and 'run' in argv:
                if migration_unknown:
                    raise RuntimeFailure('phone_command_children_unknown')
                if migration_timeout:
                    raise subprocess.TimeoutExpired(argv, 180)
                code = int(migration_failure)
            elif 'run' in argv and '--entrypoint' in argv and settings_unknown:
                raise RuntimeFailure('phone_command_children_unknown')
            elif argv[:3] == ['docker', 'ps', '--all'] and any('migration' in arg for arg in argv):
                output = 'owned-migration' if migration_timeout else ''
            elif argv[:2] == ['docker', 'stop']:
                code = int(stop_failure)
            elif 'compose' in argv and 'stop' in argv:
                code = int(stop_failure)
            return subprocess.CompletedProcess(argv, code, output, 'private diagnostic never printed')

        runtime = Runtime(root=root / 'candidate', state=root / 'state', secrets=root / 'secrets',
                          project='phone-unit', lock=root / 'release.lock', runner=runner,
                          compose_extra_files=compose_extra_files)
        return runtime, calls

    def previous(self, runtime):
        profile = {'source_root': str(runtime.root.parent / 'old'),
                   'backend_image': 'ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:' + 'a' * 64,
                   'backend_sha': 'a' * 40, 'infra_sha': 'a' * 40}
        runtime.save(profile)
        return profile

    def deploy(self, runtime):
        return runtime.deploy('ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:' + 'b' * 64,
                              'b' * 40, 'c' * 40)

    def test_new_deploy_migrates_once_and_preserves_actual_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, calls = self.runtime(directory)
            result = self.deploy(runtime)
            self.assertEqual(result['status'], 'deployed')
            self.assertEqual(runtime.profile()['backend_sha'], 'b' * 40)
            self.assertEqual(sum('run' in argv and 'backend-migrate' in argv for argv, _ in calls), 1)
            self.assertFalse(any('down' in argv or '--volumes' in argv for argv, _ in calls))
            self.assertEqual(stat.S_IMODE((runtime.state / 'runtime.json').stat().st_mode), 0o600)

    def test_existing_data_requires_known_profile_before_mutation(self):
        from production_runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as directory:
            runtime, calls = self.runtime(directory)
            with patch.object(runtime, 'observation', return_value={'containers': [], 'volumes': ['existing-db']}):
                with self.assertRaisesRegex(RuntimeFailure, 'existing_data_without_profile'):
                    self.deploy(runtime)
            self.assertEqual(calls, [])

    def test_initial_failure_snapshot_is_captured_before_release_unlock(self):
        import fcntl
        from production_runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as directory:
            runtime,calls=self.runtime(directory,migration_failure=True)
            observations=[]
            def observe():
                # The first observation is deliberately before the lock. The
                # failure snapshot must be the third and still hold that lock.
                held=False
                with runtime.lock.open('a') as competitor:
                    try:fcntl.flock(competitor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:held=True
                result={'containers':['first-candidate'] if len(observations)>=2 else [],'volumes':[]}
                observations.append((held,result))
                return result
            with patch.object(runtime,'observation',side_effect=observe):
                with self.assertRaisesRegex(RuntimeFailure,'initial_deploy_failed_data_preserved') as failed:
                    self.deploy(runtime)
            recovery=failed.exception.initial_recovery
            self.assertEqual([held for held,_ in observations],[False,True,True])
            self.assertEqual(recovery['observation'],{'containers':['first-candidate'],'volumes':[]})
            self.assertEqual(recovery['candidate']['infra_sha'],'c'*40)
            with runtime.lock.open('a') as competitor:fcntl.flock(competitor,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_initial_forward_repair_requires_same_candidate_and_exact_prior_resources(self):
        from production_runtime import RuntimeFailure
        import copy
        for changed in (None, 'inode', 'image', 'missing'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                runtime, calls = self.runtime(directory)
                candidate = {'source_root': str(runtime.root),
                    'backend_image': 'ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:' + 'b' * 64,
                    'backend_sha': 'b' * 40, 'infra_sha': 'c' * 40}
                actual = {'containers': ['known-initial-container'],
                          'volumes': [{'Name': 'known-db', 'backing': {'device': 1, 'inode': 2}}]}
                recovery = {'candidate': candidate, 'observation': copy.deepcopy(actual)}
                if changed == 'inode': recovery['observation']['volumes'][0]['backing']['inode'] = 3
                if changed == 'image': recovery['candidate'] = {**candidate, 'backend_image': 'foreign'}
                if changed == 'missing': recovery.pop('observation')
                with patch.object(runtime, 'observation', return_value=actual):
                    if changed is None:
                        result = runtime.deploy(candidate['backend_image'], candidate['backend_sha'], candidate['infra_sha'],
                                                initial_recovery=recovery)
                        self.assertEqual(result['status'], 'deployed')
                    else:
                        with self.assertRaisesRegex(RuntimeFailure, 'initial_recovery_identity_changed'):
                            runtime.deploy(candidate['backend_image'], candidate['backend_sha'], candidate['infra_sha'],
                                           initial_recovery=recovery)
                        self.assertEqual(calls, [])

    def test_volume_observation_uses_actual_backing_inode_and_detects_recreation_or_race(self):
        from production_runtime import Runtime, RuntimeFailure
        import json, subprocess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / 'first'; second = root / 'second'
            first.mkdir(); second.mkdir()
            name = 'phone-unit_postgres-data'
            row = {'Name': name, 'Driver': 'local', 'Scope': 'local',
                   'CreatedAt': '2026-10-17T00:00:00Z', 'Options': None,
                   'Mountpoint': '/var/lib/docker/volumes/' + name + '/_data',
                   'Labels': {'com.docker.compose.project': 'phone-unit', 'com.docker.compose.volume': 'postgres-data',
                              'com.docker.compose.config-hash': 'a' * 64}}
            current = [first]; reads = []; race = [False]
            def runner(argv, **kwargs):
                output = ''
                if argv[:3] == ['docker', 'volume', 'ls']: output = name
                if argv[:3] == ['docker', 'volume', 'inspect']:
                    reads.append(name)
                    value = {**row, **({'CreatedAt': '2026-10-18T00:00:00Z'} if race[0] and len(reads) % 2 == 0 else {})}
                    output = json.dumps([value])
                return subprocess.CompletedProcess(argv, 0, output, '')
            runtime = Runtime(project='phone-unit', runner=runner,
                              volume_stat=lambda path: Runtime.local_volume_stat(current[0]))
            before = runtime.observation()
            self.assertEqual(before['volumes'][0]['backing'],
                             {'device': first.stat().st_dev, 'inode': first.stat().st_ino})
            current[0] = second
            after = runtime.observation()
            self.assertNotEqual(before, after)
            race[0] = True
            with self.assertRaisesRegex(RuntimeFailure, 'volume_identity_changed'):
                runtime.observation()
            race[0] = False
            row['Labels']['com.docker.compose.config-hash'] = 'unrecognized'
            with self.assertRaisesRegex(RuntimeFailure, 'volume_identity_invalid'):
                runtime.observation()

    def test_backup_uses_same_lock_without_recursive_acquisition_and_detects_drift(self):
        from production_runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as directory:
            runtime, calls = self.runtime(directory)
            previous = self.previous(runtime)

            def backup():
                with runtime.exclusive():
                    pass

            with patch.object(runtime, 'backup', side_effect=backup) as backup_call:
                self.assertEqual(self.deploy(runtime)['status'], 'deployed')
                backup_call.assert_called_once()
            runtime, calls = self.runtime(Path(directory) / 'drift')
            self.previous(runtime)
            with patch.object(runtime, 'backup'), patch.object(runtime, 'observation', side_effect=[{}, {'changed': True}]):
                with self.assertRaisesRegex(RuntimeFailure, 'changed_during_backup'):
                    self.deploy(runtime)
            self.assertFalse(any('up' in argv or 'pull' in argv for argv, _ in calls))

    def test_migration_failure_restores_previous_backend_and_never_destroys_data(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, calls = self.runtime(directory, migration_failure=True)
            previous = self.previous(runtime)
            with patch.object(runtime, 'backup'):
                result = self.deploy(runtime)
            self.assertEqual(result['status'], 'rolled_back')
            self.assertEqual(runtime.profile(), previous)
            backend_start = [(argv, env) for argv, env in calls if 'up' in argv and argv[-1] == 'backend']
            self.assertEqual(len(backend_start), 1)
            self.assertEqual(backend_start[0][1]['ANSHIN_PHONE_BACKEND_IMAGE'], previous['backend_image'])
            self.assertFalse(any('down' in argv or '--volumes' in argv for argv, _ in calls))

    def test_unsettled_migration_cannot_claim_rollback(self):
        from production_runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as directory:
            runtime, calls = self.runtime(directory, migration_timeout=True, stop_failure=True)
            previous = self.previous(runtime)
            with patch.object(runtime, 'backup'):
                with self.assertRaises(RuntimeFailure):
                    self.deploy(runtime)
            self.assertEqual(runtime.profile(), previous)
            self.assertFalse(any('up' in argv and argv[-1] == 'backend' for argv, _ in calls))

    def test_candidate_health_failure_returns_only_observed_healthy_previous_runtime(self):
        from production_runtime import RuntimeFailure
        for previous_unhealthy in (False, True):
            with self.subTest(previous_unhealthy=previous_unhealthy), tempfile.TemporaryDirectory() as directory:
                runtime, calls = self.runtime(directory, candidate_health_failure=True,
                                             rollback_health_failure=previous_unhealthy)
                previous = self.previous(runtime)
                with patch.object(runtime, 'backup'):
                    if previous_unhealthy:
                        with self.assertRaises(RuntimeFailure):
                            self.deploy(runtime)
                    else:
                        self.assertEqual(self.deploy(runtime)['status'], 'rolled_back')
                self.assertEqual(runtime.profile(), previous)
                self.assertEqual(sum('up' in argv and argv[-1] == 'backend' for argv, _ in calls), 2)

    def test_stale_profile_cannot_report_different_running_image_as_healthy(self):
        from production_runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as directory:
            runtime, calls = self.runtime(directory)
            self.deploy(runtime)
            with self.assertRaisesRegex(RuntimeFailure, 'backend_image_mismatch'):
                runtime.health(self.previous(runtime))

    def test_first_failure_reports_unconfirmed_cleanup(self):
        from production_runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as directory:
            runtime, calls = self.runtime(directory, migration_failure=True, stop_failure=True)
            with self.assertRaisesRegex(RuntimeFailure, 'cleanup_unconfirmed'):
                self.deploy(runtime)
            self.assertIsNone(runtime.profile())

    def test_production_environment_pins_local_daemon(self):
        from production_runtime import Runtime
        with patch.dict(os.environ, {'DOCKER_HOST': 'tcp://foreign.invalid:2375', 'DOCKER_CONTEXT': 'foreign',
                                    'ANSHIN_PHONE_BACKEND_BIND_IP': '0.0.0.0'}):
            env = Runtime(transport={'ANSHIN_PHONE_BACKEND_BIND_IP': '0.0.0.0'}).environment()
            self.assertEqual(env['DOCKER_HOST'], 'unix:///var/run/docker.sock')
            self.assertNotIn('DOCKER_CONTEXT', env)
            self.assertEqual(env['ANSHIN_PHONE_BACKEND_BIND_IP'], '10.91.40.10')
            self.assertEqual(Runtime(backend_bind='127.0.0.1').environment()['ANSHIN_PHONE_BACKEND_BIND_IP'], '127.0.0.1')

    def test_unconfirmed_settings_or_migration_children_never_mutate_cleanup_or_rollback(self):
        from production_runtime import RuntimeFailure
        from unittest.mock import call
        for phase in ('settings', 'migration'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as raw:
                runtime, calls = self.runtime(raw, **{phase + '_unknown': True})
                previous = self.previous(runtime)
                with patch.object(runtime, 'backup'), patch.object(runtime, 'stop_oneoff', wraps=runtime.stop_oneoff) as cleanup:
                    with self.assertRaisesRegex(RuntimeFailure, 'phone_command_children_unknown'):
                        self.deploy(runtime)
                self.assertEqual(cleanup.call_args_list, [] if phase == 'settings' else [call('settings', 'backend')])
                self.assertFalse(any('stop' in argv or 'rm' in argv or ('up' in argv and argv[-1] == 'backend') for argv, _ in calls))
                self.assertEqual(runtime.profile(), previous)

    def test_fixture_network_file_is_explicit_and_follows_production_through_cleanup(self):
        with tempfile.TemporaryDirectory() as raw:
            runtime, calls = self.runtime(raw)
            profile = self.previous(runtime)
            with patch.dict(os.environ, {'COMPOSE_FILE': '/foreign/override.yaml'}):
                runtime.compose(profile, 'config')
            self.assertEqual(calls[-1][0].count('--file'), 1)
            self.assertNotIn('COMPOSE_FILE', calls[-1][1])
            extra = Path(raw) / 'fixture-networks.json'
            fixture, calls = self.runtime(Path(raw) / 'fixture', compose_extra_files=(extra,))
            profile = self.previous(fixture)
            for args in (('run', '--rm', 'backend'), ('exec', '-T', 'backend', 'true'),
                         ('down', '--volumes', '--remove-orphans')):
                fixture.compose(profile, *args)
                command = calls[-1][0]
                first = command.index('--file')
                self.assertEqual(command[first:first + 4],
                    ['--file', str(Path(profile['source_root']) / 'compose.production.yaml'), '--file', str(extra)])
                self.assertEqual(command[first + 4:], list(args))

    def test_owned_process_stops_descendants_when_leader_exits_or_term_closes_pipes(self):
        import signal, subprocess, sys, time
        from production_runtime import run_owned_process
        real_popen = subprocess.Popen
        for leader_exit in (True, False):
            with self.subTest(leader_exit=leader_exit), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / 'child-pid'; processes = []
                child = ('import os,signal,time; from pathlib import Path; '
                         'signal.signal(signal.SIGTERM,lambda *_:(os.close(1),os.close(2))); '
                         'Path(' + repr(str(path)) + ').write_text(str(os.getpid())); time.sleep(30)')
                parent = ('import subprocess,sys,time; from pathlib import Path; '
                          'subprocess.Popen([sys.executable,"-c",' + repr(child) + ']); '
                          'p=Path(' + repr(str(path)) + '); '
                          '\nwhile not p.exists(): time.sleep(0.01)\n' + ('' if leader_exit else 'time.sleep(30)'))
                def launch(*args, **kwargs):
                    process = real_popen(*args, **kwargs); processes.append(process); return process
                try:
                    with patch('production_runtime.subprocess.Popen', side_effect=launch):
                        with self.assertRaises(subprocess.TimeoutExpired):
                            run_owned_process([sys.executable, '-c', parent], timeout=2,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    deadline = time.monotonic() + 2
                    while True:
                        state = subprocess.run(['ps', '-p', path.read_text().strip(), '-o', 'stat='],
                            text=True, capture_output=True, timeout=5).stdout.strip()
                        if not state or state.startswith('Z'):
                            break
                        self.assertLess(time.monotonic(), deadline, 'owned descendant still executing')
                        time.sleep(0.02)
                finally:
                    for process in processes:
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        process.wait(timeout=5)


class PhoneBackupAdapterTest(unittest.TestCase):
    @contextmanager
    def backup_update_fixture(self):
        import json, base64, copy, subprocess
        from types import SimpleNamespace
        import phone_postgresql_backup_adapter as owner
        with tempfile.TemporaryDirectory() as raw, ExitStack() as stack:
            root = Path(raw)
            for name in ('install', 'keys', 'state', 'units', 'work'):
                (root/name).mkdir(mode=0o700)
            for name, value in {'INSTALL':root/'install', 'KEYS':root/'keys', 'STATE':root/'state',
                                'CONFIG':root/'profile.json', 'AWS_CONFIG':root/'aws-config', 'UNIT_ROOT':root/'units'}.items():
                stack.enter_context(patch.object(owner, name, value))
            original_mkdtemp = tempfile.mkdtemp
            stack.enter_context(patch.object(owner.tempfile, 'mkdtemp', side_effect=lambda **kwargs:
                original_mkdtemp(prefix=kwargs['prefix'], dir=root/'work')))
            public = {'trust_anchor_arn':'arn:aws:rolesanywhere:ap-northeast-1:691862619128:trust-anchor/916219bc-2500-4f73-a7b2-82e0c94ec215',
                      'manifest_key_id':'a'*64, 'credential_versions':{key:1 for key in owner.CREDENTIAL_IDS}}
            for data, product in (('db','phone-postgresql'),('fax','phone-fax')):
                for role in ('writer','restore'):
                    public[data+'_'+role+'_role_arn']='arn:aws:iam::691862619128:role/anshin-prod-'+product+'-backup-'+role
                    public[data+'_'+role+'_profile_arn']='arn:aws:rolesanywhere:ap-northeast-1:691862619128:profile/12345678-1234-1234-1234-123456789abc'
            profile = {'manifest_key_id':'a'*64,'governance_sha':'b'*40,'infra_sha':'c'*40,'public':public}
            owner.write_private(owner.CONFIG, (json.dumps(profile,sort_keys=True)+'\n').encode())
            owner.write_private(owner.AWS_CONFIG, owner.aws_profiles(public))
            for name in owner.PRODUCER_KEYS: owner.write_private(owner.KEYS/name, (name+'-old').encode())
            assets = {'scripts/phone_postgresql_backup_adapter.py':b'old-source',
                      'deploy/postgresql-backup/'+owner.BACKUP_TIMER:b'old-unit'}
            for name, body in assets.items():
                (owner.INSTALL/name).parent.mkdir(parents=True,exist_ok=True)
                owner.write_private(owner.INSTALL/name,body)
                if name.endswith('.timer'):
                    (owner.UNIT_ROOT/Path(name).name).write_bytes(body);(owner.UNIT_ROOT/Path(name).name).chmod(0o644)
            class Runtime:
                def __init__(self):
                    self.schedule={name:{'enabled':True,'active':True} for name in (owner.BACKUP_TIMER,owner.RETENTION_TIMER)}
                    self.locked=False;self.calls=[]
                def command(self, args, **kwargs):
                    self.calls.append(args)
                    if args[:2]==['systemctl','show']:
                        state=self.schedule[args[2]]
                        value='ActiveState='+('active' if state['active'] else 'inactive')+'\nUnitFileState='+('enabled' if state['enabled'] else 'disabled')
                        return subprocess.CompletedProcess(args,0,value,'')
                    if args[0]=='systemctl':
                        action=args[1]
                        for name in args[2:]:
                            if name not in self.schedule:continue
                            if action in ('enable','disable'):self.schedule[name]['enabled']=action=='enable'
                            if action in ('start','stop') or '--now' in args:
                                if action=='start':assert not self.locked
                                self.schedule[name]['active']=action=='start'
                    return subprocess.CompletedProcess(args,0,'','')
                @contextmanager
                def exclusive(self):
                    assert not self.locked;self.locked=True
                    try:yield
                    finally:self.locked=False
                def profile(self):return {}
                def health(self, profile):return {'status':'healthy'}
            runtime=Runtime();expected=owner.installation_state(assets,runtime=runtime)
            renewed=copy.deepcopy(public)
            for key in renewed['credential_versions']:
                if '-backup-' in key:renewed['credential_versions'][key]=2
            keys={name:base64.b64encode((name+'-new').encode() if '-writer-' in name else (owner.KEYS/name).read_bytes()).decode()
                  for name in owner.PRODUCER_KEYS}
            keys.update({name:base64.b64encode((name+'-new').encode()).decode() for name in owner.RESTORE_KEYS if '-restore-' in name})
            material={'public':renewed,'keys':keys};new_assets={name:body+b'-new' for name,body in assets.items()}
            snapshots={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            yield SimpleNamespace(owner=owner,runtime=runtime,expected=expected,material=material,assets=new_assets,old_assets=assets,
                                  snapshots=snapshots,root=root,original_schedule=copy.deepcopy(runtime.schedule))

    def test_backup_update_switches_known_files_and_restarts_timers_after_unlock(self):
        with self.backup_update_fixture() as f, patch.object(f.owner,'credential_canary',return_value={'authenticated_roles':4}) as canary:
            value=f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=f.expected)
            self.assertTrue(value['updated']);canary.assert_called_once()
            self.assertEqual(f.original_schedule,f.runtime.schedule)
            for name,body in f.assets.items():self.assertEqual(body,(f.owner.INSTALL/name).read_bytes())
            self.assertEqual('d'*40,f.owner.read_profile(f.owner.CONFIG)['governance_sha'])
            for path,body in f.snapshots.items():
                if path.parent==f.owner.KEYS and '-writer-' not in path.name:self.assertEqual(body,path.read_bytes())
            self.assertEqual([],list((f.root/'work').iterdir()))
            current=f.owner.installation_state(f.assets,runtime=f.runtime)
            value=f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=current)
            self.assertFalse(value['updated']);self.assertEqual(1,canary.call_count)
            self.assertEqual(f.original_schedule,f.runtime.schedule)

    def test_backup_update_preserves_nonleaf_keys_and_versions(self):
        import base64
        from production_runtime import RuntimeFailure
        for field in ('key','version'):
            with self.subTest(field=field),self.backup_update_fixture() as f:
                if field=='key':f.material['keys']['phone-age-recipient.txt']=base64.b64encode(b'changed').decode()
                else:f.material['public']['credential_versions']['anshin.production.phone.backup-age-identity']=2
                with self.assertRaisesRegex(RuntimeFailure,'nonleaf'):
                    f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=f.expected)
                for path,body in f.snapshots.items():self.assertEqual(body,path.read_bytes())
                self.assertEqual(f.original_schedule,f.runtime.schedule)

    def test_backup_update_rejects_stale_preimage_before_schedule_or_file_changes(self):
        from production_runtime import RuntimeFailure
        with self.backup_update_fixture() as f:
            f.expected['profile_sha256']='f'*64
            f.runtime.calls.clear()
            with self.assertRaisesRegex(RuntimeFailure,'preimage_changed'):
                f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=f.expected)
            self.assertFalse(any(args[1] in {'disable','stop','enable','start'} for args in f.runtime.calls))
            self.assertEqual(f.original_schedule,f.runtime.schedule)
            for path,body in f.snapshots.items():self.assertEqual(body,path.read_bytes())

    def test_backup_update_known_canary_failure_rolls_back_and_unknown_keeps_inputs(self):
        from production_runtime import RuntimeFailure
        for reason in ('phone_backup_update_certificate_pair_invalid','phone_command_children_unknown'):
            with self.subTest(reason=reason),self.backup_update_fixture() as f, \
                    patch.object(f.owner,'credential_canary',side_effect=RuntimeFailure(reason)):
                with self.assertRaises(RuntimeFailure) as failure:
                    f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=f.expected)
                for path,body in f.snapshots.items():self.assertEqual(body,path.read_bytes())
                if reason.endswith('unknown'):
                    self.assertEqual('phone_backup_update_cleanup_unconfirmed',str(failure.exception))
                    self.assertTrue(Path(failure.exception.retained_private_configuration).is_dir())
                    self.assertTrue(all(not s['enabled'] and not s['active'] for s in f.runtime.schedule.values()))
                else:
                    self.assertEqual(f.original_schedule,f.runtime.schedule)
                    self.assertEqual([],list((f.root/'work').iterdir()))

    def test_backup_update_compensates_file_renamed_before_fsync_failure(self):
        with self.backup_update_fixture() as f, patch.object(f.owner,'credential_canary',return_value={}), ExitStack() as stack:
            original=f.owner.replace_known;failed=False
            def interrupted(path,before,after,mode):
                nonlocal failed
                original(path,before,after,mode)
                if not failed:failed=True;raise OSError('fixture-after-rename')
            stack.enter_context(patch.object(f.owner,'replace_known',side_effect=interrupted))
            with self.assertRaises(OSError):
                f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=f.expected)
            for path,body in f.snapshots.items():self.assertEqual(body,path.read_bytes())
            self.assertEqual(f.original_schedule,f.runtime.schedule)
            self.assertEqual([],list((f.root/'work').iterdir()))

    def test_backup_update_schedule_readback_failure_restores_source_and_prior_schedule(self):
        import subprocess
        from production_runtime import RuntimeFailure
        with self.backup_update_fixture() as f, patch.object(f.owner,'credential_canary',return_value={}), ExitStack() as stack:
            original=f.runtime.command;failed=False
            def command(args,**kwargs):
                nonlocal failed
                if args[:2]==['systemctl','start'] and not failed:
                    failed=True;return subprocess.CompletedProcess(args,0,'','')
                return original(args,**kwargs)
            stack.enter_context(patch.object(f.runtime,'command',side_effect=command))
            with self.assertRaisesRegex(RuntimeFailure,'schedule_readback_failed'):
                f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=f.expected)
            for path,body in f.snapshots.items():self.assertEqual(body,path.read_bytes())
            self.assertEqual(f.original_schedule,f.runtime.schedule)

    def test_backup_update_compensation_continues_after_one_file_cannot_be_restored(self):
        from production_runtime import RuntimeFailure
        with self.backup_update_fixture() as f, patch.object(f.owner,'credential_canary',return_value={}), ExitStack() as stack:
            original=f.owner.replace_known;blocked=f.owner.INSTALL/'scripts/phone_postgresql_backup_adapter.py'
            def compensate(path,before,after,mode):
                if path==blocked and after==f.snapshots[path]:raise RuntimeFailure('phone_backup_update_preimage_changed')
                return original(path,before,after,mode)
            stack.enter_context(patch.object(f.owner,'replace_known',side_effect=compensate))
            stack.enter_context(patch.object(f.runtime,'health',side_effect=[{},RuntimeFailure('phone_runtime_unhealthy'),{}]))
            with self.assertRaisesRegex(RuntimeFailure,'cleanup_unconfirmed'):
                f.owner.install_backup(f.material,source_sha='d'*40,infra_sha='e'*40,runtime=f.runtime,assets=f.assets,expected_installed=f.expected)
            for path,body in f.snapshots.items():
                if path!=blocked:self.assertEqual(body,path.read_bytes())
            self.assertEqual(f.assets['scripts/phone_postgresql_backup_adapter.py'],blocked.read_bytes())
            self.assertTrue(all(not state['enabled'] and not state['active'] for state in f.runtime.schedule.values()))
            self.assertTrue(list((f.root/'work').iterdir()))

    def test_dedicated_inputs_do_not_inherit_other_product_credentials(self):
        from production_runtime import Runtime, LOCK
        from phone_postgresql_backup_adapter import environment, BUCKET, WRITER
        self.assertEqual(str(LOCK), '/tmp/anshin-ms-a2-1-platform-release.lock')
        profile = {'source_root': '/opt/anshin-phone/releases/infra', 'backend_sha': 'b' * 40,
                   'backend_image': 'ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:' + 'd' * 64}
        with patch.dict(os.environ, {'AWS_ACCESS_KEY_ID': 'foreign', 'POSTGRES_BACKUP_KMS_KEY_ID': 'foreign',
                                    'ANSHIN_PHONE_BACKEND_IMAGE': 'foreign', 'DOCKER_HOST': 'tcp://foreign:2375'}):
            env = environment(Runtime(), profile, {'manifest_key_id': 'a' * 64}, 'c' * 64)
        self.assertEqual(env['POSTGRES_BACKUP_S3_BUCKET'], BUCKET)
        self.assertEqual(env['POSTGRES_BACKUP_EXPECTED_ROLE_ARN'], WRITER)
        self.assertEqual(env['POSTGRES_BACKUP_EXPECTED_CONTAINER_ID'], 'c' * 64)
        self.assertEqual(env['POSTGRES_BACKUP_SOURCE_FIXED_SHA'], 'b' * 40)
        self.assertEqual(env['POSTGRES_BACKUP_SOURCE_ID'], 'ms-a2-1/phone-postgresql')
        self.assertEqual(env['DOCKER_HOST'], 'unix:///var/run/docker.sock')
        self.assertEqual(env['POSTGRES_BACKUP_CONTAINER_NAME'], 'anshin-phone-production-postgres-1')
        self.assertNotIn('POSTGRES_BACKUP_COMPOSE_ENV_FILE', env)
        self.assertEqual(env['AWS_PROFILE'], 'anshin-phone-backup-writer')
        self.assertEqual(env['ANSHIN_PHONE_BACKEND_IMAGE'], profile['backend_image'])
        self.assertNotIn('AWS_ACCESS_KEY_ID', env)
        self.assertNotIn('POSTGRES_BACKUP_KMS_KEY_ID', env)
        self.assertNotIn('foreign', env.values())

    def test_shared_owner_failure_and_runtime_drift_never_report_completed(self):
        import json
        import subprocess
        from unittest.mock import Mock
        from production_runtime import RuntimeFailure
        from phone_postgresql_backup_adapter import scheduled_backup, read_profile
        installed = {'source_root': '/opt/anshin-phone/releases/infra', 'backend_sha': 'b' * 40,
                     'backend_image': 'ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:' + 'd' * 64}
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'profile.json'
            from phone_postgresql_backup_adapter import CREDENTIAL_IDS
            public = {'trust_anchor_arn': 'arn:aws:rolesanywhere:ap-northeast-1:691862619128:trust-anchor/916219bc-2500-4f73-a7b2-82e0c94ec215',
                      'manifest_key_id': 'a' * 64, 'credential_versions': {k: 1 for k in CREDENTIAL_IDS}}
            for purpose, product in (('db', 'phone-postgresql'), ('fax', 'phone-fax')):
                for role in ('writer', 'restore'):
                    public[purpose+'_'+role+'_role_arn'] = 'arn:aws:iam::691862619128:role/anshin-prod-'+product+'-backup-'+role
                    public[purpose+'_'+role+'_profile_arn'] = 'arn:aws:rolesanywhere:ap-northeast-1:691862619128:profile/12345678-1234-1234-1234-123456789abc'
            config.write_text(json.dumps({'manifest_key_id': 'a' * 64, 'governance_sha': 'c' * 40,
                                          'infra_sha': 'd' * 40, 'public': public})); config.chmod(0o600)
            runtime = Mock()
            runtime.project = 'anshin-phone-production'
            runtime.environment.return_value = {}
            runtime.profile.return_value = installed
            runtime.compose.return_value = subprocess.CompletedProcess([], 0, 'c' * 64, '')
            runtime.command.return_value = subprocess.CompletedProcess([], 0, '/anshin-phone-production-postgres-1', '')
            self.assertEqual(scheduled_backup(runtime=runtime, config_path=config)['status'], 'completed')
            self.assertEqual(runtime.command.call_args.kwargs['timeout'], 1100)
            self.assertEqual(runtime.command.call_args.args[0], ['bash', '/opt/anshin-phone-backup/sh/backup_postgresql_to_s3.sh'])
            runtime.command.side_effect = RuntimeFailure('producer_failed')
            with self.assertRaisesRegex(RuntimeFailure, 'producer_failed'):
                scheduled_backup(runtime=runtime, config_path=config)
            runtime.command.side_effect = None
            runtime.profile.side_effect = [installed, {**installed, 'backend_sha': 'f' * 40}]
            with self.assertRaisesRegex(RuntimeFailure, 'runtime_changed'):
                scheduled_backup(runtime=runtime, config_path=config)
            config.chmod(0o644)
            with self.assertRaisesRegex(RuntimeFailure, 'permissions'):
                read_profile(config)

    def test_restored_reader_preserves_unknown_children_and_cli_status(self):
        import sys
        import io
        import contextlib
        from unittest.mock import Mock
        from production_runtime import RuntimeFailure
        from phone_postgresql_backup_adapter import run_restored_reader, main
        for reason, stops in [('phone_command_children_unknown', 0), ('phone_restore_reader_failed', 1)]:
            runtime = Mock()
            runtime.command.side_effect = RuntimeFailure(reason)
            with self.assertRaisesRegex(RuntimeFailure, reason):
                run_restored_reader(runtime, 'a' * 64)
            self.assertEqual(runtime.stop_oneoff.call_count, stops)
        runtime = Mock()
        runtime.command.side_effect = RuntimeFailure('known_failure')
        runtime.stop_oneoff.side_effect = RuntimeFailure('phone_command_children_unknown')
        with self.assertRaisesRegex(RuntimeFailure, 'reader_cleanup_unconfirmed'):
            run_restored_reader(runtime, 'a' * 64)
        for reason in ('phone_command_children_unknown', 'phone_capture_helper_creation_unknown',
                       'phone_restore_reader_cleanup_unconfirmed', 'known_failure'):
            with patch('phone_postgresql_backup_adapter.verify_restored_fax', side_effect=RuntimeFailure(reason)), \
                    patch.object(sys, 'argv', ['owner', '--verify-restored-fax', 'manifest', 'work', 'pg']), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1 if reason == 'known_failure' else 76)

    def test_backup_unit_preserves_shared_lock_and_four_daily_catchup(self):
        root = REPOSITORY_DIR / 'deploy/postgresql-backup'
        timer = (root / 'anshin-phone-postgresql-backup.timer').read_text()
        service = (root / 'anshin-phone-postgresql-backup.service').read_text()
        self.assertEqual(timer.count('OnCalendar='), 4)
        self.assertIn('Persistent=true', timer)
        self.assertIn('PrivateTmp=false', service)
        self.assertIn('TimeoutStartSec=25min', service)
        self.assertIn('TimeoutStopSec=5min', service)
        self.assertIn('/opt/anshin-phone-backup/scripts/phone_postgresql_backup_adapter.py --scheduled-backup', service)

    def retention_runtime(self):
        import contextlib
        import json
        import subprocess
        from unittest.mock import Mock
        runtime = Mock()
        runtime.project = 'anshin-phone-production'
        runtime.exclusive.return_value = contextlib.nullcontext()
        runtime.profile.return_value = {
            'source_root': '/opt/anshin-phone/releases/' + 'a' * 40, 'backend_sha': 'b' * 40,
            'backend_image': 'ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:' + 'd' * 64}
        identifier = 'c' * 64
        projection = [identifier, '/' + runtime.project + '-fax-retention', {
            'com.docker.compose.project': runtime.project,
            'com.docker.compose.service': 'backend-retention',
            'com.docker.compose.oneoff': 'True'}, runtime.profile()['backend_image'], '10001:10001']
        runtime.compose.return_value = subprocess.CompletedProcess([], 0, identifier, '')
        runtime.command.side_effect = [subprocess.CompletedProcess([], 0, value, '') for value in (
            json.dumps(projection), '0', json.dumps({'status': 'ok', 'purged_count': 3}))]
        return runtime, identifier, projection

    def test_retention_success_cleans_only_verified_returned_id(self):
        from phone_postgresql_backup_adapter import purge_expired
        runtime, identifier, _ = self.retention_runtime()
        result = purge_expired(runtime=runtime)
        self.assertEqual(result['purged_count'], 3)
        self.assertEqual(result['source_fixed_sha'], 'b' * 40)
        runtime.stop_oneoff.assert_called_once_with('fax-retention', 'backend-retention', expected_id=identifier)
        self.assertEqual(runtime.health.call_count, 2)

    def test_retention_lost_or_invalid_create_response_never_adopts_name(self):
        import subprocess
        from production_runtime import RuntimeFailure
        from phone_postgresql_backup_adapter import purge_expired
        for response in (RuntimeFailure('phone_command_timeout'), 'invalid'):
            with self.subTest(response=type(response).__name__):
                runtime, _, _ = self.retention_runtime()
                if isinstance(response, RuntimeFailure):
                    runtime.compose.side_effect = response
                else:
                    runtime.compose.return_value = subprocess.CompletedProcess([], 0, response, '')
                with self.assertRaises(RuntimeFailure):
                    purge_expired(runtime=runtime)
                runtime.command.assert_not_called()
                runtime.stop_oneoff.assert_not_called()

    def test_retention_unverified_or_unknown_actor_is_preserved(self):
        import json
        import subprocess
        from production_runtime import RuntimeFailure
        from phone_postgresql_backup_adapter import purge_expired
        for failure in ('metadata', 'children'):
            with self.subTest(failure=failure):
                runtime, _, projection = self.retention_runtime()
                if failure == 'metadata':
                    projection[3] = 'foreign-image'
                    runtime.command.side_effect = [subprocess.CompletedProcess([], 0, json.dumps(projection), '')]
                else:
                    runtime.command.side_effect = [subprocess.CompletedProcess([], 0, json.dumps(projection), ''),
                                                   RuntimeFailure('phone_command_children_unknown')]
                with self.assertRaises(RuntimeFailure):
                    purge_expired(runtime=runtime)
                runtime.stop_oneoff.assert_not_called()

    def test_retention_failed_consumer_cleans_verified_id(self):
        import json
        import subprocess
        from production_runtime import RuntimeFailure
        from phone_postgresql_backup_adapter import purge_expired
        runtime, identifier, projection = self.retention_runtime()
        runtime.command.side_effect = [subprocess.CompletedProcess([], 0, value, '')
                                       for value in (json.dumps(projection), '1')]
        with self.assertRaisesRegex(RuntimeFailure, 'consumer_failed'):
            purge_expired(runtime=runtime)
        runtime.stop_oneoff.assert_called_once_with('fax-retention', 'backend-retention', expected_id=identifier)

    def test_unresolved_retention_prevents_next_exclusive_storage_body(self):
        import subprocess
        from unittest.mock import Mock
        from production_runtime import Runtime, RuntimeFailure
        for observation in ('c' * 64, RuntimeFailure('phone_command_failed_daemon_unavailable_exit_1')):
            with self.subTest(observation=type(observation).__name__), tempfile.TemporaryDirectory() as directory:
                runtime = Runtime(lock=Path(directory) / 'release.lock')
                runtime.command = Mock()
                if isinstance(observation, RuntimeFailure):
                    runtime.command.side_effect = observation
                else:
                    runtime.command.return_value = subprocess.CompletedProcess([], 0, observation, '')
                entered = False
                with self.assertRaises(RuntimeFailure):
                    with runtime.exclusive():
                        entered = True
                self.assertFalse(entered)
                runtime.command.assert_called_once()
                self.assertIn('--all', runtime.command.call_args.args[0])

    def test_retention_name_replacement_is_preserved_and_cleanup_uses_exact_id(self):
        import json
        import subprocess
        from unittest.mock import Mock
        from production_runtime import Runtime, RuntimeFailure
        runtime = Runtime()
        identifier = 'c' * 64
        runtime.command = Mock(return_value=subprocess.CompletedProcess([], 0, 'f' * 64, ''))
        with self.assertRaisesRegex(RuntimeFailure, 'identity_changed'):
            runtime.stop_oneoff('fax-retention', 'backend-retention', expected_id=identifier)
        self.assertEqual(runtime.command.call_count, 1)
        projection = [identifier, '/' + runtime.project + '-fax-retention', {
            'com.docker.compose.project': runtime.project,
            'com.docker.compose.service': 'backend-retention', 'com.docker.compose.oneoff': 'True'}]
        runtime.command = Mock(side_effect=[subprocess.CompletedProcess([], 0, value, '')
            for value in (identifier, json.dumps(projection), '', '', '')])
        runtime.stop_oneoff('fax-retention', 'backend-retention', expected_id=identifier)
        cleanup = [call.args[0] for call in runtime.command.call_args_list
                   if call.args[0][:2] in (['docker', 'stop'], ['docker', 'rm'])]
        self.assertEqual(cleanup, [['docker', 'stop', '--time', '10', identifier], ['docker', 'rm', identifier]])
        self.assertIn('id=' + identifier, runtime.command.call_args.args[0])

    def test_retention_timer_catches_up_in_jst_without_private_lock_namespace(self):
        root = REPOSITORY_DIR / 'deploy/postgresql-backup'
        service = (root / 'anshin-phone-fax-retention.service').read_text()
        timer = (root / 'anshin-phone-fax-retention.timer').read_text()
        self.assertIn('--purge-expired', service)
        self.assertIn('PrivateTmp=false', service)
        self.assertIn('Restart=no', service)
        self.assertIn('OnCalendar=*-*-* 00:00:00 Asia/Tokyo', timer)
        self.assertEqual(timer.count('OnCalendar='), 1)
        self.assertIn('Persistent=true', timer)


class Phase1RenderConfigTest(unittest.TestCase):
    def render(self, auth_mode: str, overrides: dict[str, str] | None = None) -> tuple[str, str, int, int]:
        module = load_render_config()
        with tempfile.TemporaryDirectory(prefix="anshin-phone-phase1-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config_dir = temp_dir / "asterisk"
            config_dir.mkdir()
            carrier_password = temp_dir / "carrier_password"
            smartphone_password = temp_dir / "smartphone_password"
            carrier_password.write_text("carrier-test-only", encoding="utf-8")
            smartphone_password.write_text("smartphone-test-only", encoding="utf-8")

            environment = {
                "CARRIER_AUTH_MODE": auth_mode,
                "CARRIER_HOST": "198.51.100.10",
                "CARRIER_PORT": "5060",
                "CARRIER_QUALIFY_FREQUENCY": "30",
                "CARRIER_SOURCE_CIDRS": "198.51.100.0/24,203.0.113.8/32",
                "CARRIER_SIP_USERNAME": "phase1-test",
                "CARRIER_SIP_PASSWORD_FILE": str(carrier_password),
                "SBC_HOST": "sbc.example.test",
                "SBC_PORT": "5060",
                "TEL_DID": "0300000000",
                "FAX_DID": "0300000001",
                "SMARTPHONE_EXTENSION": "2001",
                "SMARTPHONE_QUALIFY_FREQUENCY": "30",
                "ANSHIN_PHONE_TENANT_ID": "anshin-phase1",
                "SMARTPHONE_SIP_PASSWORD_FILE": str(smartphone_password),
            }
            if overrides:
                environment.update(overrides)

            module.TEMPLATE_DIR = TEMPLATE_DIR
            module.CONFIG_DIR = config_dir
            with patch.dict(os.environ, environment, clear=True):
                module.main()

            pjsip_path = config_dir / "pjsip.conf"
            extensions_path = config_dir / "extensions.conf"
            return (
                pjsip_path.read_text(encoding="utf-8"),
                extensions_path.read_text(encoding="utf-8"),
                stat.S_IMODE(pjsip_path.stat().st_mode),
                stat.S_IMODE(extensions_path.stat().st_mode),
            )

    def test_registration_mode_renders_complete_configuration(self) -> None:
        pjsip, extensions, pjsip_mode, extensions_mode = self.render("registration")

        self.assertIn("[carrier-registration]", pjsip)
        self.assertIn("client_uri=sip:phase1-test@198.51.100.10", pjsip)
        self.assertIn("outbound_proxy=sip:sbc.example.test:5060\\;lr", pjsip)
        self.assertIn("match_header=X-Anshin-Source: carrier", pjsip)
        self.assertIn("[2001]", pjsip)
        self.assertIn("aors=2001", pjsip)
        self.assertIn("outbound_proxy=sip:sbc.example.test:5060\\;lr", pjsip)
        self.assertIn("rewrite_contact=no", pjsip)
        self.assertIn("endpoint_identifier_order=auth_username,username,ip", pjsip)
        self.assertNotIn("__", pjsip)
        self.assertNotIn("__", extensions)
        self.assertEqual(pjsip_mode, 0o600)
        self.assertEqual(extensions_mode, 0o600)

    def test_managed_runtime_starts_without_static_device_credentials(self) -> None:
        pjsip, _, _, _ = self.render("ip", {"PBX_EVENT_BACKEND_URL": "http://backend:8000"})
        self.assertIn("#include managed-endpoints.conf", pjsip)
        self.assertNotIn("[2001-auth]", pjsip)
        self.assertNotIn("smartphone-test-only", pjsip)

    def test_backend_endpoint_contract_is_validated_before_config_write(self) -> None:
        import hashlib
        import json
        spec = importlib.util.spec_from_file_location("pbx_management", REPOSITORY_DIR / "deploy/asterisk/scripts/pbx_management.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        content = {"tenant_id": "isolated", "endpoints": [{"id": "isolated-endpoint", "extension": "2001", "password": "1" * 64}]}
        value = {**content, "revision": hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        self.assertEqual(module.validate_configuration(value, "isolated"), value)
        with self.assertRaisesRegex(ValueError, "tenant/schema"):
            module.validate_configuration(value, "foreign")
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            module.validate_configuration({**value, "revision": "0" * 64}, "isolated")
        with self.assertRaisesRegex(ValueError, "values are invalid"):
            module.validate_configuration({**value, "endpoints": [{"id": "isolated-endpoint", "extension": "2001\n[carrier]", "password": "1" * 64}]}, "isolated")

    def test_ip_mode_omits_registration_and_keeps_source_identification(self) -> None:
        pjsip, _, _, _ = self.render("ip")

        self.assertNotIn("[carrier-registration]", pjsip)
        self.assertIn("[carrier-identify]", pjsip)
        self.assertIn("endpoint=carrier-endpoint", pjsip)
        self.assertIn("match_header=X-Anshin-Source: carrier", pjsip)

    def test_dialplan_separates_tel_fax_and_blocks_high_risk_destinations(self) -> None:
        _, extensions, _, _ = self.render("registration")

        self.assertIn("exten => 0300000000,1,NoOp(Anshin Phone inbound TEL", extensions)
        self.assertIn("exten => 0300000001,1,NoOp(Anshin Phone inbound FAX", extensions)
        self.assertIn("exten => 110,1,NoOp(Block emergency call", extensions)
        self.assertIn("exten => 118,1,Goto(110,1)", extensions)
        self.assertIn("exten => 119,1,Goto(110,1)", extensions)
        self.assertIn("exten => _010X.,1,NoOp(Block international call", extensions)
        self.assertIn("exten => _0570X.,1,NoOp(Block premium-rate call", extensions)
        self.assertIn("exten => _0990X.,1,NoOp(Block premium-rate call", extensions)

    def test_dialplan_does_not_log_raw_phone_numbers(self) -> None:
        _, extensions, _, _ = self.render("registration")

        self.assertNotIn("${CALLERID(all)}", extensions)
        self.assertNotIn("NoOp(Reject unassigned inbound DID ${EXTEN})", extensions)
        self.assertNotIn("NoOp(Reject unsupported outbound destination ${EXTEN})", extensions)
        self.assertNotIn("NoOp(Anshin Phone outbound TEL ${ARG1})", extensions)

    def test_fax_mode_uses_supported_application_options(self) -> None:
        _, audio, _, _ = self.render("ip", {"FAX_MEDIA_MODE": "audio"})
        _, t38, _, _ = self.render("ip", {"FAX_MEDIA_MODE": "t38"})
        self.assertIn("ReceiveFAX(${FAX_FILE},F)", audio)
        self.assertIn("SendFAX(${FAX_SEND_FILE},F)", audio)
        self.assertNotIn("FAXOPT(force_audio)", audio)
        self.assertIn("ReceiveFAX(${FAX_FILE},f)", t38)
        with self.assertRaisesRegex(RuntimeError, "FAX_MEDIA_MODE"):
            self.render("ip", {"FAX_MEDIA_MODE": "invalid"})

    def test_invalid_carrier_source_network_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.render("ip", {"CARRIER_SOURCE_CIDRS": "not-a-network"})

    def test_invalid_did_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "TEL_DID must contain"):
            self.render("registration", {"TEL_DID": "+81300000000"})

    def test_newline_in_runtime_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "contains a newline"):
            self.render("registration", {"CARRIER_HOST": "carrier.example\nmalicious"})

    def test_secret_is_not_rendered_as_a_quoted_literal(self) -> None:
        pjsip, _, _, _ = self.render("registration")

        self.assertIn("password=carrier-test-only", pjsip)
        self.assertIn("password=smartphone-test-only", pjsip)
        self.assertNotIn('password="carrier-test-only"', pjsip)

    def test_unsafe_secret_characters_are_rejected(self) -> None:
        module = load_render_config()
        with tempfile.TemporaryDirectory(prefix="anshin-phone-phase1-secret-") as temp_dir_name:
            secret_path = Path(temp_dir_name) / "secret"
            secret_path.write_text("unsafe;secret-value", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"TEST_SECRET_FILE": str(secret_path)},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "unsupported Asterisk config"):
                    module.secret("TEST_SECRET")


if __name__ == "__main__":
    unittest.main(verbosity=2)
