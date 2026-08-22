from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_sip_enrollment_bundle import build_bundle
from evaluate_voice_quality import evaluate


class EnrollmentTest(unittest.TestCase):
    def test_bundle_contains_single_use_expiry_and_sip_uri(self) -> None:
        bundle = build_bundle("sip.test.invalid", 5060, "2001", "synthetic-password-123", 10)
        self.assertTrue(bundle["consume_once"])
        self.assertIn("sip:2001:synthetic-password-123@sip.test.invalid", bundle["sip_uri"])

    def test_short_password_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_bundle("sip.test.invalid", 5060, "2001", "short", 10)


class VoiceQualityTest(unittest.TestCase):
    def test_passing_measurement(self) -> None:
        self.assertEqual(evaluate({
            "two_way_audio": True,
            "packet_loss_percent": 0.2,
            "jitter_ms": 8,
            "round_trip_ms": 90,
            "mos": 4.2,
            "duration_seconds": 1800,
            "unexpected_disconnects": 0,
        }), [])

    def test_one_way_audio_and_thresholds_fail(self) -> None:
        failures = evaluate({
            "two_way_audio": False,
            "packet_loss_percent": 2,
            "jitter_ms": 40,
            "round_trip_ms": 400,
            "mos": 3.0,
            "duration_seconds": 60,
            "unexpected_disconnects": 1,
        })
        self.assertGreaterEqual(len(failures), 7)


if __name__ == "__main__":
    unittest.main()
