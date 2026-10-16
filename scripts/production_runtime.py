#!/usr/bin/env python3
"""Own Compose transitions inside the dedicated Phone guest.

The central release owner supplies qualified source and an immutable image.
This module does not select releases, fetch Git, build images, or issue receipts.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
STATE = Path('/var/lib/anshin-phone/release')
SECRETS = Path('/etc/anshin-phone/secrets')
PROJECT = 'anshin-phone-production'
LOCK = Path('/tmp/anshin-ms-a2-2-platform-release.lock')
IMAGE = re.compile(r'ghcr\.io/hirotsugumatsumoto/anshin-phone-backend@sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
SETTINGS_CHECK = (
    'from app.core.config import get_settings; s=get_settings(); '
    'assert s.environment=="production" and not s.telephony_enabled; '
    'assert s.fax_retention_policy=="cloco_previous_month" and s.fax_retention_seconds is None; '
    'assert s.oidc_issuer=="https://auth.anshin.care/realms/anshin" and s.oidc_audience=="anshin-phone"; '
    'assert s.oidc_required_acr>=2 and s.fax_storage_key and s.sip_master_secret; '
    'from app.core.fax_storage import cipher; cipher()'
)


def run_owned_process(argv, **kwargs):
    """A cancelled local CLI must not outlive its release owner."""
    timeout = kwargs.pop('timeout')
    process = subprocess.Popen(argv, start_new_session=True, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
        raise


class RuntimeFailure(RuntimeError):
    """Expose an enum, never raw Docker output or consumer exceptions."""


class Runtime:
    def __init__(self, *, root=ROOT, state=STATE, secrets=SECRETS, project=PROJECT,
                 lock=LOCK, runner=run_owned_process, backend_port=8010, transport=None):
        self.root, self.state, self.secrets = Path(root), Path(state), Path(secrets)
        self.project, self.lock, self.runner = project, Path(lock), runner
        self.backend_port = backend_port
        self.transport = dict(transport or {})

    def command(self, argv, *, env=None, timeout=180, allow_failure=False):
        try:
            result = self.runner(argv, env=env or self.environment(), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeFailure('phone_command_timeout') from None
        if result.returncode and not allow_failure:
            diagnostic = 'consumer_failure'
            lower = result.stderr.lower()
            for kind, patterns in (
                ('access_denied', ('unauthorized', 'authentication required', 'permission denied', 'denied:')),
                ('capacity', ('no space left', 'out of memory')),
                ('platform', ('no matching manifest', 'exec format error')),
                ('missing_resource', ('not found', 'no such file')),
                ('daemon_unavailable', ('cannot connect to the docker daemon',)),
            ):
                if any(pattern in lower for pattern in patterns):
                    diagnostic = kind
                    break
            raise RuntimeFailure(f'phone_command_failed_{diagnostic}_exit_{result.returncode}')
        return result

    def environment(self, profile=None):
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'HOME': '/root', 'DOCKER_HOST': 'unix:///var/run/docker.sock'}
        # Fixture transport is explicit; the production CLI always owns the
        # guest-local daemon and inherits no ambient Compose/AWS/DB inputs.
        env.update(self.transport)
        env.update(ANSHIN_PHONE_SECRET_DIR=str(self.secrets),
                   ANSHIN_PHONE_BACKEND_PORT=str(self.backend_port))
        if profile:
            env['ANSHIN_PHONE_BACKEND_IMAGE'] = profile['backend_image']
        return env

    def compose(self, profile, *args, timeout=180, allow_failure=False):
        return self.command(['docker', 'compose', '--project-name', self.project,
            '--project-directory', profile['source_root'], '--env-file', '/dev/null',
            '--file', str(Path(profile['source_root']) / 'compose.production.yaml'), *args],
            env=self.environment(profile), timeout=timeout, allow_failure=allow_failure)

    @contextmanager
    def exclusive(self):
        descriptor = os.open(self.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeFailure('phone_release_busy') from None
            yield

    def profile(self):
        path = self.state / 'runtime.json'
        return json.loads(path.read_text()) if path.exists() else None

    def observation(self):
        """Read only identity/state fields; Docker inspect's Env stays private."""
        selector = f'label=com.docker.compose.project={self.project}'
        ids = self.command(['docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter', selector]).stdout.split()
        names = self.command(['docker', 'volume', 'ls', '--format', '{{.Name}}']).stdout.split()
        volumes = [name for name in names if name in {
            self.project + '_postgres-data', self.project + '_fax-protected-storage'}]
        containers = []
        for identifier in sorted(ids):
            projected = self.command(['docker', 'inspect', '--format',
                '{{json .Id}} {{json .Image}} {{json .State.StartedAt}} {{json .RestartCount}}', identifier]).stdout.strip()
            containers.append(projected)
        return {'containers': containers, 'volumes': sorted(volumes)}

    def health(self, profile):
        identifiers = self.compose(profile, 'ps', '--quiet', 'backend').stdout.split()
        if len(identifiers) != 1:
            raise RuntimeFailure('phone_backend_identity_missing')
        image = self.command(['docker', 'inspect', '--format', '{{.Config.Image}}', identifiers[0]]).stdout.strip()
        if image != profile['backend_image']:
            raise RuntimeFailure('phone_backend_image_mismatch')
        self.compose(profile, 'exec', '-T', 'backend', 'python', '-c', SETTINGS_CHECK, timeout=30)
        self.compose(profile, 'exec', '-T', 'backend', 'python', '-c',
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=5).read()", timeout=15)
        result = self.compose(profile, 'ps', '--format', 'json', 'backend', 'postgres')
        # Compose v2 versions emit a JSON array or one object per line.
        raw = result.stdout.strip()
        rows = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines()]
        if ({row.get('Service') for row in rows} != {'backend', 'postgres'} or
            any(row.get('State') != 'running' or row.get('Health') != 'healthy' for row in rows)):
            raise RuntimeFailure('phone_runtime_unhealthy')
        return {'status': 'healthy', 'backend_sha': profile['backend_sha'],
                'infra_sha': profile['infra_sha'], 'telephony_enabled': False}

    def stop_oneoff(self, suffix, service):
        name = self.project + '-' + suffix
        result = self.command(['docker', 'ps', '--all', '--quiet', '--filter', f'name=^/{name}$',
            '--filter', f'label=com.docker.compose.project={self.project}',
            '--filter', 'label=com.docker.compose.service=' + service])
        if result.stdout.strip():
            self.command(['docker', 'stop', '--time', '10', name], timeout=30)
            self.command(['docker', 'rm', name], timeout=30)

    def backup(self):
        # The existing shared producer takes the same guest lock. Run it
        # before acquiring that lock, then reobserve before any mutation.
        self.command(['python3', '/opt/anshin-phone-backup/scripts/phone_postgresql_backup_adapter.py',
                      '--scheduled-backup'], timeout=1200)

    def save(self, profile):
        self.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = self.state / 'runtime.json'
        temporary = self.state / 'runtime.json.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(profile, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)

    def deploy(self, image, backend_sha, infra_sha):
        if not IMAGE.fullmatch(image) or not SHA.fullmatch(backend_sha) or not SHA.fullmatch(infra_sha):
            raise RuntimeFailure('phone_release_input_invalid')
        candidate = {'source_root': str(self.root), 'backend_image': image,
                     'backend_sha': backend_sha, 'infra_sha': infra_sha}
        previous = self.profile()
        before = self.observation()
        if previous:
            self.health(previous)
            self.backup()
        elif before['containers'] or before['volumes']:
            raise RuntimeFailure('phone_existing_data_without_profile')
        with self.exclusive():
            if self.profile() != previous or self.observation() != before:
                raise RuntimeFailure('phone_runtime_changed_during_backup')
            # Validate the actual consumer settings before DB/container changes.
            self.compose(candidate, 'pull', 'postgres', 'backend', 'backend-migrate', timeout=600)
            revision = self.command(['docker', 'image', 'inspect', '--format',
                '{{index .Config.Labels "org.opencontainers.image.revision"}}', image]).stdout.strip()
            if revision != backend_sha:
                raise RuntimeFailure('phone_image_revision_mismatch')
            try:
                self.compose(candidate, 'run', '--rm', '--no-deps', '--name', self.project + '-settings',
                             '--entrypoint', 'python', 'backend', '-c', SETTINGS_CHECK, timeout=60)
            finally:
                self.stop_oneoff('settings', 'backend')
            try:
                self.compose(candidate, 'up', '--detach', '--wait', '--wait-timeout', '90', 'postgres')
                self.compose(candidate, 'run', '--rm', '--no-deps', '--name', self.project + '-migration',
                             'backend-migrate', timeout=180)
                self.compose(candidate, 'up', '--detach', '--no-deps', '--wait', '--wait-timeout', '90', 'backend')
                result = self.health(candidate)
                self.save(candidate)
                return {**result, 'status': 'deployed'}
            except (RuntimeFailure, OSError, ValueError, KeyError, KeyboardInterrupt):
                # A timed-out Compose CLI can leave its one-off migration alive.
                # Stop that owned process before attempting application rollback.
                self.stop_oneoff('migration', 'backend-migrate')
                if previous:
                    self.compose(previous, 'up', '--detach', '--no-deps', '--wait', '--wait-timeout', '90', 'backend')
                    self.health(previous)
                    return {'status': 'rolled_back', 'backend_sha': previous['backend_sha'],
                            'infra_sha': previous['infra_sha']}
                stopped = self.compose(candidate, 'stop', 'backend', allow_failure=True)
                if stopped.returncode:
                    raise RuntimeFailure('phone_initial_cleanup_unconfirmed') from None
                raise RuntimeFailure('phone_initial_deploy_failed_data_preserved') from None


def main():
    def terminate(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('deploy', 'health'))
    parser.add_argument('--backend-image')
    parser.add_argument('--backend-sha')
    parser.add_argument('--infra-sha')
    args = parser.parse_args()
    runtime = Runtime()
    try:
        if args.operation == 'deploy':
            result = runtime.deploy(args.backend_image or '', args.backend_sha or '', args.infra_sha or '')
        else:
            profile = runtime.profile()
            if not profile:
                raise RuntimeFailure('phone_runtime_not_installed')
            result = runtime.health(profile)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] in {'deployed', 'healthy'} else 1
    except (RuntimeFailure, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error) if isinstance(error, RuntimeFailure)
                          else 'phone_runtime_input_or_state_invalid'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
