#!/usr/bin/env python3
"""Dispatch backend FAX jobs through the actual Asterisk fax application."""
from __future__ import annotations

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

from pbx_management import request
from pbx_event_spool import write_event

FAX_ROOT = Path('/var/spool/asterisk/fax')
CALL_ROOT = Path('/var/spool/asterisk')


def valid_id(value: str) -> str:
    if not re.fullmatch(r'[0-9a-f-]{36}', value):
        raise ValueError('invalid FAX job identity')
    return value


def enqueue(job: dict) -> None:
    job_id = valid_id(job['id'])
    valid_id(job['claim_id'])
    outgoing = CALL_ROOT / 'outgoing'
    outgoing.mkdir(mode=0o750, exist_ok=True)
    temporary = CALL_ROOT / (job_id + '.call.tmp')
    temporary.write_text(f'Channel: Local/{job_id}@fax-dispatch/n\nMaxRetries: 0\nWaitTime: 180\nApplication: Wait\nData: 180\nArchive: no\n')
    temporary.chmod(0o600)
    temporary.replace(outgoing / (job_id + '.call'))


def poll() -> int:
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    params = urllib.parse.urlencode({'tenant_id': os.environ['ANSHIN_PHONE_TENANT_ID']})
    while not stopped:
        try:
            job = request('/api/v1/fax-worker/claim?' + params, {})
            if job:
                try:
                    enqueue(job)
                except OSError:
                    result_event(job['id'], job['claim_id'], 'retryable_failure', 'LOCAL_QUEUE_UNAVAILABLE')
                    print('phase=fax-dispatch state=queue-unavailable', file=sys.stderr, flush=True)
                else:
                    print('phase=fax-dispatch state=queued', flush=True)
        except Exception as exc:
            print(f"phase=fax-dispatch state=unavailable error={type(exc).__name__} errno={exc.errno if isinstance(exc, OSError) else 0}", file=sys.stderr, flush=True)
        time.sleep(2)
    return 0


def result_event(job_id: str, claim_id: str, outcome: str, failure_code: str | None) -> None:
    write_event({'kind': 'fax-attempts', 'payload': {'job_id': valid_id(job_id),
        'claim_id': valid_id(claim_id), 'outcome': outcome, 'failure_code': failure_code,
        'pbx_unique_id': 'fax-attempt-' + claim_id}})


def set_variable(name: str, value: str) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_./-]*', value):
        raise ValueError('invalid FAX channel variable')
    print(f'SET VARIABLE {name} "{value}"', flush=True)
    if not sys.stdin.readline().startswith('200 result='):
        raise RuntimeError('FAX AGI response was not accepted')


def prepare(job_id: str) -> int:
    job_id = valid_id(job_id)
    tenant = os.environ['ANSHIN_PHONE_TENANT_ID']
    params = urllib.parse.urlencode({'tenant_id': tenant})
    job = request(f'/api/v1/fax-worker/{job_id}/current?' + params)
    if not job:
        set_variable('FAX_JOB_READY', '0')
        return 0
    if job['id'] != job_id or job['tenant_id'] != tenant:
        raise ValueError('FAX worker identity mismatch')
    claim_id = valid_id(job['claim_id'])
    temporary = FAX_ROOT / (job_id + '.pdf')
    target = FAX_ROOT / (job_id + '.tif')
    try:
        for name in ('destination', 'national_number'):
            if not re.fullmatch(r'0[0-9]{9,10}', job[name]):
                raise ValueError('invalid FAX route')
        route = request('/api/v1/pbx-route?' + urllib.parse.urlencode({
            'tenant_id': tenant, 'national_number': job['national_number'], 'fax': 'true'}))
        if not route['allowed']:
            raise ValueError('FAX source is unavailable')
        document_id = valid_id(job['document_id'])
        token = Path(os.environ['PBX_EVENT_TOKEN_FILE']).read_text().strip()
        req = urllib.request.Request(os.environ['PBX_EVENT_BACKEND_URL'].rstrip('/') + f'/api/v1/fax-documents/{document_id}?' + params,
            headers={'X-Anshin-Internal-Token': token})
        with urllib.request.urlopen(req, timeout=5) as response:
            content = response.read(10 * 1024 * 1024 + 1)
            if response.headers.get_content_type() != 'application/pdf' or len(content) > 10 * 1024 * 1024:
                raise ValueError('invalid FAX PDF response')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(content)
        subprocess.run(['gs', '-q', '-dSAFER', '-dBATCH', '-dNOPAUSE', '-sDEVICE=tiffg4', '-r204x196',
            '-sPAPERSIZE=a4', '-dFIXEDMEDIA', '-dFitPage', '-dMaxBitmap=20000000',
            '-sOutputFile=' + str(target), str(temporary)], timeout=30, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target.chmod(0o600)
        # Inherited variables bind the actual called channel to this attempt.
        for name, value in {'__FAX_JOB_ID': job_id, '__FAX_CLAIM_ID': claim_id,
            '__FAX_SEND_FILE': str(target), '__FAX_DESTINATION': job['destination'],
            '__FAX_SOURCE': job['national_number'], 'FAX_JOB_READY': '1'}.items():
            set_variable(name, value)
    except Exception as exc:
        print(f'phase=fax-prepare state=failed error={type(exc).__name__} errno={exc.errno if isinstance(exc, OSError) else 0}', file=sys.stderr)
        result_event(job_id, claim_id, 'permanent_failure', 'INPUT_UNAVAILABLE')
        target.unlink(missing_ok=True)
        set_variable('FAX_JOB_READY', '0')
    finally:
        temporary.unlink(missing_ok=True)
    return 0


def complete(arguments: list[str]) -> int:
    job_id, claim_id, fax_status, dial_status = arguments
    if fax_status == 'SUCCESS':
        outcome, code = 'sent', None
    elif dial_status in {'BUSY', 'NOANSWER', 'CONGESTION', 'CHANUNAVAIL'}:
        outcome, code = 'retryable_failure', dial_status
    else:
        outcome, code = 'permanent_failure', 'FAX_TRANSMISSION_FAILED'
    result_event(job_id, claim_id, outcome, code)
    (FAX_ROOT / (valid_id(job_id) + '.tif')).unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--poll']:
        raise SystemExit(poll())
    while sys.stdin.readline().strip():
        pass
    if sys.argv[1] == 'prepare':
        raise SystemExit(prepare(sys.argv[2]))
    if sys.argv[1] == 'complete':
        raise SystemExit(complete(sys.argv[2:]))
    raise SystemExit(2)
