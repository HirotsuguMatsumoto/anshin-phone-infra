#!/usr/bin/env python3
"""Write a masked PBX event to an atomic local spool file."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid


SPOOL_DIR = Path(os.getenv("PBX_EVENT_SPOOL_DIR", "/var/spool/asterisk/anshin-events"))


def masked_number(value: str) -> str:
    if "*" in value and re.fullmatch(r"[0-9*]{4,32}", value):
        return value
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) >= 8:
        return f"{digits[:3]}****{digits[-4:]}"
    return "*" * max(len(digits), 4)


def safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise ValueError("invalid PBX unique identifier")
    return value


def normalized_timestamp(value: str) -> str:
    if value == "-":
        return "-"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_event(arguments: list[str]) -> dict[str, object]:
    if not arguments:
        raise ValueError("event kind is required")
    kind = arguments[0]
    if kind == "call" and len(arguments) == 10:
        _, tenant_id, national_number, unique_id, direction, remote, disposition, started, answered, ended = arguments
        return {
            "kind": "calls",
            "payload": {
                "tenant_id": tenant_id,
                "national_number": national_number,
                "pbx_unique_id": safe_identifier(unique_id),
                "direction": direction,
                "remote_number_masked": masked_number(remote),
                "disposition": disposition or "UNKNOWN",
                "started_at": normalized_timestamp(started),
                "answered_at": None if answered == "-" else normalized_timestamp(answered),
                "ended_at": normalized_timestamp(ended),
            },
        }
    if kind == "fax" and len(arguments) == 9:
        _, tenant_id, national_number, unique_id, direction, remote, status, occurred, file_path = arguments
        reference = None
        if file_path != "-":
            reference = f"fax-spool://{Path(file_path).name}"
        return {
            "kind": "faxes",
            "payload": {
                "tenant_id": tenant_id,
                "national_number": national_number,
                "pbx_unique_id": safe_identifier(unique_id),
                "direction": direction,
                "remote_number_masked": masked_number(remote),
                "status": status or "UNKNOWN",
                "storage_reference": reference,
                "occurred_at": normalized_timestamp(occurred),
            },
        }
    raise ValueError("unsupported PBX event arguments")


def write_event(event: dict[str, object], spool_dir: Path = SPOOL_DIR) -> Path:
    pending = spool_dir / "pending"
    pending.mkdir(parents=True, exist_ok=True, mode=0o750)
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("event payload is invalid")
    unique_id = safe_identifier(str(payload["pbx_unique_id"]))
    final_path = pending / f"{unique_id}.json"
    temporary = pending / f".{unique_id}.{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(event, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    temporary.chmod(0o640)
    temporary.replace(final_path)
    return final_path


def main() -> int:
    try:
        event = build_event(sys.argv[1:])
        write_event(event)
    except Exception as exc:
        print(f"PBX event spool error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
