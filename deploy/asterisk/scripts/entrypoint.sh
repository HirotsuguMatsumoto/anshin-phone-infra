#!/bin/sh
set -eu

python3 /opt/anshin-phone/render_config.py
mkdir -p /var/spool/asterisk/fax /var/log/asterisk /var/run/asterisk

exec "$@"
