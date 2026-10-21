#!/usr/bin/env python3
"""Reliably forward atomic PBX event files to the internal backend API."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import re
import stat
import sys


SPOOL_DIR = Path(os.getenv("PBX_EVENT_SPOOL_DIR", "/var/spool/anshin-phone/events"))
BACKEND_BASE_URL = os.getenv("PBX_EVENT_BACKEND_URL", "http://backend:8000").rstrip("/")
TOKEN_FILE = Path(os.getenv("PBX_EVENT_TOKEN_FILE", "/run/secrets/internal_api_token"))


def load_token(path: Path = TOKEN_FILE) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if not token or "\n" in token or "\r" in token:
        raise RuntimeError("internal API token is empty or invalid")
    return token


def deliver(event: dict, token: str, base_url: str = BACKEND_BASE_URL, *, original: bytes | None = None) -> str:
    kind = event.get("kind")
    if kind not in {"calls", "faxes", "fax-attempts"} or not isinstance(event.get("payload"), dict):
        return "dead-letter"
    payload = dict(event["payload"])
    target_url = f"{base_url}/api/v1/pbx-events/{kind}"
    if kind == "fax-attempts":
        job_id = payload.pop("job_id", "")
        if not re.fullmatch(r"[0-9a-f-]{36}", job_id):
            return "dead-letter"
        payload.pop("pbx_unique_id", None)
        target_url = f"{base_url}/api/v1/fax-worker/{job_id}/result"
    if kind == "faxes" and str(payload.get("storage_reference", "")).startswith("fax-spool://"):
        if original is None:
            return "dead-letter"
        upload = Request(f"{base_url}/api/v1/fax-documents?" + urlencode({
            "tenant_id": payload["tenant_id"], "pbx_unique_id": payload["pbx_unique_id"]}),
            data=original, headers={"Content-Type": "image/tiff", "X-Anshin-Internal-Token": token})
        try:
            with urlopen(upload, timeout=5) as response:
                document = json.load(response)
                if (not isinstance(document, dict) or not re.fullmatch(r"[0-9a-f-]{36}", str(document.get("id", "")))
                        or document.get('content_type') != 'image/tiff' or document.get('byte_count') != len(original)):
                    return "dead-letter"
                payload["storage_reference"] = "fax-document:" + document["id"]
        except HTTPError as exc:
            return "dead-letter" if 400 <= exc.code < 500 and exc.code not in {401, 403, 408, 429} else "retry"
        except (TimeoutError, URLError):
            return "retry"
        except (ValueError, TypeError):
            return "dead-letter"
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = Request(
        target_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Anshin-Internal-Token": token,
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            if 200 <= response.status < 300:
                if kind == 'fax-attempts':
                    result = json.load(response)
                    local = event.get('fax_local')
                    expected_status = {'sent': {'sent'}, 'permanent_failure': {'failed'}, 'retryable_failure': {'queued', 'failed'}}.get(payload.get('outcome'), set())
                    if (not isinstance(result, dict) or result.get('id') != job_id
                            or result.get('status') not in expected_status
                            or result.get('failure_code') != payload.get('failure_code')
                            or (local is not None and result.get('tenant_id') != local['tenant_id'])):
                        return 'dead-letter'
                elif kind == 'faxes':
                    result = json.load(response)
                    if not isinstance(result, dict) or any(result.get(key) != payload.get(key)
                            for key in ('tenant_id', 'pbx_unique_id', 'direction', 'status', 'storage_reference')):
                        return 'dead-letter'
                return "sent"
            return "retry"
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {401, 403, 408, 429}:
            return "dead-letter"
        return "retry"
    except (TimeoutError, URLError):
        return "retry"
    except (ValueError, TypeError):
        return 'dead-letter'


def local_binding(event: dict) -> dict | None:
    local = event.get('fax_local')
    if local is None:
        return None
    if (not isinstance(local, dict) or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}\.tif', str(local.get('basename', '')))
            or type(local.get('byte_count')) is not int or not 0 <= local['byte_count'] <= 10 * 1024 * 1024
            or not re.fullmatch('[0-9a-f]{64}', str(local.get('sha256', '')))
            or type(local.get('cleanup')) is not bool or not isinstance(local.get('tenant_id'), str) or not local['tenant_id']):
        raise ValueError('invalid local FAX binding')
    payload = event.get('payload', {})
    if not isinstance(payload, dict):
        raise ValueError('invalid FAX payload')
    if event.get('kind') == 'fax-attempts':
        job, claim = payload.get('job_id'), payload.get('claim_id')
        if (not all(isinstance(value, str) and re.fullmatch('[0-9a-f-]{36}', value) for value in (job, claim))
                or local.get('job_id') != job or local.get('claim_id') != claim
                or local['basename'] != job + '-' + claim + '.tif'
                or payload.get('pbx_unique_id') != 'fax-attempt-' + claim):
            raise ValueError('FAX attempt binding mismatch')
    elif (event.get('kind') != 'faxes' or payload.get('tenant_id') != local['tenant_id']
            or payload.get('storage_reference') != 'fax-spool://' + local['basename']):
        raise ValueError('FAX receive binding mismatch')
    return local


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_regular(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError('invalid event file')
        raw = source.read()
        if identity(os.fstat(source.fileno())) != identity(info):
            raise ValueError('event changed')
        return raw, identity(info)


def move(path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
    destination = target_dir / path.name
    if destination.exists():
        destination = target_dir / f"{path.stem}-{int(time.time())}{path.suffix}"
    shutil.move(str(path), str(destination))


def process_once(spool_dir: Path, token: str, base_url: str = BACKEND_BASE_URL) -> tuple[int, int, int]:
    pending = spool_dir / "pending"
    pending.mkdir(parents=True, exist_ok=True, mode=0o750)
    sent = dead = retried = 0
    for path in sorted(pending.glob("*.json")):
        descriptor = directory = None
        event_identity = None
        try:
            raw, event_identity = read_regular(path)
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError('invalid event')
            local = local_binding(event)
            content = None
            cleanup_ready = False
            source_name = local['basename'] if local is not None else None
            # Old received events can still reach the same protected-document
            # consumer. Without producer binding their source is never removed.
            if source_name is None and event.get('kind') == 'faxes' and isinstance(event.get('payload'), dict):
                reference = str(event['payload'].get('storage_reference') or '')
                if reference.startswith('fax-spool://'):
                    source_name = reference.removeprefix('fax-spool://')
                    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}\.tif', source_name):
                        raise ValueError('invalid legacy FAX basename')
            if source_name is not None:
                try:
                    directory = os.open(Path(os.getenv('PBX_FAX_SPOOL_DIR', '/var/spool/anshin-phone/fax')),
                                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    descriptor = os.open(source_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                    info = os.fstat(descriptor)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 10 * 1024 * 1024 or (local is not None and info.st_size != local['byte_count']):
                        raise ValueError('FAX source size mismatch')
                    with os.fdopen(os.dup(descriptor), 'rb') as source:
                        content = source.read(10 * 1024 * 1024 + 1)
                    if (local is not None and hashlib.sha256(content).hexdigest() != local['sha256']) or identity(os.fstat(descriptor)) != identity(info):
                        raise ValueError('FAX source bytes mismatch')
                    cleanup_ready = True
                except (OSError, ValueError):
                    if event.get('kind') != 'fax-attempts':
                        raise
                    # The result is independent of the temporary source. A
                    # missing/changed TIFF inhibits cleanup, not its delivery.
                    content = None
                    print('FAX source preserved: inspection unavailable', file=sys.stderr)
            outcome = deliver(event, token, base_url, original=content)
            # A producer may atomically replace this event during HTTP. Its
            # replacement has no ACK; leave it and its source untouched.
            if identity(path.lstat()) != event_identity:
                retried += 1
                continue
            if outcome == 'sent':
                move(path, spool_dir / 'sent')
                sent += 1
                if cleanup_ready and local is not None and local['cleanup']:
                    try:
                        current = os.stat(local['basename'], dir_fd=directory, follow_symlinks=False)
                        if identity(current) == identity(info) == identity(os.fstat(descriptor)):
                            os.unlink(local['basename'], dir_fd=directory)
                        else:
                            print('FAX source preserved: identity changed', file=sys.stderr)
                    except OSError:
                        print('FAX source preserved: cleanup unavailable', file=sys.stderr)
            elif outcome == 'dead-letter':
                move(path, spool_dir / 'dead-letter')
                dead += 1
            else:
                retried += 1
        except (ValueError, TypeError, KeyError):
            if event_identity is not None and identity(path.lstat()) == event_identity:
                move(path, spool_dir / 'dead-letter')
                dead += 1
            else:
                retried += 1
        except OSError:
            # Missing/changed source and failed event moves preserve pending.
            retried += 1
        finally:
            if descriptor is not None: os.close(descriptor)
            if directory is not None: os.close(directory)
    return sent, dead, retried


def replay_dead_letter(spool_dir: Path, name: str, expected_sha256: str) -> None:
    """Retry exactly one existing notification; never dispatch a FAX call."""
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}\.json', name) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('invalid replay selector')
    source = spool_dir / 'dead-letter' / name
    raw, source_identity = read_regular(source)
    event = json.loads(raw)
    if (hashlib.sha256(raw).hexdigest() != expected_sha256 or not isinstance(event, dict)
            or event.get('kind') not in {'calls', 'faxes', 'fax-attempts'} or not isinstance(event.get('payload'), dict)):
        raise ValueError('replay event mismatch')
    local_binding(event)
    pending = spool_dir / 'pending'
    pending.mkdir(parents=True, exist_ok=True, mode=0o750)
    if identity(source.lstat()) != source_identity:
        raise ValueError('replay source changed')
    # link is atomic no-clobber; a collision leaves both existing events intact.
    os.link(source, pending / name, follow_symlinks=False)
    source.unlink()


def main() -> int:
    if sys.argv[1:]:
        import argparse
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--replay-dead-letter', required=True)
        parser.add_argument('--expected-sha256', required=True)
        args = parser.parse_args()
        replay_dead_letter(SPOOL_DIR, args.replay_dead_letter, args.expected_sha256)
        return 0
    token = load_token()
    while True:
        sent, dead, retried = process_once(SPOOL_DIR, token)
        if sent or dead or retried:
            print(f"PBX event batch: sent={sent} dead_letter={dead} retry={retried}")
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
