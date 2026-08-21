#!/usr/bin/env bash
# anshin-document-governance-build-check:v1
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:---full}"
case "$MODE" in
  --full|--fast|--documents-only) ;;
  -h|--help)
    echo "Usage: bash scripts/build_check.sh [--full|--fast|--documents-only]"
    exit 0
    ;;
  *) echo "[build_check] ERROR: unsupported argument: $MODE" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { echo "[build_check] ERROR: too many arguments" >&2; exit 2; }

bash scripts/run_document_governance_guard.sh
if [[ "$MODE" == "--documents-only" ]]; then
  echo "[build_check:documents-only] OK"
  exit 0
fi

git diff --check
./scripts/verify_phase1.sh
echo "[build_check] OK mode=$MODE"
