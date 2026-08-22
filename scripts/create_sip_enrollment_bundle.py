#!/usr/bin/env python3
"""Create a short-lived SIP client enrollment bundle outside the repository."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")


def build_bundle(host: str, port: int, extension: str, password: str, ttl_minutes: int) -> dict[str, object]:
    if not HOST_RE.fullmatch(host):
        raise ValueError("host must be a DNS name or IP address")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if not re.fullmatch(r"[0-9]{3,8}", extension):
        raise ValueError("extension must contain 3 to 8 digits")
    if not 1 <= ttl_minutes <= 15:
        raise ValueError("ttl must be between 1 and 15 minutes")
    if len(password) < 16 or "\n" in password or "\r" in password:
        raise ValueError("password must be one line and at least 16 characters")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    uri = f"sip:{quote(extension)}:{quote(password, safe='')}@{host}:{port};transport=udp"
    return {
        "schema_version": 1,
        "kind": "anshin-phone-sip-enrollment",
        "expires_at": expires_at.isoformat(),
        "consume_once": True,
        "sip_uri": uri,
        "settings": {
            "server": host,
            "port": port,
            "transport": "UDP",
            "username": extension,
            "auth_username": extension,
            "outbound_proxy": host,
            "register": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5060)
    parser.add_argument("--extension", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ttl-minutes", type=int, default=10)
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("refusing to write a credential bundle inside the repository")
    password = args.password_file.read_text(encoding="utf-8").strip()
    bundle = build_bundle(args.host, args.port, args.extension, password, args.ttl_minutes)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    print(f"created short-lived enrollment bundle: {output} (mode 0600)")
    print("delete it immediately after the device imports the settings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
