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
