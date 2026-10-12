#!/bin/sh
set -eu
cp /mock-fax/pjsip.conf /etc/asterisk/pjsip.conf
cp /mock-fax/extensions.conf /etc/asterisk/extensions.conf
mkdir -p /var/run/asterisk /var/spool/asterisk/fax /var/log/asterisk
chown -R asterisk:asterisk /etc/asterisk /var/lib/asterisk /var/spool/asterisk /var/run/asterisk /var/log/asterisk
exec asterisk -f -vv
