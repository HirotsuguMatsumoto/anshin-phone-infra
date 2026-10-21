#!/usr/bin/env python3
"""Own Compose transitions inside the dedicated Phone guest.

The central release owner supplies qualified source and an immutable image.
This module does not select releases, fetch Git, build images, or issue receipts.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
STATE = Path('/var/lib/anshin-phone/release')
SECRETS = Path('/etc/anshin-phone/secrets')
PROJECT = 'anshin-phone-production'
LOCK = Path('/tmp/anshin-ms-a2-1-platform-release.lock')
IMAGE = re.compile(r'ghcr\.io/hirotsugumatsumoto/anshin-phone-backend@sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
SETTINGS_CHECK = (
    'from app.core.config import get_settings; s=get_settings(); '
    'assert s.environment=="production" and not s.telephony_enabled; '
    'assert s.fax_retention_policy=="cloco_previous_month" and s.fax_retention_seconds is None; '
    'assert s.oidc_issuer=="https://auth.anshin.care/realms/anshin" and s.oidc_audience=="anshin-phone"; '
    'assert s.oidc_required_acr>=2 and s.fax_storage_key and s.sip_master_secret; '
    'from app.core.fax_storage import cipher; cipher()'
)


def run_owned_process(argv, **kwargs):
    """A cancelled local CLI must not outlive its release owner."""
    timeout = kwargs.pop('timeout')
    termination_grace = kwargs.pop('termination_grace', 5)
    process = subprocess.Popen(argv, start_new_session=True, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    except BaseException:
        for stop_signal in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, stop_signal)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=termination_grace)
            except subprocess.TimeoutExpired:
                if stop_signal == signal.SIGKILL:
                    raise RuntimeFailure('phone_command_children_unknown') from None
        raise


class RuntimeFailure(RuntimeError):
    """Expose an enum, never raw Docker output or consumer exceptions."""

    def __init__(self, reason, *, initial_recovery=None):
        super().__init__(reason)
        self.initial_recovery = initial_recovery


class Runtime:
    def __init__(self, *, root=ROOT, state=STATE, secrets=SECRETS, project=PROJECT,
                 lock=LOCK, runner=run_owned_process, backend_port=8010,
                 backend_bind='10.91.40.10', transport=None, compose_extra_files=(), volume_stat=None):
        self.root, self.state, self.secrets = Path(root), Path(state), Path(secrets)
        self.project, self.lock, self.runner = project, Path(lock), runner
        self.backend_port = backend_port
        self.backend_bind = backend_bind
        self.transport = dict(transport or {})
        self.compose_extra_files = tuple(map(Path, compose_extra_files))
        self.volume_stat = volume_stat or self.local_volume_stat

    @staticmethod
    def local_volume_stat(path):
        metadata = Path(path).lstat()
        return {'mode': metadata.st_mode, 'device': metadata.st_dev, 'inode': metadata.st_ino}

    def command(self, argv, *, env=None, timeout=180, allow_failure=False, termination_grace=5):
        try:
            result = self.runner(argv, env=env or self.environment(), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                                 **({'termination_grace': termination_grace} if termination_grace != 5 else {}))
        except subprocess.TimeoutExpired:
            raise RuntimeFailure('phone_command_timeout') from None
        if result.returncode and not allow_failure:
            diagnostic = 'consumer_failure'
            lower = result.stderr.lower()
            for kind, patterns in (
                ('access_denied', ('unauthorized', 'authentication required', 'permission denied', 'denied:')),
                ('capacity', ('no space left', 'out of memory')),
                ('platform', ('no matching manifest', 'exec format error')),
                ('missing_resource', ('not found', 'no such file')),
                ('daemon_unavailable', ('cannot connect to the docker daemon',)),
            ):
                if any(pattern in lower for pattern in patterns):
                    diagnostic = kind
                    break
            raise RuntimeFailure(f'phone_command_failed_{diagnostic}_exit_{result.returncode}')
        return result

    def environment(self, profile=None):
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'HOME': '/root', 'DOCKER_HOST': 'unix:///var/run/docker.sock'}
        # Fixture transport is explicit; the production CLI always owns the
        # guest-local daemon and inherits no ambient Compose/AWS/DB inputs.
        env.update(self.transport)
        env.update(ANSHIN_PHONE_SECRET_DIR=str(self.secrets),
                   ANSHIN_PHONE_BACKEND_PORT=str(self.backend_port),
                   ANSHIN_PHONE_BACKEND_BIND_IP=self.backend_bind)
        if profile:
            env['ANSHIN_PHONE_BACKEND_IMAGE'] = profile['backend_image']
        return env

    def compose(self, profile, *args, timeout=180, allow_failure=False):
        command = ['docker', 'compose', '--project-name', self.project,
            '--project-directory', profile['source_root'], '--env-file', '/dev/null',
            '--file', str(Path(profile['source_root']) / 'compose.production.yaml')]
        # Explicit fixture input only. The production CLI never obtains extra
        # files from argv or ambient COMPOSE_FILE.
        for path in self.compose_extra_files:
            command.extend(('--file', str(path)))
        return self.command([*command, *args],
            env=self.environment(profile), timeout=timeout, allow_failure=allow_failure)

    def require_retention_absent(self):
        name = self.project + '-fax-retention'
        current = self.command(['docker', 'ps', '--all', '--quiet', '--no-trunc',
            '--filter', 'name=^/' + name + '$'], timeout=10).stdout.strip()
        if current:
            raise RuntimeFailure('phone_retention_existing_oneoff_preserved')

    @contextmanager
    def exclusive(self):
        descriptor = os.open(self.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeFailure('phone_release_busy') from None
            self.require_retention_absent()
            yield

    def profile(self):
        path = self.state / 'runtime.json'
        return json.loads(path.read_text()) if path.exists() else None

    def observation(self, *, timeout=None):
        """Read only identity/state fields; Docker inspect's Env stays private."""
        selector = f'label=com.docker.compose.project={self.project}'
        deadline = None if timeout is None else time.monotonic() + timeout
        def budget():
            remaining = 180 if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeFailure('phone_observation_deadline')
            return remaining
            return min(180, remaining)
        ids = self.command(['docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter', selector], timeout=budget()).stdout.split()
        names = self.command(['docker', 'volume', 'ls', '--format', '{{.Name}}'], timeout=budget()).stdout.split()
        volumes = []
        for name in sorted(names):
            if name not in {self.project + '_postgres-data', self.project + '_fax-protected-storage'}:
                continue
            def inspect_volume():
                rows = json.loads(self.command(['docker', 'volume', 'inspect', name], timeout=budget()).stdout)
                if not isinstance(rows, list) or len(rows) != 1:
                    raise RuntimeFailure('phone_volume_identity_invalid')
                row = rows[0]
                labels = row.get('Labels') or {}
                if (row.get('Name') != name or row.get('Driver') != 'local' or row.get('Scope') != 'local'
                        or row.get('Options') not in (None, {})
                        or row.get('Mountpoint') != '/var/lib/docker/volumes/' + name + '/_data'
                        or labels.get('com.docker.compose.project') != self.project
                        or labels.get('com.docker.compose.volume') != name[len(self.project) + 1:]
                        or set(labels) - {'com.docker.compose.project', 'com.docker.compose.volume',
                                          'com.docker.compose.version', 'com.docker.compose.config-hash'}
                        or ('com.docker.compose.config-hash' in labels
                            and not re.fullmatch(r'[0-9a-f]{64}', labels['com.docker.compose.config-hash']))
                        or not isinstance(row.get('CreatedAt'), str)):
                    raise RuntimeFailure('phone_volume_identity_invalid')
                return {key: row[key] for key in ('Name', 'Driver', 'Scope', 'CreatedAt', 'Mountpoint', 'Labels', 'Options')}
            observed = inspect_volume()
            backing = self.volume_stat(observed['Mountpoint'])
            if (not isinstance(backing, dict) or set(backing) != {'mode', 'device', 'inode'}
                    or type(backing['mode']) is not int or not stat.S_ISDIR(backing['mode'])
                    or any(type(backing[key]) is not int or backing[key] <= 0 for key in ('device', 'inode'))
                    or inspect_volume() != observed):
                raise RuntimeFailure('phone_volume_identity_changed')
            volumes.append({**observed, 'backing': {key: backing[key] for key in ('device', 'inode')}})
        containers = []
        for identifier in sorted(ids):
            projected = self.command(['docker', 'inspect', '--format',
                '{{json .Id}} {{json .Image}} {{json .State.StartedAt}} {{json .RestartCount}}', identifier], timeout=budget()).stdout.strip()
            containers.append(projected)
        return {'containers': containers, 'volumes': volumes}

    def health(self, profile, *, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        def budget(default):
            remaining = default if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeFailure('phone_health_deadline')
            return min(default, remaining)
        identifiers = self.compose(profile, 'ps', '--quiet', 'backend', timeout=budget(180)).stdout.split()
        if len(identifiers) != 1:
            raise RuntimeFailure('phone_backend_identity_missing')
        image = self.command(['docker', 'inspect', '--format', '{{.Config.Image}}', identifiers[0]], timeout=budget(180)).stdout.strip()
        if image != profile['backend_image']:
            raise RuntimeFailure('phone_backend_image_mismatch')
        self.compose(profile, 'exec', '-T', 'backend', 'python', '-c', SETTINGS_CHECK, timeout=budget(30))
        self.compose(profile, 'exec', '-T', 'backend', 'python', '-c',
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=5).read()", timeout=budget(15))
        result = self.compose(profile, 'ps', '--format', 'json', 'backend', 'postgres', timeout=budget(180))
        # Compose v2 versions emit a JSON array or one object per line.
        raw = result.stdout.strip()
        rows = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines()]
        if ({row.get('Service') for row in rows} != {'backend', 'postgres'} or
            any(row.get('State') != 'running' or row.get('Health') != 'healthy' for row in rows)):
            raise RuntimeFailure('phone_runtime_unhealthy')
        return {'status': 'healthy', 'backend_sha': profile['backend_sha'],
                'infra_sha': profile['infra_sha'], 'telephony_enabled': False}

    def stop_oneoff(self, suffix, service, *, expected_id=None, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        def bounded_command(argv, **kwargs):
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeFailure('phone_oneoff_cleanup_deadline')
                kwargs['timeout'] = min(kwargs.get('timeout', 180), remaining)
            return self.command(argv, **kwargs)
        name = self.project + '-' + suffix
        if expected_id is None:
            result = bounded_command(['docker', 'ps', '--all', '--quiet', '--filter', f'name=^/{name}$',
                '--filter', f'label=com.docker.compose.project={self.project}',
                '--filter', 'label=com.docker.compose.service=' + service])
            if result.stdout.strip():
                bounded_command(['docker', 'stop', '--time', '10', name], timeout=30)
                bounded_command(['docker', 'rm', name], timeout=30)
            return
        if not re.fullmatch(r'[0-9a-f]{64}', expected_id):
            raise RuntimeFailure('phone_oneoff_expected_identity_invalid')
        exact_id = ['docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter', 'id=' + expected_id]
        current = bounded_command(['docker', 'ps', '--all', '--quiet', '--no-trunc',
            '--filter', f'name=^/{name}$'], timeout=10).stdout.split()
        if not current:
            if bounded_command(exact_id, timeout=10).stdout.strip():
                raise RuntimeFailure('phone_oneoff_identity_changed')
            return
        if current != [expected_id]:
            raise RuntimeFailure('phone_oneoff_identity_changed')
        value = json.loads(bounded_command(['docker', 'inspect', '--format',
            '[{{json .Id}},{{json .Name}},{{json .Config.Labels}}]', expected_id], timeout=10).stdout)
        if (not isinstance(value, list) or len(value) != 3
                or value[0] != expected_id or value[1] != '/' + name
                or not isinstance(value[2], dict)
                or value[2].get('com.docker.compose.project') != self.project
                or value[2].get('com.docker.compose.service') != service
                or value[2].get('com.docker.compose.oneoff') != 'True'):
            raise RuntimeFailure('phone_oneoff_identity_changed')
        bounded_command(['docker', 'stop', '--time', '10', expected_id], timeout=30)
        bounded_command(['docker', 'rm', expected_id], timeout=30)
        if bounded_command(exact_id, timeout=10).stdout.strip():
            raise RuntimeFailure('phone_oneoff_cleanup_unconfirmed')

    def backup(self):
        # The existing shared producer takes the same guest lock. Run it
        # before acquiring that lock, then reobserve before any mutation.
        result = self.command(['python3', '/opt/anshin-phone-backup/scripts/phone_postgresql_backup_adapter.py',
                              '--scheduled-backup'], timeout=1500, termination_grace=260)
        try:
            value = json.loads(result.stdout)
            if (not isinstance(value, dict) or set(value) != {'status', 'source_fixed_sha', 'runtime_transition'}
                    or value['status'] != 'completed' or not isinstance(value['runtime_transition'], dict)
                    or set(value['runtime_transition']) != {'before', 'after'}):
                raise ValueError
        except (ValueError, TypeError):
            raise RuntimeFailure('phone_backup_result_invalid') from None
        return value

    def save(self, profile):
        self.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = self.state / 'runtime.json'
        temporary = self.state / 'runtime.json.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(profile, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)

    def deploy(self, image, backend_sha, infra_sha, *, initial_recovery=None):
        if not IMAGE.fullmatch(image) or not SHA.fullmatch(backend_sha) or not SHA.fullmatch(infra_sha):
            raise RuntimeFailure('phone_release_input_invalid')
        candidate = {'source_root': str(self.root), 'backend_image': image,
                     'backend_sha': backend_sha, 'infra_sha': infra_sha}
        previous = self.profile()
        before = self.observation()
        if initial_recovery is not None:
            # The central release owner supplies its existing failed result.
            # It owns receipt/source binding; this consumer only rechecks the
            # exact resources and candidate before forward repair.
            if (previous is not None or not isinstance(initial_recovery, dict)
                    or set(initial_recovery) != {'candidate', 'observation'}
                    or initial_recovery['candidate'] != candidate
                    or initial_recovery['observation'] != before
                    or not (before['containers'] or before['volumes'])):
                raise RuntimeFailure('phone_initial_recovery_identity_changed')
        if previous:
            self.health(previous)
            backup = self.backup()
            if (backup['source_fixed_sha'] != previous['backend_sha']
                    or backup['runtime_transition']['before'] != before):
                raise RuntimeFailure('phone_runtime_changed_during_backup')
            before = backup['runtime_transition']['after']
        elif (before['containers'] or before['volumes']) and initial_recovery is None:
            raise RuntimeFailure('phone_existing_data_without_profile')
        with self.exclusive():
            if self.profile() != previous or self.observation() != before:
                raise RuntimeFailure('phone_runtime_changed_during_backup')
            # Validate the actual consumer settings before DB/container changes.
            self.compose(candidate, 'pull', 'postgres', 'backend', 'backend-migrate', timeout=600)
            revision = self.command(['docker', 'image', 'inspect', '--format',
                '{{index .Config.Labels "org.opencontainers.image.revision"}}', image]).stdout.strip()
            if revision != backend_sha:
                raise RuntimeFailure('phone_image_revision_mismatch')
            settings_unknown = False
            try:
                self.compose(candidate, 'run', '--rm', '--no-deps', '--name', self.project + '-settings',
                             '--entrypoint', 'python', 'backend', '-c', SETTINGS_CHECK, timeout=60)
            except RuntimeFailure as error:
                settings_unknown = str(error) == 'phone_command_children_unknown'
                raise
            finally:
                if not settings_unknown:
                    self.stop_oneoff('settings', 'backend')
            try:
                self.compose(candidate, 'up', '--detach', '--wait', '--wait-timeout', '90', 'postgres')
                self.compose(candidate, 'run', '--rm', '--no-deps', '--name', self.project + '-migration',
                             'backend-migrate', timeout=180)
                self.compose(candidate, 'up', '--detach', '--no-deps', '--wait', '--wait-timeout', '90', 'backend')
                result = self.health(candidate)
                self.save(candidate)
                return {**result, 'status': 'deployed'}
            except (RuntimeFailure, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
                if isinstance(error, RuntimeFailure) and str(error) == 'phone_command_children_unknown':
                    raise
                # A timed-out Compose CLI can leave its one-off migration alive.
                # Stop that owned process before attempting application rollback.
                self.stop_oneoff('migration', 'backend-migrate')
                if previous:
                    self.compose(previous, 'up', '--detach', '--no-deps', '--wait', '--wait-timeout', '90', 'backend')
                    self.health(previous)
                    return {'status': 'rolled_back', 'backend_sha': previous['backend_sha'],
                            'infra_sha': previous['infra_sha']}
                stopped = self.compose(candidate, 'stop', 'backend', allow_failure=True)
                if stopped.returncode:
                    raise RuntimeFailure('phone_initial_cleanup_unconfirmed') from None
                # Capture under the same release lock, before any subsequent
                # candidate can change these resources. The central owner
                # binds this existing failure result, not a later observation.
                raise RuntimeFailure('phone_initial_deploy_failed_data_preserved',
                    initial_recovery={'candidate': candidate, 'observation': self.observation()}) from None


def main():
    def terminate(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('deploy', 'health'))
    parser.add_argument('--backend-image')
    parser.add_argument('--backend-sha')
    parser.add_argument('--infra-sha')
    args = parser.parse_args()
    runtime = Runtime()
    try:
        if args.operation == 'deploy':
            result = runtime.deploy(args.backend_image or '', args.backend_sha or '', args.infra_sha or '')
        else:
            profile = runtime.profile()
            if not profile:
                raise RuntimeFailure('phone_runtime_not_installed')
            result = runtime.health(profile)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] in {'deployed', 'healthy'} else 1
    except (RuntimeFailure, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error) if isinstance(error, RuntimeFailure)
                          else 'phone_runtime_input_or_state_invalid'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
