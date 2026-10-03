#!/usr/bin/env bash
# anshin-document-governance-build-check:v1
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# anshin-quality-plan-handoff:v1
# anshin-quality-plan-producer:v1
# anshin-quality-plan-adapter-spec: eyJleGVjdXRpb25fYXJncyI6W10sImludm9jYXRpb24iOltdLCJraW5kIjoibGVnYWN5IiwicGxhbl9hcmdzIjpbXSwic2VsZWN0b3IiOiIifQ==
# anshin-quality-plan-dependency: scripts/document_governance_contract.json
# anshin-quality-plan-dependency: scripts/document_governance_portable.py
# anshin-quality-plan-dependency: scripts/run_document_governance_guard.sh
# anshin-quality-plan-dependency: scripts/test_document_governance_guard.sh

if [[ "${1:-}" == "--print-plan" ]]; then
  shift
  [[ "${1:-}" == "--" ]] && shift
  python3 scripts/document_governance_portable.py     --repository-root "$ROOT_DIR" --build-check-plan -- "$@"
  exit $?
fi
if [[ "${1:-}" == "--auto" && "${2:-}" == "--plan" ]]; then
  [[ $# -eq 3 || ( $# -eq 5 && "${4:-}" == "--result" ) ]] || {
    echo "[build_check] ERROR: --auto --plan requires a plan and optional result path" >&2
    exit 2
  }
  DISTRIBUTION_PLAN_PATH="$3"
  DISTRIBUTION_RESULT_PATH="${5:-${ANSHIN_BUILD_CHECK_RESULT_PATH:-}}"
  DISTRIBUTION_RESULT_WRITTEN=0
  write_distribution_failure_result() {
    local distribution_rc=$?
    if [[ $distribution_rc -ne 0 && -n "${DISTRIBUTION_RESULT_PATH:-}" && "$DISTRIBUTION_RESULT_WRITTEN" -eq 0 ]]; then
      python3 scripts/document_governance_portable.py         --repository-root "$ROOT_DIR"         --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" failed         >/dev/null 2>&1 || true
    fi
    exit "$distribution_rc"
  }
  trap write_distribution_failure_result EXIT
  DISTRIBUTION_PROFILE="$(python3 scripts/document_governance_portable.py     --repository-root "$ROOT_DIR" --build-check-plan-profile "$3")"
  if [[ "$DISTRIBUTION_PROFILE" == "document-distribution" ]]; then
    set -- --document-distribution
  else
    python3 scripts/document_governance_portable.py       --repository-root "$ROOT_DIR"       --execute-build-check-plan "$3"
    if [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
      python3 scripts/document_governance_portable.py         --repository-root "$ROOT_DIR"         --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed
      DISTRIBUTION_RESULT_WRITTEN=1
    fi
    trap - EXIT
    echo "[build_check] OK profile=$DISTRIBUTION_PROFILE"
    exit 0
  fi
fi
# /anshin-quality-plan-handoff:v1
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
  if [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
    python3 scripts/document_governance_portable.py       --repository-root "$ROOT_DIR"       --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed
    DISTRIBUTION_RESULT_WRITTEN=1
  fi
  trap - EXIT
  echo "[build_check] OK profile=document-distribution"
  exit 0
fi
# /anshin-document-distribution-profile:v1

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
