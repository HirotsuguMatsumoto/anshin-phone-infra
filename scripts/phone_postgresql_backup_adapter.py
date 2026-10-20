#!/usr/bin/env python3
"""Supply the existing Phone backup and FAX retention owners with its runtime."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import shutil

from production_runtime import Runtime, RuntimeFailure


INSTALL = Path('/opt/anshin-phone-backup')
CONFIG = Path('/etc/anshin-phone/postgresql-backup-profile.json')
KEYS = Path('/etc/anshin-phone/backup-keys')
STATE = Path('/var/lib/anshin-phone/postgresql-backup')
BUCKET = 'anshin-prod-phone-postgresql-backup-691862619128'
WRITER = 'arn:aws:iam::691862619128:role/anshin-prod-phone-postgresql-backup-writer'
FAX_BUCKET = 'anshin-prod-phone-fax-691862619128'
RESTORE_INPUT = Path('/run/anshin-phone-restore')
BACKUP_SERVICE = 'anshin-phone-postgresql-backup.service'
BACKUP_TIMER = 'anshin-phone-postgresql-backup.timer'
RETENTION_TIMER = 'anshin-phone-fax-retention.timer'
PRODUCER_KEYS = {'phone-db-writer-certificate.pem', 'phone-db-writer-private-key.pem',
    'phone-fax-writer-certificate.pem', 'phone-fax-writer-private-key.pem',
    'phone-age-recipient.txt', 'phone-manifest-signing.pem', 'phone-manifest-verification.pem'}
RESTORE_KEYS = {'phone-db-restore-certificate.pem', 'phone-db-restore-private-key.pem',
    'phone-fax-restore-certificate.pem', 'phone-fax-restore-private-key.pem',
    'phone-age-identity.txt', 'phone-fax-storage-key.hex'}

CREDENTIAL_IDS = {f'anshin.production.phone.{data}-backup-{purpose}-{kind}'
    for data in ('db','fax') for purpose in ('writer','restore') for kind in ('certificate','private-key')} | {
    'anshin.production.phone.backup-age-identity', 'anshin.production.phone.backup-manifest-signing-key',
    'anshin.production.phone.fax-storage-key'}


def backup_public(public):
    expected = {'trust_anchor_arn', 'manifest_key_id', 'credential_versions'}
    expected |= {purpose + '_' + role + '_' + kind + '_arn' for purpose in ('db', 'fax') for role in ('writer', 'restore') for kind in ('role', 'profile')}
    if not isinstance(public, dict) or set(public) != expected:
        raise RuntimeFailure('phone_backup_public_input_invalid')
    if public['trust_anchor_arn'] != 'arn:aws:rolesanywhere:ap-northeast-1:691862619128:trust-anchor/916219bc-2500-4f73-a7b2-82e0c94ec215':
        raise RuntimeFailure('phone_backup_trust_anchor_mismatch')
    for purpose, product in (('db', 'phone-postgresql'), ('fax', 'phone-fax')):
        for role in ('writer', 'restore'):
            if public[purpose + '_' + role + '_role_arn'] != 'arn:aws:iam::691862619128:role/anshin-prod-' + product + '-backup-' + role:
                raise RuntimeFailure('phone_backup_role_mismatch')
            if not re.fullmatch(r'arn:aws:rolesanywhere:ap-northeast-1:691862619128:profile/[0-9a-f-]{36}', public[purpose + '_' + role + '_profile_arn']):
                raise RuntimeFailure('phone_backup_profile_mismatch')
    if not re.fullmatch('[0-9a-f]{64}', public['manifest_key_id']):
        raise RuntimeFailure('phone_backup_manifest_key_invalid')
    versions = public['credential_versions']
    if (not isinstance(versions, dict) or set(versions) != CREDENTIAL_IDS
            or any(not k.startswith('anshin.production.phone.') or type(v) is not int or v < 1 for k, v in versions.items())):
        raise RuntimeFailure('phone_backup_numeric_versions_required')
    return public


def owned_directory(path):
    path = Path(path); path.mkdir(mode=0o700, parents=True, exist_ok=True)
    facts = path.lstat()
    if not stat.S_ISDIR(facts.st_mode) or facts.st_uid != os.geteuid() or stat.S_IMODE(facts.st_mode) != 0o700:
        raise RuntimeFailure('phone_backup_private_directory_invalid')
    return path


def write_private(path, body):
    path = Path(path)
    if path.exists() or path.is_symlink():
        with open(path, 'rb', opener=lambda name, flags: os.open(name, flags | os.O_NOFOLLOW)) as source:
            facts = os.fstat(source.fileno())
            if (not stat.S_ISREG(facts.st_mode) or facts.st_uid != os.geteuid() or stat.S_IMODE(facts.st_mode) != 0o600
                    or source.read() != body):
                raise RuntimeFailure('phone_backup_existing_input_changed')
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as target:
        target.write(body); target.flush(); os.fsync(target.fileno())


def aws_profiles(public):
    import shlex
    lines = []
    for purpose in ('db', 'fax'):
        for role in ('writer', 'restore'):
            root = KEYS if role == 'writer' else RESTORE_INPUT
            name = 'phone-' + purpose + '-' + role
            arguments = [str(INSTALL / 'tools/aws_signing_helper'), 'credential-process', '--certificate', str(root / (name + '-certificate.pem')),
                '--private-key', str(root / (name + '-private-key.pem')), '--trust-anchor-arn', public['trust_anchor_arn'],
                '--profile-arn', public[purpose + '_' + role + '_profile_arn'], '--role-arn', public[purpose + '_' + role + '_role_arn'], '--session-duration', '900']
            profile = 'anshin-phone-' + ('fax-' if purpose == 'fax' else '') + 'backup-' + role
            lines.extend(['[profile ' + profile + ']', 'region = ap-northeast-1', 'credential_process = ' + shlex.join(arguments), ''])
    return '\n'.join(lines).encode()


def install_backup(material, *, source_sha, infra_sha, runtime=None):
    import base64
    runtime = runtime or Runtime()
    public = backup_public(material['public'])
    if set(material['keys']) != PRODUCER_KEYS:
        raise RuntimeFailure('phone_backup_producer_keys_invalid')
    with runtime.exclusive():
        runtime.health(runtime.profile())
        for timer in (BACKUP_TIMER, RETENTION_TIMER):
            if runtime.command(['systemctl', 'is-enabled', timer], allow_failure=True, timeout=10).stdout.strip() == 'enabled':
                raise RuntimeFailure('phone_backup_existing_schedule_preserved')
        owned_directory(KEYS); owned_directory(STATE); owned_directory(STATE / 'isolation')
        for name, value in material['keys'].items():
            body = base64.b64decode(value, validate=True)
            if not body or len(body) > 16384:
                raise RuntimeFailure('phone_backup_key_size_invalid')
            write_private(KEYS / name, body)
        from postgresql_backup_manifest import public_der
        if hashlib.sha256(public_der(KEYS / 'phone-manifest-verification.pem')).hexdigest() != public['manifest_key_id']:
            raise RuntimeFailure('phone_backup_manifest_key_mismatch')
        config = {'manifest_key_id': public['manifest_key_id'], 'governance_sha': source_sha, 'infra_sha': infra_sha, 'public': public}
        write_private(CONFIG, (json.dumps(config, sort_keys=True) + '\n').encode())
        owned_directory(Path('/etc/anshin-phone/aws'))
        write_private(Path('/etc/anshin-phone/aws/config'), aws_profiles(public))
        for name in (BACKUP_SERVICE, BACKUP_TIMER, 'anshin-phone-fax-retention.service', RETENTION_TIMER):
            path = Path('/etc/systemd/system') / name
            source = (INSTALL / 'deploy/postgresql-backup' / name).read_bytes()
            if path.exists():
                if path.is_symlink() or path.read_bytes() != source:
                    raise RuntimeFailure('phone_backup_existing_unit_changed')
            else:
                with path.open('xb') as target:
                    os.fchmod(target.fileno(), 0o644); target.write(source)
        runtime.command(['systemctl', 'daemon-reload'], timeout=30)
    return {'status': 'installed', 'schedule_enabled': False, 'source_sha': source_sha, 'infra_sha': infra_sha}


def latest_backup():
    value = json.loads((STATE / 'latest-success.json').read_text())
    if value.get('status') != 'success' or value.get('schema_version') != 3 or value.get('bucket') != BUCKET or 'phone_schema' not in value:
        raise RuntimeFailure('phone_backup_generation_unavailable')
    return value


def restore_backup(material, *, runtime=None):
    import base64
    runtime = runtime or Runtime()
    installed = runtime.profile(); runtime.health(installed)
    config = read_profile()
    if backup_public(material['public']) != config['public'] or set(material['keys']) != RESTORE_KEYS:
        raise RuntimeFailure('phone_restore_material_binding_invalid')
    if RESTORE_INPUT.exists() or RESTORE_INPUT.is_symlink():
        raise RuntimeFailure('phone_restore_existing_input_preserved')
    RESTORE_INPUT.mkdir(mode=0o700)
    complete = False
    cleanup_confirmed = False
    started = False
    try:
        for name, value in material['keys'].items():
            write_private(RESTORE_INPUT / name, base64.b64decode(value, validate=True))
        verification = RESTORE_INPUT / 'phone-manifest-verification.pem'
        write_private(verification, (KEYS / verification.name).read_bytes())
        recipient = hashlib.sha256((KEYS / 'phone-age-recipient.txt').read_bytes()).hexdigest()
        until = '9999-12-31T23:59:59+00:00'  # retain while any corresponding backup is retained
        private_json(RESTORE_INPUT / 'manifest-registry.json', {'schema_version': 1, 'keys': {config['manifest_key_id']: {'path': str(verification), 'restore_until': until}}})
        private_json(RESTORE_INPUT / 'age-registry.json', {'schema_version': 1, 'identities': {recipient: {'path': str(RESTORE_INPUT / 'phone-age-identity.txt'), 'restore_until': until}}})
        backup = latest_backup()
        pg = runtime.compose(installed, 'ps', '--quiet', '--no-trunc', 'postgres').stdout.strip()
        pg_image = container(runtime, pg)[2]
        compose = INSTALL / 'deploy/postgresql-backup/restore-drill-compose.yml'
        receipt = STATE / ('restore-' + backup['artifact_sha256'] + '.json')
        if receipt.exists():
            raise RuntimeFailure('phone_restore_existing_result_preserved')
        assertion = """\\set QUIET 1
