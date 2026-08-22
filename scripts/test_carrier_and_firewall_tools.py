from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_carrier_intake import validate


class CarrierIntakeTest(unittest.TestCase):
    def test_example_is_structurally_valid_but_pending_approval(self) -> None:
        data = json.loads((Path(__file__).parents[1] / "configs/carrier-intake.example.json").read_text())
        findings = validate(data)
        self.assertEqual(set(findings), {
            "emergency_calling is not confirmed",
            "approved_by is required before production use",
        })

    def test_invalid_cidr_is_rejected(self) -> None:
        data = json.loads((Path(__file__).parents[1] / "configs/carrier-intake.example.json").read_text())
        data["sip"]["source_cidrs"] = ["not-a-cidr"]
        self.assertIn("source_cidrs must contain valid CIDRs", validate(data))


if __name__ == "__main__":
    unittest.main()
