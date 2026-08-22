#!/bin/sh
set -eu

: "${RTPENGINE_INTERNAL_IP:?set RTPENGINE_INTERNAL_IP}"
: "${RTPENGINE_EXTERNAL_IP:?set RTPENGINE_EXTERNAL_IP}"
: "${PUBLIC_RTP_IP:?set PUBLIC_RTP_IP}"

exec rtpengine \
  --foreground \
  --log-stderr \
  --table=-1 \
  --interface="internal/${RTPENGINE_INTERNAL_IP}" \
  --interface="external/${RTPENGINE_EXTERNAL_IP}!${PUBLIC_RTP_IP}" \
  --listen-ng="0.0.0.0:2223" \
  --port-min=20000 \
  --port-max=20100 \
  --delete-delay=0 \
  --timeout=60 \
  --silent-timeout=3600
