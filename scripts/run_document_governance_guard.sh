#!/usr/bin/env bash
# anshin-document-governance-runner:v1
set -euo pipefail

REPOSITORY_ROOT="$(git rev-parse --show-toplevel)"
EXPLICIT_GOVERNANCE_ROOT=false

if [[ -n "${ANSHIN_GOVERNANCE_ROOT:-}" ]]; then
  GOVERNANCE_ROOT="$(cd "$ANSHIN_GOVERNANCE_ROOT" && pwd)"
  EXPLICIT_GOVERNANCE_ROOT=true
else
  GOVERNANCE_ROOT=""
  candidate="$REPOSITORY_ROOT"
  while [[ "$candidate" != "/" ]]; do
    if [[ -f "$candidate/scripts/run_document_governance_build_check.py" && -f "$candidate/documents/_governance/repository-registry.json" ]]; then
      GOVERNANCE_ROOT="$candidate"
      break
    fi
    if [[ -f "$candidate/anshin/scripts/run_document_governance_build_check.py" && -f "$candidate/anshin/documents/_governance/repository-registry.json" ]]; then
      GOVERNANCE_ROOT="$candidate/anshin"
      break
    fi
    candidate="$(dirname "$candidate")"
  done
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' "[document-governance-build-check] ERROR: python3 is required" >&2
  exit 127
fi

WORKSPACE_COMPLETE=false
if [[ -n "$GOVERNANCE_ROOT" ]]; then
  if $EXPLICIT_GOVERNANCE_ROOT; then
    WORKSPACE_COMPLETE=true
  elif python3 - "$GOVERNANCE_ROOT" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
registry = json.loads(
    (root / "documents/_governance/repository-registry.json").read_text(encoding="utf-8")
)
workspace = root.parent
missing = []
for item in registry.get("document_roots", []):
    candidate = workspace / item["repository_path"] / item["documents_path"]
    if not candidate.is_dir():
        missing.append(str(candidate))
raise SystemExit(0 if not missing else 1)
PY
  then
    WORKSPACE_COMPLETE=true
  fi
fi

if $WORKSPACE_COMPLETE; then
  exec python3 "$GOVERNANCE_ROOT/scripts/run_document_governance_build_check.py" \
    --governance-root "$GOVERNANCE_ROOT" \
    --repository-root "$REPOSITORY_ROOT"
fi

PORTABLE_CHECKER="$REPOSITORY_ROOT/scripts/document_governance_portable.py"
CONTRACT_METADATA="$REPOSITORY_ROOT/scripts/document_governance_contract.json"
GUARD_TEST="$REPOSITORY_ROOT/scripts/test_document_governance_guard.sh"
if [[ ! -f "$PORTABLE_CHECKER" || ! -f "$CONTRACT_METADATA" || ! -f "$GUARD_TEST" ]]; then
  printf '%s\n' \
    "[document-governance-build-check] ERROR: portable governance distribution is missing" >&2
  exit 2
fi

bash "$GUARD_TEST" "$REPOSITORY_ROOT"

exec python3 "$PORTABLE_CHECKER" \
  --repository-root "$REPOSITORY_ROOT" \
  --contract-metadata "$CONTRACT_METADATA"