BEGIN READ ONLY;
\\set QUIET 0
WITH facts AS (SELECT (SELECT count(*) FROM pg_tables WHERE schemaname='public') AS tables,(SELECT version_num FROM alembic_version LIMIT 1) AS head,(SELECT count(*) FROM phone_numbers) AS count)
SELECT concat_ws(E'\\t',CASE WHEN current_database()='anshin_restore_drill' AND tables=:'expected_table_count'::bigint AND head=:'expected_migration_head' THEN 'ok' ELSE 'failed' END,tables,head,'public.phone_numbers',count,current_setting('transaction_read_only')='on') FROM facts;
\\set QUIET 1
ROLLBACK;
"""
        write_private(RESTORE_INPUT / 'assert.sql', assertion.encode())
        env = runtime.environment(installed)
        env.update(AWS_CONFIG_FILE='/etc/anshin-phone/aws/config', AWS_SHARED_CREDENTIALS_FILE='/dev/null', AWS_EC2_METADATA_DISABLED='true', AWS_REGION='ap-northeast-1', AWS_PROFILE='anshin-phone-backup-restore')
        values = {'COMPONENT': 'phone', 'MODE': 'isolated-drill', 'S3_BUCKET': BUCKET, 'S3_PREFIX': 'postgresql/phone',
            'MANIFEST_KEY': backup['manifest_key'], 'MANIFEST_VERSION_ID': backup['manifest_version_id'], 'MANIFEST_SHA256': backup['manifest_sha256'],
            'EXPECTED_SOURCE_FIXED_SHA': backup['source_fixed_sha'], 'EXPECTED_MIGRATION_HEAD': backup['phone_schema']['migration_head'],
            'EXPECTED_TABLE_COUNT': str(backup['phone_schema']['table_count']), 'EXPECTED_REPRESENTATIVE_TABLE': 'public.phone_numbers',
            'EXPECTED_BUCKET_OWNER': '691862619128', 'EXPECTED_ROLE_ARN': config['public']['db_restore_role_arn'],
            'MANIFEST_KEY_REGISTRY_FILE': str(RESTORE_INPUT / 'manifest-registry.json'), 'AGE_IDENTITY_REGISTRY_FILE': str(RESTORE_INPUT / 'age-registry.json'),
            'KEY_ROOT': str(RESTORE_INPUT), 'PHONE_FAX_KEY_FILE': str(RESTORE_INPUT / 'phone-fax-storage-key.hex'),
            'COMPOSE_FILE': str(compose), 'EXPECTED_COMPOSE_SHA256': hashlib.sha256(compose.read_bytes()).hexdigest(),
            'COMPOSE_PROJECT': 'anshin-phone-restore-drill-' + backup['artifact_sha256'][:16], 'POSTGRES_IMAGE': pg_image,
            'ISOLATION_ROOT': str(STATE / 'isolation'), 'DATABASE': 'anshin_restore_drill', 'DATABASE_USER': 'anshin_phone',
            'ASSERT_SQL_FILE': str(RESTORE_INPUT / 'assert.sql'), 'RECEIPT_FILE': str(receipt), 'OBJECT_STORE_DRIVER': 's3',
            'PRODUCTION_CONTAINER_NAME': runtime.project + '-postgres-1', 'EXPECTED_CONTAINER_ID': pg,
            'CONFIRM_TOKEN': 'restore-drill-' + backup['artifact_sha256'][:16]}
        env.update({'POSTGRES_RESTORE_' + k: v for k, v in values.items()})
        started = True
        runtime.command(['bash', str(INSTALL / 'sh/restore_postgresql_from_s3.sh')], env=env, timeout=1100, termination_grace=240)
        value = json.loads(receipt.read_text())
        if value.get('status') != 'success' or value.get('manifest_version_id') != backup['manifest_version_id']:
            raise RuntimeFailure('phone_restore_result_invalid')
        runtime.health(installed)
        complete = True
        return {'status': 'restored', 'restore_receipt': str(receipt), 'assertion': value['assertion']}
    except BaseException as error:
        if started and str(error) != 'phone_command_children_unknown':
            try:
                # The shared restore owner has already run its existing EXIT cleanup.
                project = 'anshin-phone-restore-drill-' + backup['artifact_sha256'][:16]
                remaining = runtime.command(['docker', 'ps', '--all', '--quiet', '--no-trunc',
                    '--filter', 'label=com.docker.compose.project='+project], timeout=10).stdout.strip()
                reader = runtime.command(['docker', 'ps', '--all', '--quiet', '--no-trunc',
                    '--filter', 'name=^/'+runtime.project+'-backup-reader$'], timeout=10).stdout.strip()
                cleanup_confirmed = (not remaining and not reader
                    and not os.path.lexists(str(receipt)+'.attention-required')
                    and not os.path.lexists(STATE/'isolation'/project))
            except Exception:
                cleanup_confirmed = False
        if started and not cleanup_confirmed and str(error) != 'phone_command_children_unknown':
            raise RuntimeFailure('phone_restore_cleanup_unconfirmed') from None
        raise
    finally:
        # Unknown native actors keep the exact inputs for the existing recovery owner.
        if complete or not started or cleanup_confirmed:
            shutil.rmtree(RESTORE_INPUT)


def backup_status(*, runtime=None):
    runtime = runtime or Runtime()
    return {'status': 'observed', 'latest_backup': latest_backup(), 'timers': {
        name: runtime.command(['systemctl', 'show', name, '--property=ActiveState,UnitFileState,NextElapseUSecRealtime'], timeout=10).stdout.strip()
        for name in (BACKUP_TIMER, RETENTION_TIMER)}}


def activate_backup(*, runtime=None):
    runtime = runtime or Runtime()
    timers = (BACKUP_TIMER, RETENTION_TIMER)
    changed = False
    with runtime.exclusive():
        enabled = [runtime.command(['systemctl', 'is-enabled', name], allow_failure=True, timeout=10).stdout.strip() == 'enabled' for name in timers]
        if any(enabled) and not all(enabled):
            raise RuntimeFailure('phone_backup_partial_schedule_preserved')
        if all(enabled):
            return backup_status(runtime=runtime)
        backup = latest_backup()
        receipt = json.loads((STATE / ('restore-' + backup['artifact_sha256'] + '.json')).read_text())
        if (receipt.get('status') != 'success' or any(receipt.get(k) != backup[k] for k in
                ('artifact_version_id', 'artifact_sha256', 'manifest_version_id', 'manifest_sha256'))):
            raise RuntimeFailure('phone_backup_same_generation_restore_required')
        runtime.health(runtime.profile())
        runtime.command(['systemctl', 'enable', *timers], timeout=30)
        changed = True
    # A Persistent timer may immediately start its producer; release the producer lock first.
    try:
        runtime.command(['systemctl', 'start', *timers], timeout=30)
        for name in timers:
            if runtime.command(['systemctl', 'is-active', name], allow_failure=True, timeout=10).stdout.strip() != 'active':
                raise RuntimeFailure('phone_backup_timer_not_active')
    except BaseException:
        if changed:
            runtime.command(['systemctl', 'disable', '--now', *timers], timeout=30)
        raise
    return backup_status(runtime=runtime)


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as target:
        json.dump(value, target, sort_keys=True)


def capture_directory(path, runtime):
    path = Path(path)
    metadata = path.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or not path.name.startswith('.capture-') or path.parent != STATE):
        raise RuntimeFailure('phone_capture_directory_invalid')
    # The shared producer owns fd9 and this guest lock; never acquire it again.
    descriptor = os.fstat(9)
    lock = runtime.lock.stat(follow_symlinks=False)
    if (descriptor.st_dev, descriptor.st_ino) != (lock.st_dev, lock.st_ino):
        raise RuntimeFailure('phone_capture_lock_missing')
    return path


def container(runtime, identifier):
    raw = runtime.command(['docker', 'inspect', '--format',
        '[{{json .Id}},{{json .Name}},{{json .Config.Image}},{{json .Config.Labels}},{{json .State.Running}}]', identifier], timeout=10).stdout
    row = json.loads(raw)
    if len(row) != 5 or row[0] != identifier or not re.fullmatch('[0-9a-f]{64}', identifier):
        raise RuntimeFailure('phone_capture_container_identity_changed')
    return row


def helper_create(runtime, profile, kind, image, arguments, command=()):
    name = runtime.project + '-backup-' + kind
    current = runtime.command(['docker', 'ps', '--all', '--quiet', '--no-trunc',
        '--filter', 'name=^/' + name + '$'], timeout=10).stdout.strip()
    if current:
        raise RuntimeFailure('phone_capture_existing_helper_preserved')
    labels = {'com.docker.compose.project': runtime.project,
              'com.docker.compose.service': 'backup-' + kind, 'com.docker.compose.oneoff': 'True'}
    argv = ['docker', 'create', '--name', name, '--log-driver', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64']
    for key, value in labels.items():
        argv.extend(('--label', key + '=' + value))
    try:
        identifier = runtime.command([*argv, *arguments, image, *command], timeout=30).stdout.strip()
    except BaseException:
        raise RuntimeFailure('phone_capture_helper_creation_unknown') from None
    if not re.fullmatch('[0-9a-f]{64}', identifier):
        raise RuntimeFailure('phone_capture_helper_creation_unknown')
    try:
        row = container(runtime, identifier)
    except BaseException:
        raise RuntimeFailure('phone_capture_helper_creation_unknown') from None
    if row[1] != '/' + name or row[2] != image or not isinstance(row[3], dict) or any(row[3].get(k) != v for k, v in labels.items()) or row[4]:
        raise RuntimeFailure('phone_capture_helper_creation_unknown')
    return identifier


def capture_pair(work, artifact, recipient, *, runtime=None):
    """The existing shared lock encloses a stopped-writer DB/FAX snapshot."""
    from business_file_backup import DigestReader, capture_archive, verify_archive, MAX_FILES, MAX_BYTES
    runtime = runtime or Runtime()
    work = capture_directory(work, runtime)
    artifact, recipient = Path(artifact), Path(recipient)
    if artifact.parent != work or recipient != KEYS / 'phone-age-recipient.txt':
        raise RuntimeFailure('phone_capture_paths_invalid')
    profile = runtime.profile()
    runtime.health(profile)
    runtime.require_retention_absent()
    for kind in ('dump', 'fax', 'reader'):
        if runtime.command(['docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter',
                'name=^/' + runtime.project + '-backup-' + kind + '$'], timeout=10).stdout.strip():
            raise RuntimeFailure('phone_capture_existing_helper_preserved')
    backend = runtime.compose(profile, 'ps', '--quiet', '--no-trunc', 'backend').stdout.strip()
    pg = runtime.compose(profile, 'ps', '--quiet', '--no-trunc', 'postgres').stdout.strip()
    if pg != os.environ.get('POSTGRES_BACKUP_EXPECTED_CONTAINER_ID'):
        raise RuntimeFailure('phone_capture_database_identity_changed')
    backend_row = container(runtime, backend)
    if (backend_row[1] != '/' + runtime.project + '-backend-1' or backend_row[2] != profile['backend_image']
            or backend_row[3].get('com.docker.compose.service') != 'backend' or not backend_row[4]):
        raise RuntimeFailure('phone_capture_backend_identity_changed')
    before = runtime.observation()['volumes']
    expected_volumes = {runtime.project + '_postgres-data', runtime.project + '_fax-protected-storage'}
    if {v['Name'] for v in before} != expected_volumes:
        raise RuntimeFailure('phone_capture_volume_identity_changed')
    backend_mounts = json.loads(runtime.command(['docker', 'inspect', '--format', '{{json .Mounts}}', backend], timeout=10).stdout)
    if not any(m.get('Name') == runtime.project + '_fax-protected-storage' and m.get('Destination') == '/var/lib/anshin-phone/fax' for m in backend_mounts):
        raise RuntimeFailure('phone_capture_fax_mount_changed')
    pg_image = container(runtime, pg)[2]
    helpers = []
    stop_attempted = False
    stop_confirmed = False
    unknown = False
    started = time.monotonic()
    def interrupt(_number, _frame):
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(number, signal.SIG_IGN)
        raise KeyboardInterrupt
    previous = {n: signal.signal(n, interrupt) for n in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        stop_attempted = True
        runtime.command(['docker', 'stop', '--time', '30', backend], timeout=45)
        if container(runtime, backend) != [*backend_row[:4], False]:
            raise RuntimeFailure('phone_capture_backend_not_stopped')
        stop_confirmed = True
        # Native pg_dump and archive validator share one tracked container.
        dump_program = '''set -euo pipefail
export PGPASSWORD="$(cat /run/secrets/postgres_password)"
client=(psql -XAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U anshin_phone -d anshin_phone)
# A late COMMIT must finish before cutoff; all clients belong to this known helper.
[[ "$("${client[@]}" -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'")" == 0 ]]
"${client[@]}" > /capture/metadata.json <<'PHONE_SNAPSHOT_SQL'
WITH c AS MATERIALIZED (SELECT clock_timestamp() AS cutoff) SELECT json_build_object('cutoff',to_char(c.cutoff AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'documents',(SELECT coalesce(json_agg(row_to_json(d)),'[]'::json) FROM (SELECT id,tenant_id,content_type,page_count,byte_count,created_at,expires_at,purged_at FROM fax_documents WHERE expires_at>c.cutoff ORDER BY id LIMIT 10001) d),'history_counts',json_build_object('fax_documents',(SELECT count(*) FROM fax_documents),'fax_records',(SELECT count(*) FROM fax_records),'fax_jobs',(SELECT count(*) FROM fax_jobs),'audit_logs',(SELECT count(*) FROM audit_logs)),'migration_head',(SELECT version_num FROM alembic_version LIMIT 1),'table_count',(SELECT count(*) FROM pg_tables WHERE schemaname='public')) FROM c;
PHONE_SNAPSHOT_SQL
mkfifo /tmp/validation
pg_restore --list </tmp/validation >/dev/null & validator=$!
trap 'kill "$validator" 2>/dev/null || true; wait "$validator" 2>/dev/null || true' EXIT
pg_dump -h 127.0.0.1 -U anshin_phone -d anshin_phone -Fc --no-owner --no-privileges --lock-wait-timeout=5s | tee --output-error=exit-nopipe /tmp/validation
wait "$validator"
trap - EXIT
'''
        (work / 'dump.sh').write_text(dump_program); (work / 'dump.sh').chmod(0o600)
        (work / 'capture-output').mkdir(mode=0o700)
        arguments = ['--network', 'container:' + pg, '--tmpfs', '/tmp:rw,mode=1777',
            '--mount', 'type=bind,src=' + str(runtime.secrets / 'postgres_password') + ',dst=/run/secrets/postgres_password,readonly',
            '--mount', 'type=bind,src=' + str(work / 'dump.sh') + ',dst=/dump.sh,readonly',
            '--mount', 'type=bind,src=' + str(work / 'capture-output') + ',dst=/capture', '--entrypoint', 'bash']
        identifier = helper_create(runtime, profile, 'dump', pg_image, arguments, ('/dump.sh',))
        helpers.append(('dump', identifier))
        try:
            result = runtime.runner(['bash', '-c', 'set -o pipefail; docker start --attach "$1" | age --encrypt --recipients-file "$2" --output "$3"',
                'phone-dump', identifier, str(recipient), str(artifact)], env=runtime.environment(profile),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300, termination_grace=120)
        except subprocess.TimeoutExpired:
            raise RuntimeFailure('phone_capture_dump_timeout') from None
        if result.returncode or runtime.command(['docker', 'wait', identifier], timeout=10).stdout.strip() != '0':
            raise RuntimeFailure('phone_capture_dump_failed')
        artifact.chmod(0o600)
        facts = json.loads((work / 'capture-output/metadata.json').read_text())
        cutoff, documents, histories = facts['cutoff'], facts['documents'], facts['history_counts']
        if len(documents) > MAX_FILES:
            raise RuntimeFailure('phone_capture_document_limit')
        required = {d['id'] + '.encrypted' for d in documents}
        source = ('import os,stat,tarfile,hashlib,json,io,sys\nfrom pathlib import Path\n'
                  + f'MAX_FILES={MAX_FILES}\nMAX_BYTES={MAX_BYTES}\n'
                  + inspect.getsource(DigestReader) + inspect.getsource(capture_archive)
                  + "capture_archive(None,None,'/protected',sys.stdout.buffer)\n")
        (work / 'capture.py').write_text(source); (work / 'capture.py').chmod(0o644)
        arguments = ['--network', 'none', '--user', '10001:10001',
            '--mount', 'type=volume,src=' + runtime.project + '_fax-protected-storage,dst=/protected,readonly',
            '--mount', 'type=bind,src=' + str(work / 'capture.py') + ',dst=/capture.py,readonly',
            '--entrypoint', 'python']
        identifier = helper_create(runtime, profile, 'fax', profile['backend_image'], arguments, ('/capture.py',))
        helpers.append(('fax', identifier))
        with (work / 'phone-fax.tar.gz').open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            result = runtime.runner(['docker', 'start', '--attach', identifier], env=runtime.environment(profile),
                stdout=output, stderr=subprocess.PIPE, timeout=300, termination_grace=120)
        if result.returncode or runtime.command(['docker', 'wait', identifier], timeout=10).stdout.strip() != '0':
            raise RuntimeFailure('phone_capture_fax_failed')
        observed = verify_archive(work / 'phone-fax.tar.gz', work / 'fax-check')
        rows = json.loads((work / 'fax-check/manifest.json').read_text())['files']
        if any(not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\.encrypted', r['key']) for r in rows):
            raise RuntimeFailure('phone_capture_original_name_invalid')
        if required - {row['key'] for row in rows}:
            raise RuntimeFailure('phone_capture_active_original_missing')
        shutil.rmtree(work / 'fax-check')
        key = (runtime.secrets / 'fax_storage_key').read_text().strip()
        if not re.fullmatch('[a-fA-F0-9]{64}', key):
            raise RuntimeFailure('phone_capture_key_invalid')
        private_json(work / 'phone-fax-capture.json', {'cutoff': cutoff, 'key_sha256': hashlib.sha256(bytes.fromhex(key)).hexdigest(),
            'backend_image': profile['backend_image'], 'infra_sha': profile['infra_sha'], 'source_sha': profile['backend_sha'], 'history_counts': histories, 'migration_head': facts['migration_head'], 'table_count': facts['table_count'], 'observed': observed})
    except RuntimeFailure as error:
        unknown = str(error) in {'phone_capture_helper_creation_unknown', 'phone_command_children_unknown', 'phone_capture_existing_helper_preserved'}
        raise
    finally:
        try:
            for kind, identifier in reversed(helpers):
                try:
                    runtime.stop_oneoff('backup-' + kind, 'backup-' + kind, expected_id=identifier, timeout=30)
                except BaseException:
                    unknown = True
            if stop_attempted and not stop_confirmed:
                unknown = True
            if stop_confirmed and not unknown:
                current = container(runtime, backend)
                if current[:4] != backend_row[:4] or runtime.observation(timeout=15)['volumes'] != before:
                    raise RuntimeFailure('phone_capture_runtime_changed_data_preserved')
                if not current[4]:
                    runtime.command(['docker', 'start', backend], timeout=15)
                deadline = time.monotonic() + 30
                while True:
                    try:
                        runtime.health(profile, timeout=max(0.01, deadline - time.monotonic()))
                        break
                    except RuntimeFailure:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(1)
            if unknown:
                raise RuntimeFailure('phone_capture_native_outcome_unknown_data_preserved')
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
    return {'status': 'captured', 'write_pause_seconds': round(time.monotonic() - started, 3)}


def upload_fax(work, *, runtime=None):
    from business_file_backup import upload_generation
    runtime = runtime or Runtime()
    work = capture_directory(work, runtime)
    capture = json.loads((work / 'phone-fax-capture.json').read_text())
    config = {'service': 'phone-fax', 'account': '691862619128', 'region': 'ap-northeast-1',
              'bucket': FAX_BUCKET, 'source_sha': capture['source_sha']}
    archive = work / 'phone-fax.tar.gz'
    record = upload_generation(config, archive, image=capture['backend_image'], observed=capture['observed'])
    generation = {k: capture[k] for k in ('cutoff', 'key_sha256', 'backend_image', 'infra_sha', 'history_counts', 'migration_head', 'table_count')}
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    generation.update(bucket=FAX_BUCKET, region='ap-northeast-1', key=record['key'], version_id=record['version_id'],
        checksum_sha256=record['checksum_sha256'], artifact_sha256=digest,
        artifact_size=archive.stat().st_size, retention_until=record['retention_until'], files=record['hashes_verified'], bytes=record['bytes'])
    private_json(work / 'phone-fax-generation.json', generation)
    return {'status': 'uploaded'}


READER = '''import json,hashlib
from datetime import datetime,timezone,timedelta
from pathlib import Path
from sqlalchemy import select,text
from fastapi import HTTPException
from cryptography.exceptions import InvalidTag
from app.core.database import SessionLocal
from app.core import fax_storage
from app.models.telephony import FaxDocument
generation=json.loads(Path('/reader/generation.json').read_text())
assert hashlib.sha256(bytes.fromhex(Path('/reader/fax-key').read_text().strip())).hexdigest()==generation['key_sha256']
active=expired=0
with SessionLocal() as db:
 db.execute(text('SET TRANSACTION READ ONLY'))
 for name,count in generation['history_counts'].items():
  assert name in {'fax_documents','fax_records','fax_jobs','audit_logs'}
  assert db.execute(text('SELECT count(*) FROM '+name)).scalar_one()==count
 rows=db.scalars(select(FaxDocument).where(FaxDocument.expires_at>datetime.fromisoformat(generation['cutoff'].replace('Z','+00:00'))).order_by(FaxDocument.id).limit(10001)).all()
 assert len(rows)<=10000
 for row in rows:
  try:
   doc,content=fax_storage.read(db,row.tenant_id,row.id)
   assert len(content)==doc.byte_count
   fax_storage.validate_document(content,doc.content_type)
   assert doc.expires_at.replace(tzinfo=timezone.utc)>datetime.now(timezone.utc)
   try:fax_storage.decrypt(fax_storage.storage_path(doc.id).read_bytes(),doc.tenant_id+'-wrong-tenant')
   except InvalidTag:pass
   else:raise RuntimeError('AAD boundary failed')
   active+=1
  except HTTPException as error:
   assert error.status_code==410 and row.expires_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc)
   expired+=1
  try:fax_storage.read(db,row.tenant_id+'-wrong-tenant',row.id)
  except HTTPException as error:assert error.status_code==404
  else:raise RuntimeError('tenant boundary failed')
 for row in db.scalars(select(FaxDocument).where(FaxDocument.expires_at<=datetime.now(timezone.utc)).limit(1)):
  try:fax_storage.read(db,row.tenant_id,row.id)
  except HTTPException as error:assert error.status_code==410
  else:raise RuntimeError('restored expiry boundary failed')
 db.rollback()
# Also verify the recovered key and actual expiry reader when the source is empty.
value=fax_storage.encrypt(b'isolated-key-and-AAD-probe','isolated-tenant')
assert fax_storage.decrypt(value,'isolated-tenant')==b'isolated-key-and-AAD-probe'
try:fax_storage.decrypt(value,'other-tenant')
except InvalidTag:pass
else:raise RuntimeError('AAD boundary failed')
class Expired:
 def get(self,*args):return FaxDocument(id='00000000-0000-4000-8000-000000000000',tenant_id='isolated-tenant',expires_at=datetime.now(timezone.utc)-timedelta(days=1))
try:fax_storage.read(Expired(),'isolated-tenant','00000000-0000-4000-8000-000000000000')
except HTTPException as error:assert error.status_code==410
else:raise RuntimeError('expiry boundary failed')
print(json.dumps({'status':'ok','active_originals':active,'expired_originals':expired,'recovered_key_probe':True,'tenant_AAD':True,'expired_410':True}))
'''


def verify_restored_fax(manifest, work, pg, *, runtime=None):
    from business_file_backup import download_generation, verify_archive
    runtime = runtime or Runtime()
    generation = json.loads(Path(manifest).read_text())['payload']['fax']
    work = Path(work)
    # Shared restore has already verified this manifest's signature/binding.
    config = {'service': 'phone-fax', 'account': '691862619128', 'region': 'ap-northeast-1', 'bucket': FAX_BUCKET}
    key_path = Path(os.environ['POSTGRES_RESTORE_PHONE_FAX_KEY_FILE'])
    facts = key_path.lstat()
    if (not stat.S_ISREG(facts.st_mode) or facts.st_uid != os.geteuid() or facts.st_mode & 0o077
            or key_path.parent != Path(os.environ['POSTGRES_RESTORE_KEY_ROOT'])):
        raise RuntimeFailure('phone_restore_key_input_invalid')
    key = key_path.read_text().strip()
    if not re.fullmatch('[a-f0-9]{64}', key) or hashlib.sha256(bytes.fromhex(key)).hexdigest() != generation['key_sha256']:
        raise RuntimeFailure('phone_restore_key_mismatch')
    archive = work / 'phone-fax.tar.gz'
    download_generation(config, generation, archive)
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256')
    import base64
    if (archive.stat().st_size != generation['artifact_size'] or digest.hexdigest() != generation['artifact_sha256']
            or base64.b64encode(digest.digest()).decode() != generation['checksum_sha256']):
        raise RuntimeFailure('phone_restore_fax_checksum_mismatch')
    observed = verify_archive(archive, work / 'fax-verified')
    if observed['hashes_verified'] != generation['files'] or observed['bytes'] != generation['bytes'] or observed['s3_files']:
        raise RuntimeFailure('phone_restore_fax_inventory_mismatch')
    restored = work / 'restored-fax'; restored.mkdir(mode=0o755); restored.chmod(0o755)
    rows = json.loads((work / 'fax-verified/manifest.json').read_text())['files']
    names = set()
    for row in rows:
        name = row['key']
        if not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\.encrypted', name) or name in names:
            raise RuntimeFailure('phone_restore_fax_name_invalid')
        names.add(name)
        target = restored / name
        os.link(work / 'fax-verified' / row['entry'], target, follow_symlinks=False)
        os.chown(target, 10001, 10001); target.chmod(0o400)
    inputs = work / 'reader-inputs'; inputs.mkdir(mode=0o700)
    # As in the existing Phone runtime: readonly file mounts inside a 0700
    # host directory make the non-root consumer's required inputs readable.
    for name, body in [('reader.py', READER), ('fax-key', key), ('generation.json', json.dumps(generation)),
                       ('restore-password', Path(os.environ['POSTGRES_RESTORE_PASSWORD_FILE']).read_text())]:
        (inputs / name).write_text(body); (inputs / name).chmod(0o444)
    args = ['--network', 'container:' + pg, '--user', '10001:10001',
        '--mount', 'type=bind,src=' + str(restored) + ',dst=/restored-fax,readonly',
        '--mount', 'type=bind,src=' + str(inputs) + ',dst=/reader,readonly',
        '--entrypoint', 'python']
    # The directory itself must be searchable by the mounted UID.
    inputs.chmod(0o755)
    for name, value in {'ANSHIN_PHONE_ENVIRONMENT': 'production', 'ANSHIN_PHONE_TELEPHONY_ENABLED': 'false',
            'ANSHIN_PHONE_FAX_RETENTION_POLICY': 'cloco_previous_month', 'ANSHIN_PHONE_FAX_STORAGE_DIR': '/restored-fax',
            'ANSHIN_PHONE_FAX_STORAGE_KEY_FILE': '/reader/fax-key', 'ANSHIN_PHONE_INTERNAL_TOKEN': 'isolated-reader-only',
            'ANSHIN_PHONE_DB_PASSWORD_FILE': '/reader/restore-password', 'ANSHIN_PHONE_DB_HOST': '127.0.0.1',
            'ANSHIN_PHONE_DB_NAME': 'anshin_restore_drill'}.items():
        args.extend(('--env', name + '=' + value))
    identifier = helper_create(runtime, None, 'reader', generation['backend_image'], args, ('/reader/reader.py',))
    return run_restored_reader(runtime, identifier)


def run_restored_reader(runtime, identifier):
    unknown = False
    try:
        result = runtime.command(['docker', 'start', '--attach', identifier], timeout=180, termination_grace=120)
        if runtime.command(['docker', 'wait', identifier], timeout=10).stdout.strip() != '0':
            raise RuntimeFailure('phone_restore_reader_failed')
        value = json.loads(result.stdout)
        if value.get('status') != 'ok' or not all(value.get(k) is True for k in ('recovered_key_probe', 'tenant_AAD', 'expired_410')):
            raise RuntimeFailure('phone_restore_reader_result_invalid')
    except RuntimeFailure as error:
        unknown = str(error) == 'phone_command_children_unknown'
        raise
    finally:
        if not unknown:
            try:
                runtime.stop_oneoff('backup-reader', 'backup-reader', expected_id=identifier, timeout=30)
            except BaseException:
                raise RuntimeFailure('phone_restore_reader_cleanup_unconfirmed') from None
    return value


def read_profile(path=CONFIG):
    with open(path, 'r', opener=lambda name, flags: os.open(name, flags | os.O_NOFOLLOW)) as source:
        metadata = os.fstat(source.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077 or metadata.st_size > 8192):
            raise RuntimeFailure('phone_backup_profile_permissions')
        profile = json.load(source)
    if (not isinstance(profile, dict) or set(profile) != {'manifest_key_id', 'governance_sha', 'infra_sha', 'public'}
            or not isinstance(profile['manifest_key_id'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', profile['manifest_key_id'])):
        raise RuntimeFailure('phone_backup_profile_invalid')
    if any(not isinstance(profile[key], str) or not re.fullmatch('[0-9a-f]{40}', profile[key])
           for key in ('governance_sha', 'infra_sha')) or backup_public(profile['public'])['manifest_key_id'] != profile['manifest_key_id']:
        raise RuntimeFailure('phone_backup_profile_binding_invalid')
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
                    env=env, timeout=1100, termination_grace=240)
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
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): signal.signal(number, signal.SIG_IGN)
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--scheduled-backup', action='store_true')
    modes.add_argument('--purge-expired', action='store_true')
    modes.add_argument('--capture-pair', nargs=3, metavar=('WORK', 'ARTIFACT', 'RECIPIENT'))
    modes.add_argument('--upload-fax', type=Path)
    modes.add_argument('--verify-restored-fax', nargs=3, metavar=('MANIFEST', 'WORK', 'POSTGRES_ID'))
    arguments = parser.parse_args()
    try:
        if arguments.capture_pair:
            result = capture_pair(*arguments.capture_pair)
        elif arguments.upload_fax:
            result = upload_fax(arguments.upload_fax)
        elif arguments.verify_restored_fax:
            result = verify_restored_fax(*arguments.verify_restored_fax)
        else:
            result = purge_expired() if arguments.purge_expired else scheduled_backup()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeFailure, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error) if isinstance(error, RuntimeFailure)
                          else 'phone_backup_input_or_state_invalid'}))
        if arguments.verify_restored_fax and isinstance(error, RuntimeFailure) and str(error) in {
                'phone_command_children_unknown', 'phone_capture_helper_creation_unknown',
                'phone_restore_reader_cleanup_unconfirmed'}:
            return 76  # Existing shared cleanup preserves actors/work and writes its attention marker.
        return 1


if __name__ == '__main__':
    sys.exit(main())
