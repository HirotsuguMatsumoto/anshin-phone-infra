#!/usr/bin/env python3
"""Run isolated inbound/outbound SIP tests without carrier credentials."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import json


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def compose_args(project: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(ROOT / "compose.phase1.yaml"),
        "--file",
        str(ROOT / "compose.phase1.mock.yaml"),
    ]


def wait_for_asterisk(base: list[str], env: dict[str, str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = run(
            base + ["exec", "-T", "asterisk", "asterisk", "-rx", "core show uptime"],
            env=env,
            check=False,
        )
        if result.returncode == 0 and "System uptime" in result.stdout:
            return
        time.sleep(1)
    raise RuntimeError("Asterisk did not become ready within 30 seconds")


def backend_request(
    base: list[str], env: dict[str, str], method: str, path: str, payload: dict[str, object] | None = None
) -> object:
    code = (
        "import json,sys,urllib.request;"
        "body=None if sys.argv[3]=='-' else sys.argv[3].encode();"
        "request=urllib.request.Request('http://127.0.0.1:8000'+sys.argv[2],data=body,method=sys.argv[1],"
        "headers={'Content-Type':'application/json','X-Anshin-Internal-Token':'test-internal-token'});"
        "print(urllib.request.urlopen(request,timeout=5).read().decode())"
    )
    serialized = "-" if payload is None else json.dumps(payload, separators=(",", ":"))
    result = run(
        base + ["exec", "-T", "backend", "python", "-c", code, method, path, serialized],
        env=env,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def wait_for_backend(base: list[str], env: dict[str, str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            backend_request(base, env, "GET", "/health/ready")
            return
        except subprocess.CalledProcessError:
            time.sleep(1)
    raise RuntimeError("backend did not become ready within 30 seconds")


def wait_for_event_count(
    base: list[str], env: dict[str, str], resource: str, expected: int
) -> list[dict[str, object]]:
    deadline = time.monotonic() + 10
    path = f"/api/v1/{resource}?tenant_id=anshin-phase1"
    while time.monotonic() < deadline:
        records = backend_request(base, env, "GET", path)
        if isinstance(records, list) and len(records) >= expected:
            return records
        time.sleep(1)
    raise RuntimeError(f"{resource} did not reach {expected} records within 10 seconds")


def wait_for_smartphone_contact(base: list[str], env: dict[str, str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = run(
            base + ["exec", "-T", "asterisk", "asterisk", "-rx", "pjsip show contacts"],
            env=env,
            check=False,
        )
        if "2001/sip:2001@172.31.250.30:5060" in result.stdout:
            return
        time.sleep(1)
    endpoints = run(
        base + ["exec", "-T", "asterisk", "asterisk", "-rx", "pjsip show endpoints"],
        env=env,
        check=False,
    )
    raise RuntimeError(
        "mock smartphone did not register within 10 seconds:\n"
        f"Asterisk endpoints:\n{endpoints.stdout}"
    )


def exec_background(
    base: list[str], service: str, args: list[str], env: dict[str, str]
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        base + ["exec", "-T", service] + args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def finish(process: subprocess.Popen[str], label: str) -> None:
    try:
        output, _ = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.terminate()
        output, _ = process.communicate(timeout=5)
        raise RuntimeError(f"{label} timed out:\n{output}")
    if process.returncode != 0:
        raise RuntimeError(f"{label} failed with exit {process.returncode}:\n{output}")


def main() -> int:
    if shutil.which("docker") is None:
        raise RuntimeError("docker is required")

    project = f"anshin-phone-sip-test-{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory(prefix="anshin-phone-test-secrets-") as secret_dir:
        secret_path = Path(secret_dir)
        for name, value in {
            "postgres_password": "test-postgres-password",
            "carrier_sip_password": "test-carrier-password",
            "smartphone_sip_password": "test-smartphone-password",
            "internal_api_token": "test-internal-token",
        }.items():
            path = secret_path / name
            path.write_text(value, encoding="utf-8")
            path.chmod(0o600)

        env = os.environ.copy()
        env.update(
            {
                "ANSHIN_PHONE_SECRET_DIR": secret_dir,
                "CARRIER_AUTH_MODE": "ip",
                "CARRIER_HOST": "mock-carrier",
                "CARRIER_PORT": "5060",
                "CARRIER_QUALIFY_FREQUENCY": "0",
                "CARRIER_SOURCE_CIDRS": "172.31.250.10/32",
                "CARRIER_SIP_USERNAME": "mock-carrier",
                "PUBLIC_SIP_IP": "172.31.250.20",
                "TEL_DID": "0300000001",
                "FAX_DID": "0300000002",
                "SMARTPHONE_EXTENSION": "2001",
                "SMARTPHONE_QUALIFY_FREQUENCY": "0",
            }
        )
        base = compose_args(project)
        failed = False
        try:
            result = run(
                base
                + [
                    "up",
                    "--detach",
                    "--build",
                    "mock-carrier",
                    "mock-smartphone",
                    "postgres",
                    "backend",
                    "pbx-event-forwarder",
                    "asterisk",
                ],
                env=env,
            )
            print(result.stdout, end="")
            wait_for_asterisk(base, env)
            wait_for_backend(base, env)
            backend_request(
                base,
                env,
                "POST",
                "/api/v1/phone-numbers",
                {
                    "tenant_id": "anshin-phase1",
                    "e164": "+81300000001",
                    "national_number": "0300000001",
                    "area_code": "03",
                    "usage": "TEL",
                    "carrier_name": "isolated-mock-carrier",
                    "route_target": "2001",
                },
            )
            backend_request(
                base,
                env,
                "POST",
                "/api/v1/phone-numbers",
                {
                    "tenant_id": "anshin-phase1",
                    "e164": "+81300000002",
                    "national_number": "0300000002",
                    "area_code": "03",
                    "usage": "FAX",
                    "carrier_name": "isolated-mock-carrier",
                },
            )

            registration = run(
                base
                + [
                    "exec",
                    "-T",
                    "mock-smartphone",
                    "sipp",
                    "-nostdin",
                    "172.31.250.20:5060",
                    "-sf",
                    "/scenarios/smartphone_register.xml",
                    "-i",
                    "172.31.250.30",
                    "-p",
                    "5060",
                    "-m",
                    "1",
                    "-timeout",
                    "15s",
                    "-trace_msg",
                    "-message_file",
                    "/tmp/registration-messages.log",
                ],
                env=env,
            )
            print(registration.stdout, end="")
            wait_for_smartphone_contact(base, env)

            smartphone = exec_background(
                base,
                "mock-smartphone",
                [
                    "sipp",
                    "-nostdin",
                    "-sf",
                    "/scenarios/smartphone_inbound_uas.xml",
                    "-i",
                    "172.31.250.30",
                    "-p",
                    "5060",
                    "-m",
                    "1",
                    "-timeout",
                    "15s",
                ],
                env,
            )
            time.sleep(1)
            inbound = run(
                base
                + [
                    "exec",
                    "-T",
                    "mock-carrier",
                    "sipp",
                    "-nostdin",
                    "172.31.250.20:5060",
                    "-sf",
                    "/scenarios/carrier_inbound_uac.xml",
                    "-i",
                    "172.31.250.10",
                    "-p",
                    "5060",
                    "-m",
                    "1",
                    "-timeout",
                    "15s",
                ],
                env=env,
                check=False,
            )
            print(inbound.stdout, end="")
            if inbound.returncode != 0:
                if smartphone.poll() is None:
                    smartphone.terminate()
                smartphone_output, _ = smartphone.communicate(timeout=5)
                raise RuntimeError(
                    f"mock carrier inbound scenario failed:\n{inbound.stdout}\n"
                    f"mock smartphone scenario output:\n{smartphone_output}"
                )
            finish(smartphone, "mock smartphone inbound scenario")
            print("PASS: mock carrier -> Asterisk -> smartphone inbound signaling")

            carrier = exec_background(
                base,
                "mock-carrier",
                [
                    "sipp",
                    "-nostdin",
                    "-sf",
                    "/scenarios/carrier_outbound_uas.xml",
                    "-i",
                    "172.31.250.10",
                    "-p",
                    "5060",
                    "-m",
                    "1",
                    "-timeout",
                    "15s",
                ],
                env,
            )
            time.sleep(1)
            outbound = exec_background(
                base,
                "mock-smartphone",
                [
                    "sipp",
                    "-nostdin",
                    "172.31.250.20:5060",
                    "-sf",
                    "/scenarios/smartphone_outbound_uac.xml",
                    "-i",
                    "172.31.250.30",
                    "-p",
                    "5060",
                    "-m",
                    "1",
                    "-timeout",
                    "15s",
                ],
                env,
            )
            finish(carrier, "mock carrier outbound scenario")
            finish(outbound, "mock smartphone outbound scenario")
            print("PASS: smartphone -> Asterisk -> mock carrier outbound signaling")

            call_records = wait_for_event_count(base, env, "call-records", 2)
            if not all("*" in str(record["remote_number_masked"]) for record in call_records):
                raise RuntimeError("unmasked call record reached the backend")
            print("PASS: Asterisk call events -> durable spool -> Backend")

            fax_event = run(
                base
                + [
                    "exec",
                    "-T",
                    "--user",
                    "10001:10001",
                    "asterisk",
                    "python3",
                    "/var/lib/asterisk/agi-bin/pbx_event_spool.py",
                    "fax",
                    "anshin-phase1",
                    "0300000002",
                    "isolated-fax-event-001",
                    "inbound",
                    "090****0000",
                    "SUCCESS",
                    "2026-08-21T00:00:00Z",
                    "/var/spool/asterisk/fax/isolated-test.tif",
                ],
                env=env,
            )
            print(fax_event.stdout, end="")
            fax_records = wait_for_event_count(base, env, "fax-records", 1)
            if fax_records[0]["storage_reference"] != "fax-spool://isolated-test.tif":
                raise RuntimeError("FAX storage reference was not normalized")
            print("PASS: Asterisk FAX event -> durable spool -> Backend")
        except Exception:
            failed = True
            logs = run(
                base
                + [
                    "logs",
                    "--no-color",
                    "asterisk",
                    "pbx-event-forwarder",
                    "backend",
                ],
                env=env,
                check=False,
            )
            print(logs.stdout, end="")
            registration_trace = run(
                base
                + [
                    "exec",
                    "-T",
                    "mock-smartphone",
                    "sh",
                    "-c",
                    "test ! -f /tmp/registration-messages.log || cat /tmp/registration-messages.log",
                ],
                env=env,
                check=False,
            )
            print(registration_trace.stdout, end="")
            raise
        finally:
            cleanup = run(
                base + ["down", "--volumes", "--remove-orphans"],
                env=env,
                check=False,
            )
            if cleanup.returncode != 0 or failed:
                print(cleanup.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
