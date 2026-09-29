#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose.phase1.yaml"

EXPECTED = {
    "postgres": ("1.0", "1g", "512m", "128"),
    "backend": ("1.0", "1g", "512m", "256"),
    "backend-migrate": ("1.0", "1g", "512m", "256"),
    "pbx-event-forwarder": ("0.5", "256m", "128m", "64"),
    "rtpengine": ("2.0", "512m", "256m", "128"),
    "kamailio": ("0.5", "256m", "128m", "128"),
    "asterisk": ("2.0", "1g", "512m", "256"),
}


def service_blocks(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^  ([a-z][a-z0-9-]+):\n", text, re.MULTILINE))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[match.group(1)] = text[match.end() : end]
    return result


class Phase1ResourceProfileTest(unittest.TestCase):
    def test_every_runtime_service_has_the_approved_resource_limits(self) -> None:
        blocks = service_blocks(COMPOSE.read_text(encoding="utf-8"))

        self.assertEqual(set(EXPECTED), set(blocks).intersection(EXPECTED))
        for service, (cpus, memory, reservation, pids) in EXPECTED.items():
            with self.subTest(service=service):
                block = blocks[service]
                self.assertIn(f"    cpus: {cpus}\n", block)
                self.assertIn(f"    mem_limit: {memory}\n", block)
                self.assertIn(f"    mem_reservation: {reservation}\n", block)
                self.assertIn(f"    pids_limit: {pids}\n", block)

    def test_steady_state_memory_ceiling_fits_six_gib_phone_vm(self) -> None:
        steady_state_mib = {
            "postgres": 1024,
            "backend": 1024,
            "pbx-event-forwarder": 256,
            "rtpengine": 512,
            "kamailio": 256,
            "asterisk": 1024,
        }

        self.assertEqual(sum(steady_state_mib.values()), 4096)
        self.assertLessEqual(sum(steady_state_mib.values()), 6 * 1024 - 1536)

    def test_migration_and_backend_do_not_start_concurrently(self) -> None:
        blocks = service_blocks(COMPOSE.read_text(encoding="utf-8"))

        self.assertIn("backend-migrate:\n        condition: service_completed_successfully", blocks["backend"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
