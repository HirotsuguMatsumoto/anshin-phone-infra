#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compose="docker compose --file $repo_dir/compose.phase1.yaml"

echo 'Service status'
$compose ps

echo 'Asterisk core status'
$compose exec -T asterisk asterisk -rx 'core show uptime'

echo 'SIP endpoint status'
$compose exec -T asterisk asterisk -rx 'pjsip show endpoints'

echo 'Backend readiness'
$compose exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read().decode())"

echo 'PBX event spool counts'
$compose exec -T pbx-event-forwarder python -c "from pathlib import Path; root=Path('/var/spool/anshin-phone/events'); print('pending=' + str(len(list((root/'pending').glob('*.json'))))); print('dead_letter=' + str(len(list((root/'dead-letter').glob('*.json'))))); print('sent=' + str(len(list((root/'sent').glob('*.json')))))"
