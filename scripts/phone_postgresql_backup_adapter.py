#!/usr/bin/env python3
"""Supply the existing Phone backup and FAX retention owners with its runtime."""
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
        'CONTAINER_NAME': runtime.project + '-postgres-1', 'EXPECTED_CONTAINER_ID': container_id,
        'DATABASE': 'anshin_phone', 'DATABASE_USER': 'anshin_phone',
        'SOURCE_ID': 'ms-a2-1/phone-postgresql', 'SOURCE_FIXED_SHA': installed['backend_sha'],
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
    actual_name = runtime.command(['docker', 'inspect', '--format', '{{.Name}}', identifiers[0]]).stdout.strip()
    if actual_name != '/' + runtime.project + '-postgres-1':
        raise RuntimeFailure('phone_backup_database_name_mismatch')
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


def purge_expired(*, runtime=None):
    runtime = runtime or Runtime()
    with runtime.exclusive():
        installed = runtime.profile()
        if not installed:
            raise RuntimeFailure('phone_retention_runtime_not_installed')
        runtime.health(installed)
        name = runtime.project + '-fax-retention'
        # Runtime.exclusive checks unresolved retention absence before yielding.
        identifier = None
        owned = False
        children_unknown = False
        try:
            created = runtime.compose(installed, 'run', '--detach', '--no-deps',
                '--name', name, 'backend-retention', timeout=60).stdout.strip()
            if not re.fullmatch(r'[0-9a-f]{64}', created):
                raise RuntimeFailure('phone_retention_create_identity_unknown')
            identifier = created
            rows = json.loads(runtime.command(['docker', 'inspect', '--format',
                '[{{json .Id}},{{json .Name}},{{json .Config.Labels}},{{json .Config.Image}},{{json .Config.User}}]',
                identifier], timeout=10).stdout)
            if (not isinstance(rows, list) or len(rows) != 5
                    or rows[0] != identifier or rows[1] != '/' + name
                    or not isinstance(rows[2], dict)
                    or rows[2].get('com.docker.compose.project') != runtime.project
                    or rows[2].get('com.docker.compose.service') != 'backend-retention'
                    or rows[2].get('com.docker.compose.oneoff') != 'True'
                    or rows[3] != installed['backend_image'] or rows[4] != '10001:10001'):
                raise RuntimeFailure('phone_retention_oneoff_identity_mismatch')
            owned = True
            status = runtime.command(['docker', 'wait', identifier], timeout=180).stdout.strip()
            if status != '0':
                raise RuntimeFailure('phone_retention_consumer_failed')
            raw = runtime.command(['docker', 'logs', '--tail', '2', identifier], timeout=10).stdout
            if len(raw) > 8192:
                raise RuntimeFailure('phone_retention_consumer_result_invalid')
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {'status', 'purged_count'}
                    or value['status'] != 'ok' or type(value['purged_count']) is not int
                    or value['purged_count'] < 0):
                raise RuntimeFailure('phone_retention_consumer_result_invalid')
        except RuntimeFailure as error:
            children_unknown = str(error) == 'phone_command_children_unknown'
            raise
        finally:
            # Lost create response or unverified identity never adopts a name.
            if owned and identifier is not None and not children_unknown:
                runtime.stop_oneoff('fax-retention', 'backend-retention', expected_id=identifier)
        if runtime.profile() != installed:
            raise RuntimeFailure('phone_retention_runtime_changed')
        runtime.health(installed)
        return {'status': 'completed', 'purged_count': value['purged_count'],
                'source_fixed_sha': installed['backend_sha']}


def main():
    def terminate(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--scheduled-backup', action='store_true')
    modes.add_argument('--purge-expired', action='store_true')
    arguments = parser.parse_args()
    try:
        result = purge_expired() if arguments.purge_expired else scheduled_backup()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeFailure, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error) if isinstance(error, RuntimeFailure)
                          else 'phone_backup_input_or_state_invalid'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
