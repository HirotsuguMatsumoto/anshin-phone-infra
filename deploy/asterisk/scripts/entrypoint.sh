#!/bin/sh
set -eu

python3 /opt/anshin-phone/render_config.py
mkdir -p /var/spool/asterisk/outgoing /var/spool/asterisk/fax /var/log/asterisk /var/run/asterisk
chown -R asterisk:asterisk \
  /etc/asterisk \
  /var/lib/asterisk \
  /var/log/asterisk \
  /var/run/asterisk \
  /var/spool/asterisk

if [ -n "${PBX_EVENT_BACKEND_URL:-}" ]; then
  python3 /var/lib/asterisk/agi-bin/pbx_management.py --poll &
  python3 /var/lib/asterisk/agi-bin/pbx_fax_worker.py --poll &
fi
exec "$@"
