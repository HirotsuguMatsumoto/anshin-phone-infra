#!/usr/bin/env python3
"""Apply the backend's endpoint configuration and authorize actual PBX calls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request


def request(path: str, payload: dict | None = None) -> dict | None:
    token = Path(os.environ["PBX_EVENT_TOKEN_FILE"]).read_text().strip()
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(os.environ["PBX_EVENT_BACKEND_URL"].rstrip("/") + path,
        data=body, headers={"X-Anshin-Internal-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as response:
        raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("PBX configuration exceeds supported size")
        return json.loads(raw) if raw else None


def validate_configuration(value: dict, tenant: str) -> dict:
    if value.get("tenant_id") != tenant or not isinstance(value.get("endpoints"), list):
        raise ValueError("PBX configuration tenant/schema mismatch")
    extensions = set()
    for endpoint in value["endpoints"]:
        if set(endpoint) != {"id", "extension", "password"}:
            raise ValueError("PBX endpoint schema mismatch")
        if not re.fullmatch(r"[0-9]{3,8}", endpoint["extension"]) or not re.fullmatch(r"[0-9a-f]{64}", endpoint["password"]):
            raise ValueError("PBX endpoint values are invalid")
        if endpoint["extension"] in extensions:
            raise ValueError("PBX endpoint extension is duplicated")
        extensions.add(endpoint["extension"])
    content = {"tenant_id": tenant, "endpoints": value["endpoints"]}
    revision = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if revision != value.get("revision"):
        raise ValueError("PBX configuration revision mismatch")
    return value


def endpoint_sections(value: dict) -> str:
    # These values also pass the existing renderer's validation before startup.
    sbc = os.environ["SBC_HOST"]
    port = os.environ["SBC_PORT"]
    qualify = os.environ["SMARTPHONE_QUALIFY_FREQUENCY"]
    sections = []
    for endpoint in value["endpoints"]:
        ext = endpoint["extension"]
        sections.append(f"""[{ext}-auth]
type=auth
auth_type=userpass
username={ext}
password={endpoint['password']}

[{ext}]
type=aor
max_contacts=1
remove_existing=yes
qualify_frequency={qualify}

