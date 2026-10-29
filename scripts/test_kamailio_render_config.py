#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "deploy/kamailio/scripts/render_config.py"
TEMPLATE = ROOT / "deploy/kamailio/config/kamailio.cfg.template"


def load_renderer():
    spec = importlib.util.spec_from_file_location("kamailio_render_config", RENDERER)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load Kamailio renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KamailioRenderConfigTest(unittest.TestCase):
    def render(self, overrides: dict[str, str] | None = None, *, fixture_template=None) -> str:
        module = load_renderer()
        environment = {
            "SBC_ADVERTISED_IP": "192.0.2.10",
            "SBC_EDGE_IP": "172.31.250.40",
            "SBC_INTERNAL_IP": "172.31.251.40",
            "ASTERISK_HOST": "asterisk",
            "ASTERISK_PORT": "5060",
            "ASTERISK_SOURCE_CIDRS": "172.31.251.20/32",
            "CARRIER_SOURCE_CIDRS": "198.51.100.0/24,203.0.113.8/32",
            "SMARTPHONE_SOURCE_CIDRS": "10.20.0.0/24",
            "RTPENGINE_SOCKET": "udp:rtpengine:2223",
        }
        if overrides:
            environment.update(overrides)
        with tempfile.TemporaryDirectory(prefix="anshin-phone-kamailio-") as temp_dir:
            module.TEMPLATE = TEMPLATE
            if fixture_template is not None:
                module.TEMPLATE = Path(temp_dir) / 'fixture.template'
                module.TEMPLATE.write_text(fixture_template)
            module.OUTPUT = Path(temp_dir) / "kamailio.cfg"
            with patch.dict(os.environ, environment, clear=True):
                module.main()
            return module.OUTPUT.read_text(encoding="utf-8")

    def test_simulator_template_uses_real_renderer_before_runtime(self):
        from softphone_sip_fixture import simulator_template
        config = self.render(fixture_template=simulator_template(ROOT,'10.0.2.2',24001,'192.168.65.1'))
        self.assertNotIn('__',config)
        self.assertIn('advertise 10.0.2.2:24001',config)
        self.assertLess(config.index('Keepalive'),config.index('Fixture Source Mismatch'))
        self.assertIn('src_ip == 172.31.251.20/32',config)
        reply = config.split('onreply_route[MANAGE_REPLY] {')[1]
        self.assertIn('src_ip == 192.168.65.1/32',reply)
        self.assertIn('add_contact_alias()',reply)

    def test_renders_source_boundaries_and_media_relay(self) -> None:
        config = self.render()
        self.assertIn("advertise 192.0.2.10:5060", config)
        self.assertIn("listen=udp:172.31.251.40:5060 advertise 172.31.251.40:5060", config)
        self.assertIn("src_ip == 172.31.251.20/32", config)
        self.assertNotIn("src_ip == 198.51.100.0/24", config)
        self.assertNotIn("X-Anshin-Source: carrier", config)
        self.assertIn("src_ip == 10.20.0.0/24", config)
        self.assertIn('rtpengine_sock", "udp:rtpengine:2223"', config)
        self.assertIn("direction=external direction=internal", config)
        self.assertNotIn("__", config)

    def test_sip_logs_do_not_include_destination_or_call_identifier(self) -> None:
        config = self.render()

        self.assertNotIn("ruri=$ru", config)
        self.assertNotIn("$hdr(Route)", config)
        self.assertNotIn("call-id=$ci", config)

    def test_rejects_invalid_source_network(self) -> None:
        with self.assertRaises(ValueError):
            self.render({"SMARTPHONE_SOURCE_CIDRS": "not-a-network"})

    def test_rejects_invalid_rtpengine_socket(self) -> None:
        with self.assertRaisesRegex(ValueError, "RTPENGINE_SOCKET"):
            self.render({"RTPENGINE_SOCKET": "http://rtpengine"})

    def test_rejects_newline_in_host(self) -> None:
        with self.assertRaisesRegex(ValueError, "one line"):
            self.render({"ASTERISK_HOST": "asterisk\nmalicious"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
