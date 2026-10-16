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
                "ANSHIN_PHONE_FAX_RETENTION_SECONDS": "604800",
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
        for name in ("backend", "backend-migrate"):
            service = model["services"][name]
            self.assertNotIn("build", service)
            self.assertIn("@sha256:", service["image"])
            self.assertEqual(service["environment"]["ANSHIN_PHONE_TELEPHONY_ENABLED"], "false")
            self.assertEqual(service["environment"]["ANSHIN_PHONE_FAX_RETENTION_SECONDS"], "604800")
        self.assertEqual(model["services"]["backend"]["image"], model["services"]["backend-migrate"]["image"])
        self.assertIn("phone-auth-egress", model["services"]["backend"]["networks"])
        self.assertEqual(set(model["services"]["postgres"]["networks"]), {"phone-data"})
        self.assertTrue(model["networks"]["phone-data"]["internal"])
        self.assertNotIn("carrier_sip_password", model["secrets"])
        ports = model["services"]["backend"]["ports"]
        self.assertTrue(all(port["host_ip"] == "127.0.0.1" for port in ports))

    def test_production_never_falls_back_to_local_retention_or_source_build(self):
        for required in ("ANSHIN_PHONE_FAX_RETENTION_SECONDS", "ANSHIN_PHONE_BACKEND_IMAGE"):
            with self.subTest(required=required):
                result, model = self.render_production(omit=required)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(model)


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
