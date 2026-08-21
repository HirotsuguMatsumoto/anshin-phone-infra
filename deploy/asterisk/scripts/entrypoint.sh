#!/bin/sh
set -eu

python3 /opt/anshin-phone/render_config.py
mkdir -p /var/spool/asterisk/fax /var/log/asterisk /var/run/asterisk
chown -R asterisk:asterisk \
  /etc/asterisk \
  /var/lib/asterisk \
  /var/log/asterisk \
  /var/run/asterisk \
  /var/spool/asterisk

exec "$@"
