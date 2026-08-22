#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

required_files='compose.phase1.yaml
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
scripts/test_kamailio_render_config.py
scripts/test_device_and_voice_tools.py
scripts/test_carrier_and_firewall_tools.py
anshin-phone-backend/Dockerfile
anshin-phone-backend/app/main.py'

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
python3 "$repo_dir/scripts/test_kamailio_render_config.py"
python3 "$repo_dir/scripts/test_pbx_event_pipeline.py"
python3 "$repo_dir/scripts/test_device_and_voice_tools.py"
python3 "$repo_dir/scripts/test_carrier_and_firewall_tools.py"
python3 -m py_compile "$repo_dir/scripts/create_sip_enrollment_bundle.py"
python3 -m py_compile "$repo_dir/scripts/evaluate_voice_quality.py"
python3 -m py_compile "$repo_dir/scripts/render_phase1_firewall.py"
python3 -m py_compile "$repo_dir/scripts/validate_carrier_intake.py"

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
