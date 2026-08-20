#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

required_files='compose.phase1.yaml
deploy/asterisk/Dockerfile
deploy/asterisk/config/pjsip.conf.template
deploy/asterisk/config/extensions.conf.template
deploy/asterisk/scripts/render_config.py
deploy/asterisk/scripts/entrypoint.sh
anshin-phone-backend/Dockerfile
anshin-phone-backend/app/main.py'

printf '%s\n' "$required_files" | while IFS= read -r item; do
  test -f "$repo_dir/$item" || {
    echo "missing required file: $item" >&2
    exit 1
  }
done

python3 -m py_compile "$repo_dir/deploy/asterisk/scripts/render_config.py"

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
