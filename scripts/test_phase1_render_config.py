#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
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
    def render_production(self, *, omit: str | None = None):
        import json
        import subprocess
        with tempfile.TemporaryDirectory(prefix="phone-compose-") as directory:
            env = {key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT") if key in os.environ}
            env.update({
                "ANSHIN_PHONE_SECRET_DIR": directory,
                "ANSHIN_PHONE_BACKEND_IMAGE": "ghcr.io/hirotsugumatsumoto/anshin-phone-backend@sha256:" + "a" * 64,
            })
            if omit:
                env.pop(omit)
            result = subprocess.run(["docker", "compose", "--file", str(REPOSITORY_DIR / "compose.production.yaml"),
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

    def test_production_retention_input_is_accepted_by_backend_settings(self):
        import json
        import subprocess
        import sys
        from resolve_phone_backend import resolve_backend

        result, model = self.render_production()
        self.assertEqual(result.returncode, 0, result.stderr)
        backend = resolve_backend(REPOSITORY_DIR, os.getenv("ANSHIN_PHONE_BACKEND_DIR"))
        for name in ("backend", "backend-migrate"):
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
                candidate_health_failure=False, rollback_health_failure=False):
        import json
        import subprocess
        from production_runtime import Runtime
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
                if migration_timeout:
                    raise subprocess.TimeoutExpired(argv, 180)
                code = int(migration_failure)
            elif argv[:3] == ['docker', 'ps', '--all'] and any('migration' in arg for arg in argv):
                output = 'owned-migration' if migration_timeout else ''
            elif argv[:2] == ['docker', 'stop']:
                code = int(stop_failure)
            elif 'compose' in argv and 'stop' in argv:
                code = int(stop_failure)
            return subprocess.CompletedProcess(argv, code, output, 'private diagnostic never printed')

        runtime = Runtime(root=root / 'candidate', state=root / 'state', secrets=root / 'secrets',
                          project='phone-unit', lock=root / 'release.lock', runner=runner)
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
        with patch.dict(os.environ, {'DOCKER_HOST': 'tcp://foreign.invalid:2375', 'DOCKER_CONTEXT': 'foreign'}):
            env = Runtime().environment()
            self.assertEqual(env['DOCKER_HOST'], 'unix:///var/run/docker.sock')
            self.assertNotIn('DOCKER_CONTEXT', env)


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
