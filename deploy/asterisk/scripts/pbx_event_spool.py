#!/usr/bin/env python3
"""Write a masked PBX event to an atomic local spool file."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid


SPOOL_DIR = Path(os.getenv("PBX_EVENT_SPOOL_DIR", "/var/spool/asterisk/anshin-events"))
FAX_ROOT = Path('/var/spool/asterisk/fax')


def fax_local_source(name: str, tenant_id: str, *, cleanup: bool, job_id=None, claim_id=None) -> dict:
    """Bind only the local source bytes; this metadata never enters the API."""
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}\.tif', name):
        raise ValueError('invalid local FAX basename')
    directory = os.open(FAX_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 10 * 1024 * 1024:
                raise ValueError('invalid local FAX source')
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
            after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('local FAX source changed')
    finally:
        os.close(directory)
    result = {'basename': name, 'byte_count': before.st_size, 'sha256': digest,
              'tenant_id': tenant_id, 'cleanup': cleanup}
    if job_id is not None:
        result.update(job_id=job_id, claim_id=claim_id)
    return result


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
        if file_path != "-" and status == "SUCCESS":
            reference = f"fax-spool://{Path(file_path).name}"
        event = {
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
        if reference is not None:
            try:
                event['fax_local'] = fax_local_source(Path(file_path).name, tenant_id, cleanup=True)
            except (OSError, ValueError):
                print('FAX source preserved: local binding unavailable', file=sys.stderr)
        return event
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
