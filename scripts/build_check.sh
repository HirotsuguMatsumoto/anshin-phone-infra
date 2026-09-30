#!/usr/bin/env bash
# anshin-document-governance-build-check:v1
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# anshin-document-distribution-profile:v1
if [[ "${1:-}" == "--document-distribution" ]]; then
  [[ $# -eq 1 ]] || { echo "[build_check] ERROR: distribution mode accepts no paths" >&2; exit 2; }
  bash scripts/run_document_governance_guard.sh
  DISTRIBUTION_SELECTION="$(bash scripts/run_document_governance_guard.sh --build-check-profile)"
  read -r DISTRIBUTION_PROFILE DISTRIBUTION_BASE DISTRIBUTION_TARGET DISTRIBUTION_HEAD DISTRIBUTION_INPUT <<< "$DISTRIBUTION_SELECTION"
  [[ "$DISTRIBUTION_PROFILE" == "document-distribution" ]] || {
    echo "[build_check] ERROR: actual changes require the normal repository profile" >&2
    exit 2
  }
  git diff --no-ext-diff --no-textconv --check "$DISTRIBUTION_BASE...HEAD" --
  git diff --no-ext-diff --no-textconv --cached --check --
  git diff --no-ext-diff --no-textconv --check --
  bash -n scripts/build_check.sh scripts/run_document_governance_guard.sh scripts/test_document_governance_guard.sh
  bash scripts/test_document_governance_guard.sh "$ROOT_DIR"
  [[ "$(bash scripts/run_document_governance_guard.sh --build-check-profile)" == "$DISTRIBUTION_SELECTION" ]] || {
    echo "[build_check] ERROR: distribution inputs changed during verification" >&2
    exit 1
  }
  echo "[build_check] OK profile=document-distribution"
  exit 0
fi
# /anshin-document-distribution-profile:v1

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
