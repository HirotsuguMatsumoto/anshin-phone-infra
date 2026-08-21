#!/usr/bin/env python3
"""Reliably forward atomic PBX event files to the internal backend API."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SPOOL_DIR = Path(os.getenv("PBX_EVENT_SPOOL_DIR", "/var/spool/anshin-phone/events"))
BACKEND_BASE_URL = os.getenv("PBX_EVENT_BACKEND_URL", "http://backend:8000").rstrip("/")
TOKEN_FILE = Path(os.getenv("PBX_EVENT_TOKEN_FILE", "/run/secrets/internal_api_token"))


def load_token(path: Path = TOKEN_FILE) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if not token or "\n" in token or "\r" in token:
        raise RuntimeError("internal API token is empty or invalid")
    return token


def deliver(path: Path, token: str, base_url: str = BACKEND_BASE_URL) -> str:
    event = json.loads(path.read_text(encoding="utf-8"))
    kind = event.get("kind")
    if kind not in {"calls", "faxes"} or not isinstance(event.get("payload"), dict):
        return "dead-letter"
    body = json.dumps(event["payload"], ensure_ascii=True).encode("utf-8")
    request = Request(
        f"{base_url}/api/v1/pbx-events/{kind}",
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
                return "sent"
            return "retry"
    except HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {401, 403, 408, 429}:
            return "dead-letter"
        return "retry"
    except (TimeoutError, URLError):
        return "retry"


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
        outcome = deliver(path, token, base_url)
        if outcome == "sent":
            move(path, spool_dir / "sent")
            sent += 1
        elif outcome == "dead-letter":
            move(path, spool_dir / "dead-letter")
            dead += 1
        else:
            retried += 1
    return sent, dead, retried


def main() -> int:
    token = load_token()
    while True:
        sent, dead, retried = process_once(SPOOL_DIR, token)
        if sent or dead or retried:
            print(f"PBX event batch: sent={sent} dead_letter={dead} retry={retried}")
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