[{ext}]
type=endpoint
transport=transport-udp
outbound_proxy=sip:{sbc}:{port}\\;lr
context=from-smartphone
disallow=all
allow=ulaw
allow=alaw
auth={ext}-auth
aors={ext}
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=no
""")
    return "\n".join(sections)


def cli(command: str) -> str:
    result = subprocess.run(["asterisk", "-rx", command], capture_output=True, text=True, timeout=5, check=True)
    if "Unable to connect" in result.stdout or "No such command" in result.stdout:
        raise RuntimeError("PBX has not started")
    return result.stdout


def applied_extensions() -> set[str]:
    return set(re.findall(r"^\s*Endpoint:\s+([0-9]{3,8})(?:/|\s)", cli("pjsip show endpoints"), re.MULTILINE))


def poll() -> int:
    tenant = os.environ["ANSHIN_PHONE_TENANT_ID"]
    path = Path("/etc/asterisk/managed-endpoints.conf")
    last_revision = None
    stop = False
    def terminate(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    # Runtime writes belong to the same uid as Asterisk; no privileged helper.
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    while not stop:
        phase = "fetch"
        try:
            value = validate_configuration(request("/api/v1/pbx-configuration?" + urllib.parse.urlencode({"tenant_id": tenant})), tenant)
            phase = "observe"
            expected = {e["extension"] for e in value["endpoints"]}
            if last_revision != value["revision"] or applied_extensions() != expected:
                phase = "write"
                temporary = path.with_suffix(".tmp")
                temporary.write_text(endpoint_sections(value))
                temporary.chmod(0o600)
                temporary.replace(path)
                phase = "reload"
                cli("module reload res_pjsip.so")
                phase = "confirm"
                deadline = time.monotonic() + 5
                while applied_extensions() != expected:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("PBX endpoint configuration was not applied")
                    time.sleep(0.1)
                last_revision = value["revision"]
            phase = "acknowledge"
            request("/api/v1/pbx-configuration/applied", {"tenant_id": tenant, "revision": last_revision})
        except Exception as exc:
            # Never log a URL, token, password, raw response, or phone number.
            print(f"phase=pbx-configuration call_context={phase} state=unavailable error={type(exc).__name__}", file=sys.stderr, flush=True)
        time.sleep(2)
    return 0


def agi_variable(name: str, value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9/&]*", value):
        raise ValueError("invalid dialplan variable")
    print(f'SET VARIABLE {name} "{value}"', flush=True)
    if not sys.stdin.readline().startswith("200 result="):
        raise RuntimeError("AGI variable response was not accepted")


def inbound_did(to_header: str, alert_info: str = "") -> str:
    """Carrier contract: To owns DID; optional Alert-Info must agree.

    Header values come from PJSIP's parsed request, never from argv or the
    Request-URI/REGISTER Contact. The manual's Alert-Info is a bare DID.
    """
    if any(c in to_header + alert_info for c in "\r\n"):
        raise ValueError("invalid carrier header")
    users = re.findall(r"(?:^|<)sips?:([^@;<>\s]+)@", to_header.strip(), re.IGNORECASE)
    if len(users) != 1:
        raise ValueError("carrier To must contain one SIP identity")
    def normalize(value):
        if re.fullmatch(r"\+81[1-9][0-9]{8,9}", value):
            value = "0" + value[3:]
        if not re.fullmatch(r"0[0-9]{9,10}", value):
            raise ValueError("invalid carrier DID")
        return value
    did = normalize(users[0])
    if alert_info and normalize(alert_info.strip()) != did:
        raise ValueError("carrier DID headers disagree")
    return did


def agi_header(name: str, index: int = 1) -> str:
    # Both arguments are internal literals. Do not interpolate received SIP.
    print(f'GET FULL VARIABLE "${{PJSIP_HEADER(read,{name},{index})}}"', flush=True)
    response = sys.stdin.readline().rstrip("\r\n")
    if response == "200 result=0":
        return ""
    match = re.fullmatch(r"200 result=1 \((.*)\)", response)
    if not match:
        raise RuntimeError("carrier header read failed")
    return match[1]


def authorize(arguments: list[str]) -> int:
    # Consume the AGI environment before writing AGI commands.
    while sys.stdin.readline().strip():
        pass
    allowed, did, targets = "0", "", ""
    try:
        mode, identity = arguments[:2]
        if mode == "carrier-inbound":
            if len(arguments) != 2:
                raise ValueError("invalid carrier route arguments")
            call_id = identity
            to_header, alert_info = agi_header("To"), agi_header("Alert-Info")
            if agi_header("To", 2) or agi_header("Alert-Info", 2):
                raise ValueError("ambiguous carrier DID headers")
            identity = inbound_did(to_header, alert_info)
            mode = "fax" if identity == os.environ["FAX_DID"] else "inbound"
            arguments = [mode, identity] if mode == "fax" else [mode, identity, call_id]
        if mode not in {"inbound", "outbound", "fax"} or not re.fullmatch(r"[0-9]{3,11}", identity):
            raise ValueError("invalid route identity")
        tenant = os.environ["ANSHIN_PHONE_TENANT_ID"]
        params = {"tenant_id": tenant, "extension" if mode == "outbound" else "national_number": identity}
        if mode == "fax":
            if len(arguments) != 2:
                raise ValueError("invalid fax route arguments")
            params["fax"] = "true"
            value = request("/api/v1/pbx-route?" + urllib.parse.urlencode(params))
        else:
            if len(arguments) != 3 or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", arguments[2]):
                raise ValueError("PBX call identity is required")
            params["pbx_unique_id"] = arguments[2]
            value = request("/api/v1/pbx-route", params)
        if value.get("tenant_id") != tenant or not isinstance(value.get("allowed"), bool):
            raise ValueError("PBX route response mismatch")
        if value["allowed"]:
            did = value["national_number"]
            extensions = value["extensions"]
            if (mode != "outbound" and did != identity) or not re.fullmatch(r"0[0-9]{9,10}", did) or any(not re.fullmatch(r"[0-9]{3,8}", e) for e in extensions):
                raise ValueError("invalid PBX route")
            targets = "&".join("PJSIP/" + e for e in extensions)
            allowed = "1"
    except Exception:
        print("phase=pbx-route state=denied", file=sys.stderr)
    agi_variable("PHONE_ROUTE_ALLOWED", allowed)
    agi_variable("PHONE_ROUTE_DID", did)
    agi_variable("PHONE_ROUTE_TARGETS", targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(poll() if sys.argv[1:] == ["--poll"] else authorize(sys.argv[1:]))
