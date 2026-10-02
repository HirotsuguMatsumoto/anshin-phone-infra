#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
validation_root=$(mktemp -d "${TMPDIR:-/tmp}/anshin-phone-phase1-validation.XXXXXX")
trap 'rm -rf -- "$validation_root"' EXIT
mkdir -p "$validation_root/secrets"
export PYTHONPYCACHEPREFIX="$validation_root/pycache"

if [ -n "${ANSHIN_PHONE_BACKEND_DIR:-}" ]; then
  ANSHIN_PHONE_BACKEND_DIR=$(python3 "$repo_dir/scripts/resolve_phone_backend.py" \
    --infra-root "$repo_dir" \
    --override "$ANSHIN_PHONE_BACKEND_DIR")
else
  ANSHIN_PHONE_BACKEND_DIR=$(python3 "$repo_dir/scripts/resolve_phone_backend.py" \
    --infra-root "$repo_dir")
fi
export ANSHIN_PHONE_BACKEND_DIR

required_files='compose.phase1.yaml
compose.phase1.resources.experimental.yaml
deploy/asterisk/Dockerfile
deploy/asterisk/config/pjsip.conf.template
deploy/asterisk/config/extensions.conf.template
deploy/asterisk/scripts/render_config.py
deploy/asterisk/scripts/entrypoint.sh
deploy/kamailio/Dockerfile
deploy/kamailio/config/kamailio.cfg.template
deploy/kamailio/scripts/render_config.py
deploy/kamailio/scripts/entrypoint.sh
deploy/rtpengine/Dockerfile
deploy/rtpengine/scripts/entrypoint.sh
scripts/test_phase1_render_config.py
scripts/test_phase1_resource_profile.py
scripts/test_kamailio_render_config.py
scripts/test_device_and_voice_tools.py
scripts/test_carrier_and_firewall_tools.py'

printf '%s\n' "$required_files" | while IFS= read -r item; do
  test -f "$repo_dir/$item" || {
    echo "missing required file: $item" >&2
    exit 1
  }
done

python3 -m py_compile "$repo_dir/deploy/asterisk/scripts/render_config.py"
python3 -m py_compile "$repo_dir/deploy/asterisk/scripts/pbx_event_spool.py"
python3 -m py_compile "$repo_dir/deploy/pbx-event-forwarder/forwarder.py"
python3 -m py_compile "$repo_dir/deploy/pbx-event-forwarder/healthcheck.py"
python3 -m py_compile "$repo_dir/deploy/kamailio/scripts/render_config.py"
sh -n "$repo_dir/deploy/kamailio/scripts/entrypoint.sh"
sh -n "$repo_dir/deploy/rtpengine/scripts/entrypoint.sh"
sh -n "$repo_dir/scripts/phase1_status.sh"
sh -n "$repo_dir/scripts/audit_phase1_host.sh"
python3 "$repo_dir/scripts/test_phase1_render_config.py"
python3 "$repo_dir/scripts/test_phase1_resource_profile.py"
python3 "$repo_dir/scripts/test_kamailio_render_config.py"
python3 "$repo_dir/scripts/test_pbx_event_pipeline.py"
python3 "$repo_dir/scripts/test_device_and_voice_tools.py"
python3 "$repo_dir/scripts/test_carrier_and_firewall_tools.py"
python3 "$repo_dir/scripts/test_phase1_sip_e2e_cleanup.py"
python3 "$repo_dir/scripts/test_resolve_phone_backend.py"
python3 -m py_compile "$repo_dir/scripts/create_sip_enrollment_bundle.py"
python3 -m py_compile "$repo_dir/scripts/evaluate_voice_quality.py"
python3 -m py_compile "$repo_dir/scripts/render_phase1_firewall.py"
python3 -m py_compile "$repo_dir/scripts/validate_carrier_intake.py"

ANSHIN_PHONE_SECRET_DIR="$validation_root/secrets" \
  CARRIER_AUTH_MODE=registration \
  CARRIER_HOST=carrier.invalid \
  CARRIER_SOURCE_CIDRS=198.51.100.10/32 \
  SMARTPHONE_SOURCE_CIDRS=192.0.2.10/32 \
  CARRIER_SIP_USERNAME=phase1-validation \
  TEL_DID=0312345678 \
  FAX_DID=0312345679 \
  PUBLIC_SIP_IP=203.0.113.10 \
  PUBLIC_RTP_IP=203.0.113.10 \
  docker compose -f "$repo_dir/compose.phase1.yaml" config -q

if [ "${RUN_PHASE1_SIP_E2E:-0}" = "1" ]; then
  python3 "$repo_dir/scripts/test_phase1_sip_e2e.py"
fi

if git -C "$repo_dir" ls-files | grep -E '(^|/)(\.env[^/]*|[^/]*\.env[^/]*|secrets/)' >/dev/null; then
  echo 'tracked environment or secret file detected' >&2
  exit 1
fi

if ! grep -Fx '.env*' "$repo_dir/.gitignore" >/dev/null \
  || ! grep -Fx '*.env*' "$repo_dir/.gitignore" >/dev/null; then
  echo 'required environment ignore patterns are missing' >&2
  exit 1
fi

echo 'Phase 1 source validation passed. No secret value was read.'
