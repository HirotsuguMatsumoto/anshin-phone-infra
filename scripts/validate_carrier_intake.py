#!/usr/bin/env python3
"""Validate carrier connection information without reading a SIP password."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import re


HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
REQUIRED_SIP = {"host", "port", "transport", "auth_mode", "source_cidrs", "rtp_cidrs", "rtp_ports", "codecs", "dtmf", "did_format", "caller_id_header"}


def validate(data: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    sip = data.get("sip")
    if not isinstance(sip, dict):
        return errors + ["sip must be an object"]
    missing = REQUIRED_SIP - sip.keys()
    if missing:
        errors.append("missing sip fields: " + ", ".join(sorted(missing)))
        return errors
    if not isinstance(sip["host"], str) or not HOST_RE.fullmatch(sip["host"]):
        errors.append("invalid SIP host")
    if sip["transport"] not in {"UDP", "TCP", "TLS"}:
        errors.append("transport must be UDP, TCP or TLS")
    if sip["auth_mode"] not in {"registration", "ip"}:
        errors.append("auth_mode must be registration or ip")
    for field in ("source_cidrs", "rtp_cidrs"):
        try:
            values = sip[field]
            if not isinstance(values, list) or not values:
                raise ValueError
            for value in values:
                ipaddress.ip_network(str(value), strict=False)
        except ValueError:
            errors.append(f"{field} must contain valid CIDRs")
    if data.get("emergency_calling") == "not-confirmed":
        errors.append("emergency_calling is not confirmed")
    if data.get("approved_by") in {None, ""}:
        errors.append("approved_by is required before production use")
    reference = data.get("secret_reference")
    if not isinstance(reference, str) or not reference.startswith("external-"):
        errors.append("secret_reference must identify external storage, not contain a secret")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("intake", type=Path)
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.intake.read_text(encoding="utf-8"))
    errors = validate(data)
    pending = {"emergency_calling is not confirmed", "approved_by is required before production use"}
    blocking = [error for error in errors if not args.allow_pending or error not in pending]
    print(json.dumps({"result": "PASS" if not blocking else "FAIL", "findings": errors}, ensure_ascii=False))
    return 0 if not blocking else 1


if __name__ == "__main__":
    raise SystemExit(main())
