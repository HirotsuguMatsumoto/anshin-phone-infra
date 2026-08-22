#!/usr/bin/env python3
"""Evaluate a real-call quality measurement JSON against Phase 1 thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


LIMITS = {
    "packet_loss_percent": 1.0,
    "jitter_ms": 30.0,
    "round_trip_ms": 300.0,
    "minimum_mos": 3.6,
    "minimum_duration_seconds": 1800.0,
}


def evaluate(data: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if data.get("two_way_audio") is not True:
        failures.append("双方向音声が確認できない")
    for name in ("packet_loss_percent", "jitter_ms", "round_trip_ms"):
        value = float(data[name])
        if value > LIMITS[name]:
            failures.append(f"{name}={value} exceeds {LIMITS[name]}")
    mos = float(data["mos"])
    if mos < LIMITS["minimum_mos"]:
        failures.append(f"mos={mos} below {LIMITS['minimum_mos']}")
    duration = float(data["duration_seconds"])
    if duration < LIMITS["minimum_duration_seconds"]:
        failures.append(f"duration_seconds={duration} below {LIMITS['minimum_duration_seconds']}")
    if data.get("unexpected_disconnects") != 0:
        failures.append("予期しない切断がある")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("measurement", type=Path)
    args = parser.parse_args()
    data = json.loads(args.measurement.read_text(encoding="utf-8"))
    failures = evaluate(data)
    print(json.dumps({"result": "FAIL" if failures else "PASS", "failures": failures}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
