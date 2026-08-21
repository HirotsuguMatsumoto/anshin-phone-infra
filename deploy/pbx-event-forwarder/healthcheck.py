#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import time


spool = Path(os.getenv("PBX_EVENT_SPOOL_DIR", "/var/spool/anshin-phone/events"))
pending = spool / "pending"
dead_letter = spool / "dead-letter"
maximum_age = int(os.getenv("PBX_EVENT_MAX_PENDING_AGE_SECONDS", "300"))

if not pending.is_dir():
    raise SystemExit("pending spool directory is missing")
if dead_letter.is_dir() and any(dead_letter.glob("*.json")):
    raise SystemExit("dead-letter PBX events require operator action")

now = time.time()
for event in pending.glob("*.json"):
    if now - event.stat().st_mtime > maximum_age:
        raise SystemExit("PBX event exceeded the maximum pending age")
