#!/usr/bin/env python3
"""Supply Phone's actual runtime to the existing PostgreSQL backup owner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys

from production_runtime import Runtime, RuntimeFailure


INSTALL = Path('/opt/anshin-phone-backup')
CONFIG = Path('/etc/anshin-phone/postgresql-backup-profile.json')
KEYS = Path('/etc/anshin-phone/backup-keys')
STATE = Path('/var/lib/anshin-phone/postgresql-backup')
BUCKET = 'anshin-prod-phone-postgresql-backup-691862619128'
WRITER = 'arn:aws:iam::691862619128:role/anshin-prod-phone-postgresql-backup-writer'


def read_profile(path=CONFIG):
    with open(path, 'r', opener=lambda name, flags: os.open(name, flags | os.O_NOFOLLOW)) as source:
        metadata = os.fstat(source.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077 or metadata.st_size > 4096):
            raise RuntimeFailure('phone_backup_profile_permissions')
        profile = json.load(source)
    if (not isinstance(profile, dict) or set(profile) != {'manifest_key_id'}
            or not isinstance(profile['manifest_key_id'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', profile['manifest_key_id'])):
        raise RuntimeFailure('phone_backup_profile_invalid')
    return profile


def environment(runtime, installed, config, container_id):
    if not re.fullmatch(r'[0-9a-f]{64}', container_id):
        raise RuntimeFailure('phone_backup_database_identity_invalid')
    env = runtime.environment(installed)
    env.update(HOME='/var/empty', AWS_REGION='ap-northeast-1',
               AWS_SHARED_CREDENTIALS_FILE='/dev/null', AWS_EC2_METADATA_DISABLED='true',
               AWS_CONFIG_FILE='/etc/anshin-phone/aws/config', AWS_PROFILE='anshin-phone-backup-writer')
    values = {
        'COMPONENT': 'phone', 'COMPOSE_PROJECT': runtime.project, 'COMPOSE_SERVICE': 'postgres',
        'COMPOSE_FILE': str(Path(installed['source_root']) / 'compose.production.yaml'),
        'COMPOSE_ENV_FILE': '/dev/null', 'EXPECTED_CONTAINER_ID': container_id,
        'DATABASE': 'anshin_phone', 'DATABASE_USER': 'anshin_phone',
        'SOURCE_ID': 'ms-a2-2/phone-postgresql', 'SOURCE_FIXED_SHA': installed['backend_sha'],
        'S3_BUCKET': BUCKET, 'S3_PREFIX': 'postgresql/phone',
        'EXPECTED_BUCKET_OWNER': '691862619128', 'EXPECTED_ROLE_ARN': WRITER,
        'AGE_RECIPIENT_FILE': str(KEYS / 'phone-age-recipient.txt'),
        'MANIFEST_SIGNING_KEY_FILE': str(KEYS / 'phone-manifest-signing.pem'),
        'MANIFEST_VERIFY_KEY_FILE': str(KEYS / 'phone-manifest-verification.pem'),
        'MANIFEST_KEY_ID': config['manifest_key_id'], 'STATE_DIR': str(STATE), 'OBJECT_STORE_DRIVER': 's3',
    }
    env.update({'POSTGRES_BACKUP_' + key: value for key, value in values.items()})
    return env


def scheduled_backup(*, runtime=None, config_path=CONFIG, install=INSTALL):
    runtime = runtime or Runtime()
    config = read_profile(config_path)
    installed = runtime.profile()
    if not installed:
        raise RuntimeFailure('phone_backup_runtime_not_installed')
    runtime.health(installed)
    identifiers = runtime.compose(installed, 'ps', '--quiet', '--no-trunc', 'postgres').stdout.split()
    if len(identifiers) != 1:
        raise RuntimeFailure('phone_backup_database_identity_invalid')
    env = environment(runtime, installed, config, identifiers[0])
    # This is the sole producer: it owns locking, age, AES256, exact-version
    # readback and the existing receipt. Phone support (including identity
    # binding under that lock) must be integrated before installation.
    runtime.command(['bash', str(Path(install) / 'sh/backup_postgresql_to_s3.sh')],
                    env=env, timeout=1100)
    if runtime.profile() != installed:
        raise RuntimeFailure('phone_backup_runtime_changed')
    runtime.health(installed)
    return {'status': 'completed', 'source_fixed_sha': installed['backend_sha']}


def main():
    def terminate(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheduled-backup', action='store_true', required=True)
    parser.parse_args()
    try:
        print(json.dumps(scheduled_backup(), sort_keys=True))
        return 0
    except (RuntimeFailure, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error) if isinstance(error, RuntimeFailure)
                          else 'phone_backup_input_or_state_invalid'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
