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
    def render(self, overrides: dict[str, str] | None = None) -> str:
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
            module.OUTPUT = Path(temp_dir) / "kamailio.cfg"
            with patch.dict(os.environ, environment, clear=True):
                module.main()
            return module.OUTPUT.read_text(encoding="utf-8")

    def test_renders_source_boundaries_and_media_relay(self) -> None:
        config = self.render()
        self.assertIn("advertise 192.0.2.10:5060", config)
        self.assertIn("listen=udp:172.31.251.40:5060 advertise 172.31.251.40:5060", config)
        self.assertIn("src_ip == 172.31.251.20/32", config)
        self.assertIn("src_ip == 198.51.100.0/24", config)
        self.assertIn("src_ip == 10.20.0.0/24", config)
        self.assertIn('rtpengine_sock", "udp:rtpengine:2223"', config)
        self.assertIn("direction=external direction=internal", config)
        self.assertNotIn("__", config)

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
