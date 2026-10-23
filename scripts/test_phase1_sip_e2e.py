#!/usr/bin/env python3
"""Run isolated inbound/outbound SIP tests without carrier credentials."""

from __future__ import annotations

from contextlib import contextmanager
import argparse
import ipaddress
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import json
import stat
import signal
from datetime import datetime, timedelta, timezone
import re


class FixtureInterrupted(KeyboardInterrupt):
    def __init__(self, signum):
        self.signum = signum


@contextmanager
def fixture_signals():
    previous = {kind: signal.getsignal(kind) for kind in (signal.SIGTERM, signal.SIGINT)}
    def interrupted(signum, _frame):
        for kind in previous:signal.signal(kind, signal.SIG_IGN)
        raise FixtureInterrupted(signum)
    try:
        for kind in previous:signal.signal(kind, interrupted)
        yield
    finally:
        for kind, handler in previous.items():signal.signal(kind, handler)


def fixture_labels(project, expires_at=None):
    return {"care.anshin.local.ephemeral":"true", "care.anshin.local.owner":"anshin-phone-infra",
            "care.anshin.local.task_id":project,
            "care.anshin.local.expires_at":expires_at or (datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()}


def fixture_ownership_override(compiled, project, expires_at=None):
    labels=fixture_labels(project, expires_at)
    services={}
    for name, service in compiled["services"].items():
        services[name]={"labels":labels}
        if service.get("build"):services[name]["build"]={"labels":labels}
    result={"services":services}
    for kind in ("volumes","networks"):
        result[kind]={name:{"labels":labels} for name, resource in compiled.get(kind,{}).items()
                      if not resource.get("external")}
    return result


@contextmanager
def fixture_directory(*, prefix="anshin-phone-test-secrets-", allow_preview=True):
    preview = os.environ.get("PHONE_PREVIEW_DIR") if allow_preview else None
    state = {"retain": False}
    if preview:
        path = Path(preview)
        if not path.is_absolute() or path.resolve().is_relative_to(ROOT):
            raise RuntimeError("process-start=0: preview path must be absolute and outside source")
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    else:
        path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path, state
    except BaseException:
        state["retain"] = True
        print("SIP E2E inputs retained after failure: " + str(path))
        raise
    finally:
        if not state["retain"]:
            shutil.rmtree(path)

from resolve_phone_backend import resolve_backend


ROOT = Path(__file__).resolve().parents[1]
DOCKER_HEAVY_LOCK_PATH = Path("/tmp/anshin-local-docker-heavy.lock")
MOCK_SUBNETS = ("10.254.250.0/24", "10.254.251.0/24")


@contextmanager
def docker_test_lease():
    descriptor = os.open(DOCKER_HEAVY_LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lock_stat = os.fstat(descriptor)
    if (
        lock_stat.st_uid != os.getuid()
        or not stat.S_ISREG(lock_stat.st_mode)
        or stat.S_IMODE(lock_stat.st_mode) != 0o600
        or lock_stat.st_nlink != 1
    ):
        os.close(descriptor)
        raise RuntimeError("Docker-heavy resource lease is not an owner-only regular file")
    with os.fdopen(descriptor, "r+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("exclusive Docker cleanup or rebuild owns the resource lease") from exc
        yield


def run(command: list[str], *, env: dict[str, str], check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    if input_text is None:
        from production_runtime import run_owned_process
        result = run_owned_process(command, cwd=ROOT, env=env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=None)
        if check:result.check_returncode()
        return result
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=check,
        text=True,
        input=input_text,
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
    ] + (["--file", str(ROOT / "compose.phase1.local.yaml")] if os.environ.get("PHONE_LOCAL_OIDC_ISSUER") else [])


def ensure_mock_networks_available(env: dict[str, str]) -> None:
    identifiers = run(["docker", "network", "ls", "--quiet"], env=env).stdout.split()
    if not identifiers:
        return
    existing = json.loads(run(["docker", "network", "inspect", *identifiers], env=env).stdout)
    wanted = [ipaddress.ip_network(subnet) for subnet in MOCK_SUBNETS + (('10.254.252.0/24',) if env.get('PHONE_SOFTPHONE_SIMULATOR') else ())]
    for network in existing:
        for entry in network.get("IPAM", {}).get("Config") or []:
            if not entry.get("Subnet"):
                continue
            actual = ipaddress.ip_network(entry["Subnet"])
            if any(actual.version == subnet.version and actual.overlaps(subnet) for subnet in wanted):
                raise RuntimeError("process-start=0: isolated SIP fixture subnet overlaps an existing Docker network")


def cleanup_args(base: list[str]) -> list[str]:
    """Remove every resource built for the unique ephemeral Compose project."""
    return base + ["down", "--rmi", "local", "--volumes", "--remove-orphans"]


def project_image_ids(project: str, env: dict[str, str]) -> list[str]:
    result = run(
        ["docker", "image", "ls", "--all", "--quiet", "--no-trunc", "--filter", f"reference={project}-*"],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def cleanup_residue(
    base: list[str], project: str, env: dict[str, str], expected_image_ids: list[str] | None = None
) -> list[str]:
    checks = {
        "container": base + ["ps", "--all", "--quiet"],
        "network": ["docker", "network", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}"],
        "volume": ["docker", "volume", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}"],
        "image": ["docker", "image", "ls", "--all", "--quiet", "--filter", f"reference={project}-*"],
    }
    residue: list[str] = []
    for kind, command in checks.items():
        result = run(command, env=env, check=False)
        if result.returncode != 0 or result.stdout.strip():
            residue.append(kind)
    for image_id in expected_image_ids or []:
        result = run(["docker", "image", "inspect", image_id], env=env, check=False)
        if result.returncode == 0:
            if "image" not in residue:
                residue.append("image")
            break
    return residue


def ensure_cleanup_succeeded(cleanup: subprocess.CompletedProcess[str], residue: list[str], test_failed: bool) -> None:
    """Turn cleanup defects into a test failure without hiding an earlier failure."""
    if cleanup.returncode != 0 or residue:
        message = ("SIP E2E cleanup failed: "
                   f"exit={cleanup.returncode} residue={','.join(residue) or 'unknown'}")
        if test_failed:
            print(message)
        else:
            raise RuntimeError(message)


def cleanup_owned_runtime(base: list[str], project: str, env: dict[str,str], failed: bool) -> None:
    # A UI consumer is created with docker run, so Compose does not own it.
    # Remove it before its network producers, including a failed restore phase.
    run(["docker","rm","--force",project+"-management-ui"],env=env,check=False)
    built_image_ids = project_image_ids(project,env)
    cleanup = run(cleanup_args(base),env=env,check=False)
    residue = cleanup_residue(base,project,env,built_image_ids)
    if cleanup.returncode != 0 or residue or failed:
        print(cleanup.stdout,end="")
    ensure_cleanup_succeeded(cleanup,residue,failed)


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


def wait_for_sbc(base: list[str], env: dict[str, str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = run(
            base + ["exec", "-T", "kamailio", "kamcmd", "-s", "unix:/tmp/kamailio_ctl", "core.uptime"],
            env=env,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("Kamailio SBC did not become ready within 30 seconds")


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
    return json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else None


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
        if "2001/sip:2001@10.254.250.30:5060" in result.stdout:
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


def validate_browser_inputs(env: dict[str,str]) -> tuple[Path,dict]:
    frontend = Path(env["PHONE_TEST_FRONTEND_DIR"]).resolve(strict=True)
    actual = subprocess.check_output(["git", "-C", str(frontend), "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(actual).resolve() != frontend or not (frontend / "apps/anshin-phone/tests/e2e/management.spec.ts").is_file():
        raise RuntimeError("process-start=0: Phone frontend identity/entry mismatch")
    account_path = Path(env["PHONE_TEST_ACCOUNT_FILE"]).resolve(strict=True)
    if stat.S_IMODE(account_path.stat().st_mode) != 0o600 or account_path.stat().st_uid != os.getuid():
        raise RuntimeError("process-start=0: Phone account fixture is not owner-only")
    account = json.loads(account_path.read_text())
    if not str(account["username"]).endswith("@example.invalid"):
        raise RuntimeError("process-start=0: only a synthetic Phone account is permitted")
    return frontend, account


def run_management_browser_flow(base: list[str], env: dict[str, str], secret_path: Path) -> None:
    frontend, account = validate_browser_inputs(env)
    for tenant, role, label in (("anshin-phase1", "phone-owner", "基礎開発・隔離事業所"), ("phone-role-check", "phone-auditor", "権限確認・隔離事業所")):
        backend_request(base, env, "POST", "/api/v1/tenant-memberships", {"tenant_id": tenant,
            "subject": account["subject"], "role": role, "display_name": label})
    project = base[base.index("--project-name") + 1]
    container = project + "-management-ui"
    print("phase=management-browser state=started", flush=True)
    succeeded = False
    try:
        run(["docker", "run", "--detach", "--name", container, "--label", "anshin.task=phone-foundation-20261012",
            *[argument for key,value in fixture_labels(project,env.get("PHONE_TEST_EXPIRES_AT")).items() for argument in ("--label",key+"="+value)],
            "--user", f"{os.getuid()}:{os.getgid()}", "--network", project + "_phone-data",
            "--publish", "127.0.0.1:3015:3015", "--volume", str(frontend) + ":/workspace",
            "--workdir", "/workspace/apps/anshin-phone", "--env", "PHONE_API_PROXY_TARGET=http://backend:8000",
            "--env", "VITE_OIDC_ISSUER=" + env["PHONE_LOCAL_OIDC_ISSUER"], "node:24-bookworm-slim",
            "node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "3015", "--strictPort"], env=env)
        run(["docker", "network", "connect", env["PHONE_LOCAL_AUTH_NETWORK"], container], env=env)
        import urllib.request
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen("http://localhost:3015/dashboard", timeout=2).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("phase=management-browser state=startup-timeout")
        browser_env = dict(env, PHONE_TEST_BASE_URL="http://localhost:3015", PHONE_TEST_PDF_FILE=str(secret_path / "synthetic-fax.pdf"),
            PHONE_TEST_OUTPUT_DIR=str(secret_path / "playwright-output"))
        completed = subprocess.run(["pnpm", "--dir", "apps/anshin-phone", "run", "test:e2e"], cwd=frontend,
            env=browser_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        print(completed.stdout, end="", flush=True)
        if completed.returncode:
            raise RuntimeError("phase=management-browser state=assertion-failed")
        print("PASS: actual PKCE/AAL2 -> management actions -> PBX/FAX/call/audit UI", flush=True)
        succeeded = True
    finally:
        if not (succeeded and env.get("PHONE_PREVIEW_DIR")):
            run(["docker", "rm", "--force", container], env=env, check=False)


def start_concurrent_voice(base: list[str], env: dict[str,str]):
    smartphone = exec_background(base,"mock-smartphone",["sipp","-nostdin","-sf","/scenarios/smartphone_inbound_uas.xml",
        "-i","10.254.250.30","-p","5060","-m","2","-timeout","30s"],env)
    time.sleep(0.5)
    for _ in range(2):
        run(base + ["exec","-T","mock-carrier","asterisk","-rx","channel originate PJSIP/0300000001@carrier-sbc extension s@synthetic-load"],env=env)
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        channels = run(base + ["exec","-T","asterisk","asterisk","-rx","core show channels concise"],env=env).stdout.splitlines()
        channels = [line.split("!")[0] for line in channels if line.startswith("PJSIP/carrier-endpoint-")]
        if len(channels)>=2:
            break
        time.sleep(0.2)
    else:
        smartphone.terminate()
        smartphone.communicate(timeout=5)
        raise RuntimeError("phase=local-load state=failed expected=two-live-calls")
    for index,channel in enumerate(channels[:2]):
        if not re.fullmatch(r"PJSIP/carrier-endpoint-[0-9a-f]+",channel):
            raise RuntimeError("phase=local-load state=invalid-channel")
        run(base + ["exec","-T","asterisk","asterisk","-rx",f"mixmonitor start {channel} /var/spool/asterisk/fax/load-{index}.wav"],env=env)
    return smartphone


def observe_concurrent_resources(base: list[str], env: dict[str,str], directory: Path):
    identifiers = run(base + ["ps","--quiet"],env=env).stdout.split()
    observed = run(["docker","stats","--no-stream","--format","{{json .}}",*identifiers],env=env).stdout
    channels = run(base + ["exec","-T","asterisk","asterisk","-rx","core show channels count"],env=env).stdout
    if not re.search(r"[5-9][0-9]* active channels",channels):
        raise RuntimeError("phase=local-load state=failed expected=voice-and-fax-overlap")
    (directory / "concurrent-resource-sample.json").write_text(json.dumps({"sample_kind":"local-two-calls-one-fax-two-recordings",
        "measurement":"single-overlap-sample-not-production-capacity","containers":[json.loads(line) for line in observed.splitlines()],"channels":channels},indent=2))
    print("phase=local-load state=observed calls=2 fax=1 recordings=2 scope=local-only",flush=True)


def run_fax_flow(base: list[str], env: dict[str, str], fax_number: dict, secret_path: Path, *, with_load: bool = True) -> int | None:
    import base64
    print("phase=fax-integration state=started", flush=True)
    run(base + ["exec", "-T", "mock-carrier", "gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=tiffg4", "-r204x196", "-sOutputFile=/tmp/mock-send.tif", "/mock-fax/synthetic-fax.ps"], env=env)
    run(base + ["exec", "-T", "mock-carrier", "gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite", "-sOutputFile=/tmp/mock-send.pdf", "/mock-fax/synthetic-fax.ps"], env=env)
    carrier_log = secret_path / "mock-fax-runtime.log"
    carrier_output = carrier_log.open("w")
    carrier = subprocess.Popen(base + ["exec", "-T", "mock-carrier", "sh", "/mock-fax/start.sh"], cwd=ROOT, env=env,
        text=True, stdout=carrier_output, stderr=subprocess.STDOUT)
    load_smartphone = None
    completed = False
    forwarder_paused = False
    def pending_source(kind, job_id=None):
        code = ("import json;from pathlib import Path;root=Path('/var/spool/asterisk/anshin-events/pending');"
            "events=[json.loads(p.read_text()) for p in root.glob('*.json')];"
            "events=[e for e in events if e.get('kind')==" + repr(kind)
            + (" and e['payload'].get('job_id')==" + repr(job_id) if job_id else '') + "];"
            "assert len(events)==1;local=events[0]['fax_local'];"
            "assert local['cleanup'] is True;assert (Path('/var/spool/asterisk/fax')/local['basename']).is_file();"
            "print(local['basename'])")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = run(base + ['exec', '-T', 'asterisk', 'python3', '-c', code], env=env, check=False)
            if result.returncode == 0:
                return result.stdout.strip()
            time.sleep(1)
        raise RuntimeError('phase=fax-ack state=pending-source-not-confirmed')
    def removed_source(name):
        code = "from pathlib import Path;assert not (Path('/var/spool/asterisk/fax')/" + repr(name) + ").exists()"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if run(base + ['exec', '-T', 'asterisk', 'python3', '-c', code], env=env, check=False).returncode == 0:
                return
            time.sleep(0.5)
        raise RuntimeError('phase=fax-ack state=accepted-source-not-reclaimed')
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if carrier.poll() is not None:
                carrier_output.flush()
                print("\n".join(carrier_log.read_text().splitlines()[-20:]), flush=True)
                raise RuntimeError("phase=mock-fax-runtime state=exited protocol=not-started")
            ready = run(base + ["exec", "-T", "mock-carrier", "asterisk", "-rx", "core show uptime"], env=env, check=False)
            if "System uptime" in ready.stdout:
                break
            time.sleep(0.5)
        else:
            carrier_output.flush()
            print("\n".join(carrier_log.read_text().splitlines()[-20:]), flush=True)
            raise RuntimeError("phase=mock-fax-runtime state=timeout protocol=not-started")
        if with_load:
            load_smartphone = start_concurrent_voice(base,env)
        # Real SendFAX -> Kamailio/RTPengine -> real ReceiveFAX -> encrypted
        # backend original and history. The carrier is synthetic and isolated.
        run(base + ['pause', 'pbx-event-forwarder'], env=env)
        forwarder_paused = True
        run(base + ["exec", "-T", "mock-carrier", "asterisk", "-rx", "channel originate PJSIP/0300000002@carrier-sbc application SendFAX /tmp/mock-send.tif,F"], env=env)
        if with_load:
            observe_concurrent_resources(base,env,secret_path)
        received_source = pending_source('faxes')
        run(base + ['unpause', 'pbx-event-forwarder'], env=env)
        forwarder_paused = False
        deadline = time.monotonic() + 90
        records = []
        while time.monotonic() < deadline:
            records = backend_request(base, env, "GET", "/api/v1/fax-records?tenant_id=anshin-phase1")
            if records:
                break
            time.sleep(1)
        if not records or records[0]["status"] != "SUCCESS" or not str(records[0]["storage_reference"]).startswith("fax-document:"):
            carrier_output.flush()
            print("\n".join(carrier_log.read_text().splitlines()[-40:]), flush=True)
            raise RuntimeError("phase=fax-receive state=failed expected=successful-encrypted-original")
        removed_source(received_source)
        if with_load:
            finish(load_smartphone,"concurrent synthetic voice")
        load_smartphone = None
        recording_code = "import wave;from pathlib import Path;files=[Path('/var/spool/asterisk/fax/load-'+str(i)+'.wav') for i in range(2)];sizes=[p.stat().st_size for p in files];assert all(n>44 for n in sizes);[wave.open(str(p)).getnframes() for p in files];print('phase=local-recording state=completed bytes='+str(sum(sizes)));[p.unlink() for p in files]"
        if with_load:
            print(run(base + ["exec","-T","asterisk","python3","-c",recording_code],env=env).stdout,end="",flush=True)
        print("PASS: actual G.711 FAX receive -> protected original -> backend history", flush=True)
        pdf_path = secret_path / "synthetic-fax.pdf"
        container = run(base + ["ps", "--quiet", "mock-carrier"], env=env).stdout.strip()
        run(["docker", "cp", container + ":/tmp/mock-send.pdf", str(pdf_path)], env=env)
        code = "import base64,json,sys,urllib.request;body=base64.b64decode(sys.stdin.read());req=urllib.request.Request('http://127.0.0.1:8000/api/v1/fax-documents?tenant_id=anshin-phase1&pbx_unique_id=isolated-send-document',data=body,headers={'Content-Type':'application/pdf','X-Anshin-Internal-Token':'test-internal-token'});print(urllib.request.urlopen(req,timeout=10).read().decode())"
        document = json.loads(run(base + ["exec", "-T", "backend", "python", "-c", code], env=env, input_text=base64.b64encode(pdf_path.read_bytes()).decode()).stdout)
        # Use the exact production encryption function with the actual runtime
        # key; no manually reconstructed protected reference or driver.
        code = "import base64;from app.core.fax_storage import encrypt;print('encrypted:'+base64.b64encode(encrypt(b'0300000000','anshin-phase1')).decode())"
        protected_destination = run(base + ["exec", "-T", "backend", "python", "-c", code], env=env).stdout.strip()
        run(base + ['pause', 'pbx-event-forwarder'], env=env)
        forwarder_paused = True
        job = backend_request(base, env, "POST", "/api/v1/fax-jobs", {
            "tenant_id": "anshin-phase1", "phone_number_id": fax_number["id"],
            "idempotency_key": "isolated-real-fax-send", "destination_masked": "030****0000",
            "destination_reference": protected_destination, "pdf_storage_reference": "fax-document:" + document["id"] + ".pdf"})
        sent_source = pending_source('fax-attempts', job['id'])
        run(base + ['unpause', 'pbx-event-forwarder'], env=env)
        forwarder_paused = False
        deadline = time.monotonic() + 90
        completed = None
        while time.monotonic() < deadline:
            jobs = backend_request(base, env, "GET", "/api/v1/fax-jobs?tenant_id=anshin-phase1")
            completed = next(j for j in jobs if j["id"] == job["id"])
            if completed["status"] in {"sent", "failed"}:
                break
            time.sleep(1)
        if completed["status"] != "sent":
            carrier_output.flush()
            print("\n".join(carrier_log.read_text().splitlines()[-40:]), flush=True)
            raise RuntimeError(f"phase=fax-send state=failed result={completed['status']} code={completed['failure_code']}")
        observed = run(base + ["exec", "-T", "mock-carrier", "cat", "/tmp/mock-fax-status"], env=env).stdout.strip()
        if observed != "SUCCESS":
            raise RuntimeError("phase=fax-send state=failed consumer=mock-carrier")
        removed_source(sent_source)
        print("PASS: queued PDF -> actual SendFAX -> mock carrier ReceiveFAX -> completion/history", flush=True)
        print('PASS: received and sent TIFF preserved while consumer paused; exact originals reclaimed only after typed Backend ACK', flush=True)
        if env.get("PHONE_TEST_FRONTEND_DIR"):
            run_management_browser_flow(base, env, secret_path)
        completed = True
        return carrier.pid if env.get("PHONE_PREVIEW_DIR") else None

    finally:
        if forwarder_paused:
            run(base + ['unpause', 'pbx-event-forwarder'], env=env, check=False)
        if load_smartphone is not None and load_smartphone.poll() is None:
            load_smartphone.terminate()
            load_smartphone.communicate(timeout=5)
        if not (completed and env.get("PHONE_PREVIEW_DIR")):
            if carrier.poll() is None:
                carrier.terminate()
            try:
                carrier.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                carrier.kill()
                carrier.communicate(timeout=5)
        carrier_output.close()


def run_backup_restore(base: list[str], env: dict[str,str], directory: Path) -> None:
    print("phase=isolated-backup-restore state=started",flush=True)
    project = base[base.index("--project-name") + 1]
    compose_files = [base[i+1] for i,value in enumerate(base) if value == "--file"]
    backup_env = dict(env, COMPOSE_PROJECT_NAME=project, COMPOSE_FILE=os.pathsep.join(compose_files))
    run(base + ["pause","backend","asterisk","pbx-event-forwarder"],env=env)
    try:
        result = run(["sh",str(ROOT / "scripts/create_phase1_backup.sh"),"--execute",str(directory / "backup")],env=backup_env)
        print(result.stdout,end="",flush=True)
    finally:
        run(base + ["unpause","backend","asterisk","pbx-event-forwarder"],env=env)
    backup = next((directory / "backup").iterdir())
    run(["shasum","-a","256","-c",str(backup / "SHA256SUMS")],env=env)
    restore_db = "phone_restore_" + uuid.uuid4().hex[:12]
    restore_root = "/var/lib/anshin-phone/fax/" + restore_db
    # Restore into a new database and private storage subdirectory, never the
    # producer database/volume paths used by the UI's final consumer.
    run(base + ["exec","-T","postgres","createdb","-U","anshin_phone",restore_db],env=env)
    try:
        with (backup / "postgres.dump").open("rb") as source:
            subprocess.run(base + ["exec","-T","postgres","pg_restore","--exit-on-error","--no-owner","-U","anshin_phone","-d",restore_db],cwd=ROOT,env=env,stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        run(base + ["exec","-T","backend","mkdir","-m","700",restore_root],env=env)
        with (backup / "fax-encrypted.tar").open("rb") as source:
            subprocess.run(base + ["exec","-T","backend","tar","-xf","-","-C",restore_root],cwd=ROOT,env=env,stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        code = "from sqlalchemy import select;from app.core.database import SessionLocal;from app.models.telephony import FaxDocument,FaxJob,CallRecord;from app.core.fax_storage import read,validate_document;db=SessionLocal();docs=list(db.scalars(select(FaxDocument)));assert len(docs)>=3;assert len(list(db.scalars(select(CallRecord))))>=2;assert len(list(db.scalars(select(FaxJob).where(FaxJob.status=='sent'))))>=2;[(validate_document(read(db,d.tenant_id,d.id)[1],d.content_type)) for d in docs];print('PASS: isolated restored database and AES-GCM originals through production reader')"
        result = run(base + ["exec","-T","--env","ANSHIN_PHONE_DB_NAME="+restore_db,"--env","ANSHIN_PHONE_FAX_STORAGE_DIR="+restore_root,"backend","python","-c",code],env=env)
        print(result.stdout,end="",flush=True)
    finally:
        run(base + ["exec","-T","postgres","dropdb","-U","anshin_phone",restore_db],env=env)
        run(base + ["exec","-T","backend","rm","-rf",restore_root],env=env)


def run_isolated_e2e(*, preflight_only: bool = False, fixture_only: str | None = None) -> int:
    if shutil.which("docker") is None:
        raise RuntimeError("docker is required")

    if os.environ.get("PHONE_PREVIEW_DIR") and (not os.environ.get("PHONE_TEST_FRONTEND_DIR") or fixture_only is not None):
        raise RuntimeError("process-start=0: owner preview requires the complete UI consumer path")
    backend_root = resolve_backend(ROOT, os.environ.get("ANSHIN_PHONE_BACKEND_DIR"))
    ensure_mock_networks_available(os.environ.copy())
    if os.environ.get("PHONE_TEST_FRONTEND_DIR"):
        validate_browser_inputs(os.environ.copy())
        if shutil.which("pnpm") is None:
            raise RuntimeError("process-start=0: pnpm is unavailable for the UI consumer")
        if os.environ.get("PHONE_LOCAL_OIDC_ISSUER") != "http://localhost:18115/realms/phone-foundation-local":
            raise RuntimeError("process-start=0: owned local authentication origin mismatch")
        import urllib.request
        with urllib.request.urlopen(os.environ["PHONE_LOCAL_OIDC_ISSUER"] + "/.well-known/openid-configuration",timeout=5) as response:
            discovery = json.load(response)
        if discovery["issuer"] != os.environ["PHONE_LOCAL_OIDC_ISSUER"]:
            raise RuntimeError("process-start=0: authentication issuer input was not accepted")

    project = f"anshin-phone-sip-test-{uuid.uuid4().hex[:8]}"
    with fixture_directory() as (secret_path, retention):
        secret_dir = str(secret_path)
        for name, value in {
            "postgres_password": "test-postgres-password",
            "carrier_sip_password": "test-carrier-password",
            "smartphone_sip_password": "test-smartphone-password",
            "internal_api_token": "test-internal-token",
            "fax_storage_key": "6" * 64,
        }.items():
            path = secret_path / name
            path.write_text(value, encoding="utf-8")
            # Compose bind-mounts retain the host mode. Only synthetic values
            # live here; the enclosing TemporaryDirectory remains owner-only.
            path.chmod(0o444)

        env = os.environ.copy()
        env.update(
            {
                "ANSHIN_PHONE_BACKEND_DIR": str(backend_root),
                "ANSHIN_PHONE_TENANT_ID": "anshin-phase1",
                "ANSHIN_PHONE_SECRET_DIR": secret_dir,
                "CARRIER_AUTH_MODE": "ip",
                "CARRIER_HOST": "mock-carrier",
                "CARRIER_PORT": "5060",
                "CARRIER_QUALIFY_FREQUENCY": "0",
                "CARRIER_SOURCE_CIDRS": "10.254.250.10/32",
                "CARRIER_SIP_USERNAME": "mock-carrier",
                "PUBLIC_SIP_IP": "10.254.250.40",
                "PUBLIC_RTP_IP": "10.254.250.50",
                "SMARTPHONE_SOURCE_CIDRS": "10.254.250.30/32",
                "TEL_DID": "0300000001",
                "FAX_DID": "0300000002",
                "SMARTPHONE_EXTENSION": "2001",
                "SMARTPHONE_QUALIFY_FREQUENCY": "0",
            }
        )
        base = compose_args(project)
        if fixture_only == "softphone":
            from softphone_sip_fixture import prepare_softphone_override
            base += ["--file", str(prepare_softphone_override(ROOT, secret_path, env, run))]
        run(base + ["config", "--quiet"], env=env)
        if preflight_only:
            print("phase=diagnostic-preflight state=ready process-start=0 quality=not-run", flush=True)
            return 0
        env["PHONE_TEST_EXPIRES_AT"] = fixture_labels(project)["care.anshin.local.expires_at"]
        compiled=json.loads(run(base+["config","--format","json","--no-env-resolution"],env=env).stdout)
        ownership=secret_path/"fixture-ownership.json"
        ownership.write_text(json.dumps(fixture_ownership_override(compiled,project,env["PHONE_TEST_EXPIRES_AT"])))
        ownership.chmod(0o600)
        base += ["--file",str(ownership)]
        failed = False
        try:
            bootstrap_started = time.monotonic()
            print("phase=compose-bootstrap state=started", flush=True)
            if fixture_only == "database":
                run(base + ["up", "--detach", "--build", "postgres", "backend-migrate"], env=env)
                run(base + ["wait", "backend-migrate"], env=env)
                print(f"phase=database-fixture state=completed wall_seconds={time.monotonic() - bootstrap_started:.3f} integration=not-run", flush=True)
                return 0
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
                    "rtpengine",
                    "kamailio",
                    "asterisk",
                ],
                env=env,
            )
            print(result.stdout, end="")
            print(f"phase=compose-bootstrap state=completed wall_seconds={time.monotonic() - bootstrap_started:.3f}", flush=True)
            wait_for_sbc(base, env)
            wait_for_asterisk(base, env)
            wait_for_backend(base, env)
            tel_number = backend_request(
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
            fax_number = backend_request(
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

            for national_number in ("0300000001", "0300000002"):
                records = backend_request(base, env, "GET", "/api/v1/phone-numbers?tenant_id=anshin-phase1")
                number = next(n for n in records if n["national_number"] == national_number)
                backend_request(base, env, "PATCH", f"/api/v1/phone-numbers/{number['id']}", {"status": "testing"})
            endpoint = backend_request(base, env, "POST", "/api/v1/sip-endpoints", {
                "tenant_id": "anshin-phase1", "extension": "2001", "display_name": "Isolated smartphone"})
            backend_request(base, env, "PATCH", f"/api/v1/sip-endpoints/{endpoint['id']}", {"status": "active"})
            assignment = backend_request(base, env, "POST", "/api/v1/phone-number-assignments", {
                "tenant_id": "anshin-phase1", "phone_number_id": tel_number["id"], "sip_endpoint_id": endpoint["id"]})
            configuration = backend_request(base, env, "GET", "/api/v1/pbx-configuration?tenant_id=anshin-phase1")
            credentials = "SEQUENTIAL\n2001;[authentication username=2001 password=" + configuration["endpoints"][0]["password"] + "]\n"
            run(base + ["exec", "-T", "mock-smartphone", "sh", "-c", "umask 077; cat > /tmp/device.csv"], env=env, input_text=credentials)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                output = run(base + ["exec", "-T", "asterisk", "asterisk", "-rx", "pjsip show endpoints"], env=env).stdout
                if "2001" in output:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("phase=endpoint-provisioning state=timeout")
            print("PASS: backend active endpoint -> actual PBX configuration")

            if fixture_only == "softphone":
                if env.get('PHONE_SOFTPHONE_SIMULATOR'):
                    from softphone_sip_fixture import run_simulator_flow
                    run_simulator_flow(base, env, endpoint, configuration, run, exec_background, finish)
                    return 0
                from softphone_sip_fixture import run_softphone_flow
                run_softphone_flow(base, env, endpoint, configuration, backend_request, run, exec_background, finish)
                return 0

            if fixture_only == "fax":
                run_fax_flow(base, env, fax_number, secret_path,with_load=False)
                return 0

            if fixture_only == "management":
                print(f"phase=management-fixture state=ready project={project} source={backend_root}", flush=True)
                # The UI is the last consumer. Keep producer resources and
                # their original secret mounts alive until the owning session
                # terminates this fixture; cleanup then follows the same path.
                import signal
                stopped = False
                def stop(*_):
                    nonlocal stopped
                    stopped = True
                signal.signal(signal.SIGTERM, stop)
                signal.signal(signal.SIGINT, stop)
                while not stopped:
                    time.sleep(1)
                return 0

            registration = run(
                base
                + [
                    "exec",
                    "-T",
                    "mock-smartphone",
                    "sipp",
                    "-nostdin",
                    "10.254.250.40:5060",
                    "-sf",
                    "/scenarios/smartphone_register.xml",
                    "-inf", "/tmp/device.csv",
                    "-i",
                    "10.254.250.30",
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
                    "-trace_msg", "-message_file", "/tmp/inbound-uas.log", "-recv_timeout", "10000",
                    "-i",
                    "10.254.250.30",
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
                    "10.254.250.40:5060",
                    "-sf",
                    "/scenarios/carrier_inbound_uac.xml",
                    "-i",
                    "10.254.250.10",
                    "-p",
                    "5060",
                    "-m",
                    "1",
                    "-timeout",
                    "15s",
                    "-trace_msg",
                    "-message_file",
                    "/tmp/inbound-messages.log",
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
            inbound_trace = run(
                base + ["exec", "-T", "mock-carrier", "cat", "/tmp/inbound-messages.log"],
                env=env,
            ).stdout
            if "c=IN IP4 10.254.250.50" not in inbound_trace:
                raise RuntimeError("RTPengine did not rewrite inbound response SDP to its edge address")
            print("PASS: mock carrier -> Kamailio/RTPengine -> Asterisk -> smartphone")

            carrier = exec_background(
                base,
                "mock-carrier",
                [
                    "sipp",
                    "-nostdin",
                    "-sf",
                    "/scenarios/carrier_outbound_uas.xml",
                    "-i",
                    "10.254.250.10",
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
                    "10.254.250.40:5060",
                    "-sf",
                    "/scenarios/smartphone_outbound_uac.xml",
                    "-inf", "/tmp/device.csv",
                    "-i",
                    "10.254.250.30",
                    "-p",
                    "5060",
                    "-m",
                    "1",
                    "-timeout",
                    "15s",
                    "-trace_msg",
                    "-message_file",
                    "/tmp/outbound-messages.log",
                ],
                env,
            )
            finish(outbound, "mock smartphone outbound scenario")
            finish(carrier, "mock carrier outbound scenario")
            outbound_trace = run(
                base + ["exec", "-T", "mock-smartphone", "cat", "/tmp/outbound-messages.log"],
                env=env,
            ).stdout
            if "c=IN IP4 10.254.250.50" not in outbound_trace:
                raise RuntimeError("RTPengine did not rewrite outbound response SDP to its edge address")
            print("PASS: smartphone -> Kamailio/RTPengine -> Asterisk -> mock carrier")

            call_records = wait_for_event_count(base, env, "call-records", 2)
            if not all("*" in str(record["remote_number_masked"]) for record in call_records):
                raise RuntimeError("unmasked call record reached the backend")
            print("PASS: Asterisk call events -> durable spool -> Backend")
            observed = run(base + ["logs","--no-color","asterisk"],env=env).stdout
            media = re.findall(r"phase=voice-media direction=(inbound|outbound) rx=([0-9]+) tx=([0-9]+)",observed)
            if not all(any(d == direction and int(rx)>=20 and int(tx)>=20 for d,rx,tx in media) for direction in ("inbound","outbound")):
                raise RuntimeError("phase=voice-media state=failed expected=bidirectional-PCMU-packets")
            print("PASS: actual bidirectional synthetic PCMU media in inbound and outbound calls",flush=True)
            # Existing registered contacts must not bypass current assignment
            # or endpoint status. These are real SIP failures, not DB-only checks.
            backend_request(base, env, "DELETE", f"/api/v1/phone-number-assignments/{assignment['id']}?tenant_id=anshin-phase1")
            denied = run(base + ["exec", "-T", "mock-carrier", "sipp", "-nostdin", "10.254.250.40:5060",
                "-sf", "/scenarios/carrier_inbound_denied.xml", "-i", "10.254.250.10", "-p", "5060", "-m", "1", "-timeout", "15s"], env=env)
            print("PASS: unassigned number denies actual inbound SIP", flush=True)
            backend_request(base, env, "PATCH", f"/api/v1/sip-endpoints/{endpoint['id']}", {"status":"suspended"})
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                output = run(base + ["exec", "-T", "asterisk", "asterisk", "-rx", "pjsip show endpoints"], env=env).stdout
                if "Endpoint:  2001" not in output:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("phase=endpoint-stop state=timeout")
            run(base + ["exec", "-T", "mock-smartphone", "sipp", "-nostdin", "10.254.250.40:5060",
                "-sf", "/scenarios/smartphone_register_denied.xml", "-inf", "/tmp/device.csv", "-i", "10.254.250.30", "-p", "5060", "-m", "1", "-timeout", "15s"], env=env)
            print("PASS: stopped endpoint rejects old REGISTER credentials", flush=True)
            backend_request(base, env, "PATCH", f"/api/v1/sip-endpoints/{endpoint['id']}", {"status":"active"})
            backend_request(base, env, "POST", "/api/v1/phone-number-assignments", {"tenant_id":"anshin-phase1", "phone_number_id":tel_number["id"], "sip_endpoint_id":endpoint["id"]})


            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                if "2001" in run(base+["exec","-T","asterisk","asterisk","-rx","pjsip show endpoints"],env=env).stdout:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("phase=endpoint-reconnect state=configuration-timeout")
            run(base+["exec","-T","mock-smartphone","sipp","-nostdin","10.254.250.40:5060","-sf","/scenarios/smartphone_register.xml",
                "-inf","/tmp/device.csv","-i","10.254.250.30","-p","5060","-m","1","-timeout","15s"],env=env)
            wait_for_smartphone_contact(base,env)
            print("PASS: restored endpoint reconnects through actual REGISTER",flush=True)

            if fixture_only == "voice":
                return 0
            carrier_exec_pid = run_fax_flow(base, env, fax_number, secret_path)
            if env.get("PHONE_TEST_FRONTEND_DIR"):
                run_backup_restore(base,env,secret_path)
            if env.get("PHONE_PREVIEW_DIR"):
                (secret_path / "runtime.json").write_text(json.dumps({"project":project,"compose":base,
                    "backend_sha":run(["git","-C",str(backend_root),"rev-parse","HEAD"],env=env).stdout.strip(),
                    "infra_sha":run(["git","rev-parse","HEAD"],env=env).stdout.strip(),
                    "url":"http://localhost:3015/dashboard","quality":"business-flow-passed",
                    "cleanup_after":"owner-final-browser-consumer","carrier_exec_pid":carrier_exec_pid},ensure_ascii=False,indent=2))
                retention["retain"] = True
                print("phase=owner-preview state=retained cleanup=after-final-consumer",flush=True)
        except Exception as exc:
            failed = True
            if isinstance(exc, subprocess.CalledProcessError):
                print(exc.stdout or "", end="", flush=True)
            logs = run(
                base
                + [
                    "logs",
                    "--no-color",
                    "asterisk",
                    "kamailio",
                    "rtpengine",
                    "pbx-event-forwarder",
                    "backend",
                    "backend-migrate",
                    "postgres",
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
            # Bound protocol diagnostics: keep private response traces outside
            # Git; report methods/status only, never authentication values.
            trace = run(base + ["exec","-T","mock-smartphone","cat","/tmp/inbound-uas.log"],env=env,check=False).stdout
            print("phase=voice-uas protocol=" + ",".join(re.findall(r"(?:SIP/2.0 [0-9]{3}|(?:INVITE|ACK|BYE) sip:)",trace)),flush=True)
            raise
        finally:
            if not retention["retain"]:
                cleanup_owned_runtime(base,project,env,failed)
    return 0


def production_backup_transition_fixture(runtime, temporary, profile):
    """Real capture/DB/FAX/stop-start; age and S3 are explicit fixture boundaries."""
    from unittest.mock import patch
    import errno
    import phone_postgresql_backup_adapter as owner
    from production_runtime import RuntimeFailure
    state = temporary / 'capture-state'; state.mkdir(mode=0o700)
    keys = temporary / 'capture-keys'; keys.mkdir(mode=0o700)
    recipient = keys / 'phone-age-recipient.txt'; recipient.write_text('fixture-age-boundary'); recipient.chmod(0o600)
    config = temporary / 'backup-profile.json'
    public = {'trust_anchor_arn':'arn:aws:rolesanywhere:ap-northeast-1:691862619128:trust-anchor/916219bc-2500-4f73-a7b2-82e0c94ec215',
              'manifest_key_id':'a'*64,'credential_versions':{key:1 for key in owner.CREDENTIAL_IDS}}
    for purpose, product in (('db','phone-postgresql'),('fax','phone-fax')):
        for role in ('writer','restore'):
            public[purpose+'_'+role+'_role_arn']='arn:aws:iam::691862619128:role/anshin-prod-'+product+'-backup-'+role
            public[purpose+'_'+role+'_profile_arn']='arn:aws:rolesanywhere:ap-northeast-1:691862619128:profile/12345678-1234-1234-1234-123456789abc'
    config.write_text(json.dumps({'manifest_key_id':'a'*64,'governance_sha':'c'*40,'infra_sha':profile['infra_sha'],'public':public}))
    config.chmod(0o600)
    original_command, original_runner = runtime.command, runtime.runner
    captures=[]; drift=[False]
    def runner(argv, **kwargs):
        if argv[:2]==['bash','-c'] and len(argv)==7 and argv[3]=='phone-dump':
            # Store the native pg_dump bytes only in this private temporary
            # fixture. This is not age/S3 acceptance and never reaches AWS.
            with Path(argv[6]).open('xb') as output:
                os.chmod(argv[6],0o600)
                return original_runner(['docker','start','--attach',argv[4]],**{**kwargs,'stdout':output})
        return original_runner(argv,**kwargs)
    def command(argv, **kwargs):
        if argv==['python3','/opt/anshin-phone-backup/scripts/phone_postgresql_backup_adapter.py','--scheduled-backup']:
            result=owner.scheduled_backup(runtime=runtime,config_path=config)
            if drift[0]:
                backend=runtime.compose(profile,'ps','--quiet','--no-trunc','backend').stdout.strip()
                original_command(['docker','restart','--time','30',backend],timeout=45)
                deadline=time.monotonic()+30
                while True:
                    try:runtime.health(profile);break
                    except RuntimeFailure:
                        if time.monotonic()>=deadline:raise
                        time.sleep(1)
            return subprocess.CompletedProcess(argv,0,json.dumps(result),'')
        if argv==['bash','/opt/anshin-phone-backup/sh/backup_postgresql_to_s3.sh']:
            try:os.fstat(9)
            except OSError as error:
                if error.errno!=errno.EBADF:raise
            else:raise RuntimeError('fixture preserves an already open fd9')
            work=Path(tempfile.mkdtemp(prefix='.capture-',dir=state));work.chmod(0o700)
            with runtime.lock.open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                duplicated=lock.fileno()!=9
                if duplicated:os.dup2(lock.fileno(),9,inheritable=False)
                try:
                    with patch.dict(os.environ,kwargs['env']):
                        result=owner.capture_pair(work,work/'fixture.dump.age',recipient,runtime=runtime)
                finally:
                    if duplicated:os.close(9)
            captures.append(result)
            return subprocess.CompletedProcess(argv,0,json.dumps(result)+'\n[fixture] S3 upload boundary completed\n','')
        return original_command(argv,**kwargs)
    with patch.object(owner,'STATE',state),patch.object(owner,'KEYS',keys), \
         patch.object(runtime,'runner',side_effect=runner),patch.object(runtime,'command',side_effect=command):
        result=runtime.deploy(profile['backend_image'],profile['backend_sha'],profile['infra_sha'])
        if result['status']!='deployed' or len(captures)!=1:
            raise RuntimeError('capture transition fixture did not deploy')
        if captures[0]['runtime_transition']['before']==captures[0]['runtime_transition']['after']:
            raise RuntimeError('capture fixture did not observe the real Backend restart')
        saved=runtime.profile();drift[0]=True
        try:runtime.deploy(profile['backend_image'],profile['backend_sha'],profile['infra_sha'])
        except RuntimeFailure as error:
            if str(error)!='phone_runtime_changed_during_backup':raise
        else:raise RuntimeError('post-capture extra restart was accepted')
        if runtime.profile()!=saved or len(captures)!=2:
            raise RuntimeError('drift failure changed its profile')
        runtime.health(saved)
    print('PASS: deploy -> scheduled owner -> real native DB/FAX capture -> same Backend restart -> deploy; extra restart after producer rejected. age and S3 use fixture boundaries, not production acceptance.',flush=True)


def run_production_management_fixture(image: str, backend_sha: str) -> int:
    """Exercise the packaged production image through its actual guest owner.

    This proves first deployment, migration and management-only health. It
    deliberately does not claim the pending production backup/restore adapter.
    """
    import secrets
    import socket
    import base64
    from datetime import datetime, timedelta, timezone
    from production_runtime import Runtime, RuntimeFailure, run_owned_process

    if not image or not backend_sha:
        raise RuntimeError('process-start=0: production image and source SHA are required')
    env = os.environ.copy()
    ensure_mock_networks_available(env)
    project = 'phone-management-' + uuid.uuid4().hex[:12]
    transport = {key: env[key] for key in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG') if key in env}
    if not transport.get('DOCKER_HOST'):
        transport['DOCKER_HOST'] = run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'], env=env).stdout.strip()
    with fixture_directory(prefix='phone-production-fixture-', allow_preview=False) as (directory, _retention):
        temporary = Path(directory)
        network_override = temporary / 'production-fixture-networks.json'
        network_override.write_text(json.dumps({'networks': {
            name: {'ipam': {'config': [{'subnet': subnet}]}}
            for name, subnet in zip(('phone-data', 'phone-auth-egress'), MOCK_SUBNETS, strict=True)
        }}))
        network_override.chmod(0o600)
        # Reuse the owner-issued publisher credential without touching the
        # user's Docker config or Keychain. Values remain in stdin/memory and
        # the private temporary credential file until the last consumer exits.
        registry = temporary / 'docker'
        registry.mkdir(mode=0o700)
        publisher = run_owned_process(['gh', 'api', 'user', '--jq', '.login'], env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        credential = run_owned_process(['gh', 'auth', 'token'], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if publisher.returncode or credential.returncode or not credential.stdout.strip():
            raise RuntimeError('process-start=0: existing GitHub publisher credential unavailable')
        auth = base64.b64encode((publisher.stdout.strip() + ':' + credential.stdout.strip()).encode()).decode()
        del credential
        # Do not call docker login: native helper auto-discovery can write to
        # Keychain even when --config points to an otherwise empty directory.
        config = {'auths': {'ghcr.io': {'auth': auth}}}
        del auth
        plugin_result = run_owned_process(['docker', 'info', '--format',
            '{{range .ClientInfo.Plugins}}{{if eq .Name "compose"}}{{.Path}}{{end}}{{end}}'], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if plugin_result.returncode:
            raise RuntimeError('process-start=0: existing Docker plugin unavailable')
        plugin = plugin_result.stdout.strip()
        if plugin:
            config['cliPluginsExtraDirs'] = [str(Path(plugin).parent)]
        config_path = registry / 'config.json'
        descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(config, output)
        del config
        transport['DOCKER_CONFIG'] = str(registry)
        secret_root = temporary / 'secrets'
        secret_root.mkdir(mode=0o700)
        for name in ('postgres_password', 'internal_api_token', 'smartphone_sip_password', 'fax_storage_key'):
            path = secret_root / name
            path.write_text(secrets.token_hex(32))
            # Match the existing fixture: only synthetic values, within its
            # owner-only directory, readable by the image's nonroot UID.
            path.chmod(0o444)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        def volume_stat(mountpoint):
            # The daemon is inside the Mac Docker VM. Bind the already
            # inspected backing path: unlike a named volume or -v, --mount
            # fails if it disappeared and never creates a replacement.
            observed = runtime.command(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
                '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '0:0',
                '--label', 'com.docker.compose.project=' + project,
                '--label', 'com.docker.compose.service=volume-inspection',
                '--label', 'care.anshin.local.ephemeral=true',
                '--label', 'care.anshin.local.expires_at=' + (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                '--label', 'care.anshin.local.owner=MAC',
                '--label', 'care.anshin.local.task_id=phone-production-20261016',
                '--mount', 'type=bind,src=' + mountpoint + ',dst=/inspect,readonly',
                '--entrypoint', 'python', image, '-c',
                "import os,json; s=os.lstat('/inspect'); print(json.dumps({'mode':s.st_mode,'device':s.st_dev,'inode':s.st_ino}))"], timeout=30)
            return json.loads(observed.stdout)
        runtime = Runtime(root=ROOT, state=temporary / 'state', secrets=secret_root, project=project,
                          lock=temporary / 'release.lock', transport=transport, backend_port=port,
                          backend_bind='127.0.0.1', compose_extra_files=(network_override,), volume_stat=volume_stat)
        infra_sha = run(['git', 'rev-parse', 'HEAD'], env=env).stdout.strip()
        profile = {'source_root': str(ROOT), 'backend_image': image, 'backend_sha': backend_sha, 'infra_sha': infra_sha}
        compiled=json.loads(runtime.compose(profile,'config','--format','json','--no-env-resolution').stdout)
        ownership=fixture_ownership_override(compiled,project)
        for name, config in json.loads(network_override.read_text())["networks"].items():
            ownership["networks"].setdefault(name,{}).update(config)
        network_override.write_text(json.dumps(ownership))
        failed = True
        try:
            actual_health = runtime.health
            def first_health_failure(candidate):
                actual_health(candidate)
                raise RuntimeFailure('phone_fixture_initial_health_failure')
            runtime.health = first_health_failure
            try:
                runtime.deploy(image, backend_sha, infra_sha)
            except RuntimeFailure as error:
                if str(error) != 'phone_initial_deploy_failed_data_preserved':
                    raise
                recovery = error.initial_recovery
            else:
                raise RuntimeError('production fixture did not exercise initial failure')
            finally:
                runtime.health = actual_health
            if runtime.profile() is not None:
                raise RuntimeError('failed initial deployment wrote a runtime profile')
            # This is the native result which the existing central failed
            # receipt will bind. No new recovery journal is introduced.
            if recovery is None or recovery['candidate'] != profile:
                raise RuntimeError('initial failure did not capture its exact candidate under lock')
            runtime.compose(profile, 'exec', '-T', 'postgres', 'psql', '-U', 'anshin_phone', '-d', 'anshin_phone',
                '-v', 'ON_ERROR_STOP=1', '-c',
                'CREATE TABLE fixture_phone_initial_recovery (value integer PRIMARY KEY); '
                'INSERT INTO fixture_phone_initial_recovery VALUES (1)')
            foreign = json.loads(json.dumps(recovery))
            foreign['observation']['volumes'][0]['backing']['inode'] += 1
            try:
                runtime.deploy(image, backend_sha, infra_sha, initial_recovery=foreign)
            except RuntimeFailure as error:
                if str(error) != 'phone_initial_recovery_identity_changed':
                    raise
            else:
                raise RuntimeError('production fixture adopted a different backing identity')
            result = runtime.deploy(image, backend_sha, infra_sha, initial_recovery=recovery)
            if result['status'] != 'deployed':
                raise RuntimeError('production management fixture did not deploy')
            kept = runtime.compose(profile, 'exec', '-T', 'postgres', 'psql', '-U', 'anshin_phone', '-d', 'anshin_phone',
                '-At', '-v', 'ON_ERROR_STOP=1', '-c', 'SELECT value FROM fixture_phone_initial_recovery').stdout.strip()
            if kept != '1':
                raise RuntimeError('initial forward repair lost existing database data')
            if runtime.observation()['volumes'] != recovery['observation']['volumes']:
                raise RuntimeError('initial forward repair recreated a persistent volume')
            container = runtime.compose(profile, 'ps', '--quiet', 'backend').stdout.strip()
            published = json.loads(runtime.command(['docker', 'inspect', '--format',
                '{{json .NetworkSettings.Ports}}', container]).stdout)
            if published.get('8000/tcp') != [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]:
                raise RuntimeError('production fixture actual API binding differs')
            runtime.compose(profile, 'exec', '-T', 'backend', 'python', '-c',
                "from sqlalchemy import text; from app.core.database import engine; "
                "c=engine.connect(); assert c.execute(text('SELECT version_num FROM alembic_version')).scalar(); c.close()")
            probe = '''import urllib.request,urllib.error
from pathlib import Path
for path,headers,expected in [
 ('/api/v1/management/me/tenants',{},401),
 ('/api/v1/pbx-configuration?tenant_id=isolated',
  {'X-Anshin-Internal-Token':Path('/run/secrets/internal_api_token').read_text().strip()},503)]:
 try:
  urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000'+path,headers=headers),timeout=5)
 except urllib.error.HTTPError as error:
  assert error.code==expected
 else:
  raise AssertionError('management/carrier boundary unexpectedly open')
'''
            runtime.compose(profile, 'exec', '-T', 'backend', 'python', '-c', probe)
            print('PASS: immutable image -> actual settings/migration -> initial failure -> exact-resource forward repair -> readiness; DB data and volume identities retained; foreign identity/unauthenticated management denied and telephony disabled', flush=True)
            production_backup_transition_fixture(runtime,temporary,profile)
            # Only this fixture's synthetic documents are involved. Use the
            # real encrypted writer and calendar policy, including a missed
            # monthly run, rather than changing expiry directly in SQL.
            retention_setup = '''import io,json,hashlib
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi import HTTPException
from pypdf import PdfWriter
from sqlalchemy import func,select
from app.core.database import SessionLocal
from app.core import fax_storage
from app.models.telephony import AuditLog,FaxDocument,FaxRecord,PhoneNumber
now=datetime.now(timezone.utc)
first=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
old=first.replace(year=first.year-1)
buffer=io.BytesIO(); writer=PdfWriter(); writer.add_blank_page(width=100,height=100); writer.write(buffer)
content=buffer.getvalue()
with SessionLocal() as db:
 with patch.object(fax_storage,'utcnow',return_value=old):
  expired=fax_storage.store(db,'fixture-retention',content,'application/pdf')
 active=fax_storage.store(db,'fixture-retention',content,'application/pdf')
 number=PhoneNumber(tenant_id='fixture-retention',e164='+81300000000',national_number='0300000000',
  area_code='03',usage='fax',carrier_name='fixture-only')
 db.add(number); db.flush()
 record=FaxRecord(tenant_id='fixture-retention',phone_number_id=number.id,pbx_unique_id='fixture-retention',
  direction='inbound',remote_number_masked='fixture-only',status='received',
  storage_reference=expired.id,occurred_at=old)
 audit=AuditLog(tenant_id='fixture-retention',actor_subject='fixture-only',action='fax.received',
  resource_type='fax_document',resource_id=expired.id)
 db.add_all([record,audit]); db.commit()
 assert expired.expires_at < now < active.expires_at
 assert fax_storage.storage_path(expired.id).is_file()
 assert fax_storage.read(db,'fixture-retention',active.id)[1]==content
 try: fax_storage.read(db,'fixture-retention',expired.id)
 except HTTPException as error: assert error.status_code==410
 else: raise AssertionError('expired original was readable')
 assert db.scalar(select(func.count()).select_from(FaxDocument))==2
 print(json.dumps({'expired':expired.id,'active':active.id,'record':record.id,'audit':audit.id,
  'sha256':hashlib.sha256(content).hexdigest()}))
'''
            documents = json.loads(runtime.compose(profile, 'exec', '-T', 'backend', 'python', '-c', retention_setup).stdout)
            from phone_postgresql_backup_adapter import purge_expired
            purged = purge_expired(runtime=runtime)
            if purged['status'] != 'completed' or purged['purged_count'] != 1:
                raise RuntimeError('production retention fixture did not purge only its expired original')
            retention_readback = '''import json,sys,hashlib
from fastapi import HTTPException
from sqlalchemy import func,select
from app.core.database import SessionLocal
from app.core import fax_storage
from app.models.telephony import AuditLog,FaxDocument,FaxRecord
value=json.loads(sys.argv[1])
with SessionLocal() as db:
 expired=db.get(FaxDocument,value['expired']); active,content=fax_storage.read(db,'fixture-retention',value['active'])
 assert expired is not None and expired.purged_at is not None
 assert not fax_storage.storage_path(expired.id).exists()
 assert active.purged_at is None and fax_storage.storage_path(active.id).is_file()
 assert hashlib.sha256(content).hexdigest()==value['sha256']
 assert db.scalar(select(func.count()).select_from(FaxDocument))==2
 assert db.get(FaxRecord,value['record']).storage_reference==expired.id
 assert db.get(AuditLog,value['audit']).resource_id==expired.id
 try: fax_storage.read(db,'fixture-retention',expired.id)
 except HTTPException as error: assert error.status_code==410
 else: raise AssertionError('purged original was readable')
'''
            runtime.compose(profile, 'exec', '-T', 'backend', 'python', '-c', retention_readback, json.dumps(documents))
            runtime.require_retention_absent()
            if runtime.observation()['volumes'] != recovery['observation']['volumes']:
                raise RuntimeError('production retention changed persistent volume identity')
            print('PASS: actual calendar-policy encrypted FAX writer -> fixed maintenance consumer -> exact-ID cleanup -> reader; expired ciphertext removed, active ciphertext readable, both history rows and volume identities retained', flush=True)
            # Resource evidence is a fixture measurement, not VM capacity acceptance.
            measurements = {}
            for service in ('backend', 'postgres'):
                container = runtime.compose(profile, 'ps', '--quiet', service).stdout.strip()
                state = runtime.command(['docker', 'inspect', '--format',
                    '{{json .State.OOMKilled}} {{json .RestartCount}}', container]).stdout.strip()
                peak = runtime.compose(profile, 'exec', '-T', service, 'cat', '/sys/fs/cgroup/memory.peak', allow_failure=True)
                measurements[service] = {'oom_and_restarts': state,
                    'container_memory_peak_bytes': int(peak.stdout.strip()) if peak.returncode == 0 and peak.stdout.strip().isdigit() else None}
            print(json.dumps({'phase': 'production-management-measurement', 'services': measurements,
                              'vm_capacity_accepted': False}, sort_keys=True), flush=True)
            failed = False
        finally:
            cleanup = runtime.compose(profile, 'down', '--volumes', '--remove-orphans', allow_failure=True)
            selector = f'label=com.docker.compose.project={project}'
            residue = [kind for kind in ('container', 'volume', 'network')
                       if runtime.command(['docker', kind, 'ls', '--quiet', '--filter', selector]).stdout.strip()]
            ensure_cleanup_succeeded(cleanup, residue, failed)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preflight", action="store_true", help="validate fixture inputs without build or container startup")
    modes.add_argument("--fixture", choices=("database", "management", "voice", "fax", "production", "softphone"), help="diagnose a minimal real runtime")
    parser.add_argument('--backend-image', help='immutable published image for production fixture')
    parser.add_argument('--backend-sha', help='published Backend source for production fixture')
    args = parser.parse_args(argv)
    if args.preflight:
        return run_isolated_e2e(preflight_only=True)
    try:
        with fixture_signals(), docker_test_lease():
            if args.fixture == 'production':
                return run_production_management_fixture(args.backend_image, args.backend_sha)
            return run_isolated_e2e(fixture_only=args.fixture)
    except FixtureInterrupted as error:
        return 128 + error.signum


if __name__ == "__main__":
    raise SystemExit(main())
