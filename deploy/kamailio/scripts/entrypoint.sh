#!/bin/sh
set -eu

python3 /opt/anshin-phone/render_config.py
kamailio -c -f /tmp/kamailio.cfg
exec kamailio -DD -E -f /tmp/kamailio.cfg -m 64 -M 8
