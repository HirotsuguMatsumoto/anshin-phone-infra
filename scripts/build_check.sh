#!/usr/bin/env bash
# anshin-document-governance-build-check:v1
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# anshin-quality-plan-handoff:v1
# anshin-quality-plan-producer:v1
# anshin-quality-plan-adapter-spec: eyJkZXBlbmRlbmNpZXMiOltdLCJleGVjdXRpb25fYXJncyI6W10sImludm9jYXRpb24iOltdLCJraW5kIjoibGVnYWN5IiwicGxhbl9hcmdzIjpbXSwic2VsZWN0b3IiOiIifQ==
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
  DISTRIBUTION_RESULT_ATTEMPTED=0
  DISTRIBUTION_FAILED_CHECK_IDS=()
  DISTRIBUTION_TIMING_TOKEN="$(python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --timing-plan "$DISTRIBUTION_PLAN_PATH" --timing-start build.canonical)" || true
  # Match Core native: the repository-owned Poetry carrier intentionally uses
  # interpreter word splitting; all plan/result/data arguments remain quoted.
  verify_core_execution_inputs() {
    local final_selection
    if [[ "$1" == "0" ]]; then
      CORE_TERMINAL_ARGS=(--repository-root "$ROOT_DIR" --build-check-execution-selection "$DISTRIBUTION_PLAN_PATH" --expected-check-inputs-sha256 "$DISTRIBUTION_CHECK_INPUTS_SHA256")
      for completed_id in "${DISTRIBUTION_COMPLETED_CHECK_IDS[@]:-}"; do
        [[ -n "$completed_id" ]] && CORE_TERMINAL_ARGS+=(--completed-check "$completed_id")
      done
      ${PYTHON_BIN:-python3} scripts/document_governance_portable.py "${CORE_TERMINAL_ARGS[@]}" >/dev/null
      return $?
    fi
    final_selection="$(${PYTHON_BIN:-python3} scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --build-check-execution-selection "$DISTRIBUTION_PLAN_PATH")" || return $?
    ${PYTHON_BIN:-python3} -c 'import json,sys; current=json.loads(sys.argv[1])["inputs_sha256"]; sys.exit(0 if current == sys.argv[2] else "[build_check:auto] ERROR: quality execution inputs changed during verification")' "$final_selection" "$DISTRIBUTION_CHECK_INPUTS_SHA256"
  }
  write_distribution_failure_result() {
    local distribution_rc=$?
    local distribution_result_attempted="${DISTRIBUTION_RESULT_ATTEMPTED:-0}"
    if [[ "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" && -z "${DISTRIBUTION_CHECK_INPUTS_SHA256:-}" ]]; then
      printf '%s\n' "[build_check:auto] ERROR: execution inputs were not captured before verification" >&2
      [[ $distribution_rc -ne 0 ]] || distribution_rc=1
    fi
    if [[ "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" && -n "${DISTRIBUTION_CHECK_INPUTS_SHA256:-}" && -z "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
      verify_core_execution_inputs "$distribution_rc" || {
        local input_rc=$?
        [[ $distribution_rc -ne 0 ]] || distribution_rc=$input_rc
      }
    fi
    if [[ $distribution_rc -eq 0 && "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" && "$DISTRIBUTION_RESULT_WRITTEN" -eq 0 ]]; then
      if [[ "$(git write-tree)" != "$AUTO_INDEX_TREE" ]] || ! git diff --quiet -- || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
        distribution_rc=1
      elif [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
        distribution_result_attempted=1
        DISTRIBUTION_SUCCESS_ARGS=(--repository-root "$ROOT_DIR")
        for completed_id in "${DISTRIBUTION_COMPLETED_CHECK_IDS[@]:-}"; do
          [[ -n "$completed_id" ]] && DISTRIBUTION_SUCCESS_ARGS+=(--completed-check "$completed_id")
        done
        ${PYTHON_BIN:-python3} scripts/document_governance_portable.py           "${DISTRIBUTION_SUCCESS_ARGS[@]}"           --expected-check-inputs-sha256 "$DISTRIBUTION_CHECK_INPUTS_SHA256"           --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed || distribution_rc=$?
        [[ $distribution_rc -ne 0 ]] || DISTRIBUTION_RESULT_WRITTEN=1
      fi
    fi
    if [[ $distribution_rc -ne 0 && -n "${DISTRIBUTION_RESULT_PATH:-}" && "$DISTRIBUTION_RESULT_WRITTEN" -eq 0 && "$distribution_result_attempted" -eq 0 ]]; then
      # Keep the argv non-empty so Bash 3 with nounset can expand it safely
      # even when no optional completed/failed check arguments exist.
      DISTRIBUTION_FAILURE_ARGS=(--repository-root "$ROOT_DIR")
      for completed_id in "${DISTRIBUTION_COMPLETED_CHECK_IDS[@]:-}"; do
        [[ -n "$completed_id" ]] && DISTRIBUTION_FAILURE_ARGS+=(--completed-check "$completed_id")
      done
      if [[ ${#DISTRIBUTION_FAILED_CHECK_IDS[@]} -gt 0 ]]; then
        for failed_id in "${DISTRIBUTION_FAILED_CHECK_IDS[@]}"; do DISTRIBUTION_FAILURE_ARGS+=(--failed-check "$failed_id"); done
      elif [[ -n "${DISTRIBUTION_CURRENT_CHECK_ID:-}" ]]; then DISTRIBUTION_FAILURE_ARGS+=(--failed-check "$DISTRIBUTION_CURRENT_CHECK_ID"); fi
      if [[ "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" ]]; then
        if [[ -n "${DISTRIBUTION_CHECK_INPUTS_SHA256:-}" ]]; then
          DISTRIBUTION_FAILURE_ARGS+=(--expected-check-inputs-sha256 "$DISTRIBUTION_CHECK_INPUTS_SHA256")
          ${PYTHON_BIN:-python3} scripts/document_governance_portable.py "${DISTRIBUTION_FAILURE_ARGS[@]}" --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" failed || true
        fi
      else
        if [[ -n "${DISTRIBUTION_EXECUTION_SELECTION:-}" ]]; then
          DISTRIBUTION_FAILURE_ARGS+=(--expected-check-inputs-sha256 "$(node -e 'console.log(JSON.parse(process.argv[1]).inputs_sha256 || "")' "$DISTRIBUTION_EXECUTION_SELECTION")")
        fi
        python3 scripts/document_governance_portable.py           "${DISTRIBUTION_FAILURE_ARGS[@]}"           --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" failed           >/dev/null 2>&1 || true
      fi
    fi
    if [[ $distribution_rc -eq 0 && "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" ]]; then
      printf '%s\n' "[build_check] OK mode=--auto"
    fi
    python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --timing-end "${DISTRIBUTION_CHECK_TOKEN:-}" "$distribution_rc" || true
    python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --timing-end "${DISTRIBUTION_TIMING_TOKEN:-}" "$distribution_rc" || true
    exit "$distribution_rc"
  }
  trap write_distribution_failure_result EXIT
  DISTRIBUTION_PROFILE="$(python3 scripts/document_governance_portable.py     --repository-root "$ROOT_DIR" --build-check-plan-profile "$3")"
  if [[ "$DISTRIBUTION_PROFILE" == "document-distribution" ]]; then
    set -- --document-distribution

  else
    DISTRIBUTION_EXECUTOR_ARGS=(--repository-root "$ROOT_DIR" --timing-parent "${DISTRIBUTION_TIMING_TOKEN:-}" --execute-build-check-plan "$3")
    if [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
      # The executor owns actual completion/failure evidence in this process.
      # Do not synthesize another result if it rejects drift or is interrupted.
      DISTRIBUTION_RESULT_ATTEMPTED=1
      DISTRIBUTION_EXECUTOR_ARGS+=(--execution-result "$DISTRIBUTION_RESULT_PATH")
    fi
    python3 scripts/document_governance_portable.py "${DISTRIBUTION_EXECUTOR_ARGS[@]}"
    [[ -z "${DISTRIBUTION_RESULT_PATH:-}" ]] || DISTRIBUTION_RESULT_WRITTEN=1
    python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --timing-end "${DISTRIBUTION_TIMING_TOKEN:-}" 0 || true
    trap - EXIT
    echo "[build_check] OK profile=$DISTRIBUTION_PROFILE"
    exit 0
  fi
fi
# /anshin-quality-plan-handoff:v1
# anshin-document-distribution-profile:v1
if [[ "${1:-}" == "--document-distribution" ]]; then
  [[ $# -eq 1 ]] || { echo "[build_check] ERROR: distribution mode accepts no paths" >&2; exit 2; }
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
  bash scripts/run_document_governance_guard.sh --with-portable-self-test
  [[ "$(bash scripts/run_document_governance_guard.sh --build-check-profile)" == "$DISTRIBUTION_SELECTION" ]] || {
    echo "[build_check] ERROR: distribution inputs changed during verification" >&2
    exit 1
  }
  if [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
    python3 scripts/document_governance_portable.py       --repository-root "$ROOT_DIR"       --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed
    DISTRIBUTION_RESULT_WRITTEN=1
  fi
  python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --timing-end "${DISTRIBUTION_TIMING_TOKEN:-}" 0 || true
  trap - EXIT
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
tests=()
if [[ "$MODE" == "--fast" && "${RUN_PHASE1_SIP_E2E:-0}" != "1" ]]; then
  changes="$(mktemp "${TMPDIR:-/tmp}/anshin-phone-infra-paths.XXXXXX")"
  trap 'rm -f "$changes"' EXIT
  python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --list-change-paths >"$changes"
  while IFS= read -r -d '' path; do
    case "$path" in
      documents/*.md|docs/*.md|AGENTS.md) continue ;;
      scripts/test_phase1_render_config.py|scripts/test_kamailio_render_config.py|scripts/test_pbx_event_pipeline.py|scripts/test_device_and_voice_tools.py|scripts/test_carrier_and_firewall_tools.py|scripts/test_phase1_sip_e2e_cleanup.py|scripts/test_resolve_phone_backend.py)
        [[ -f "$path" ]] || { tests=(); break; }
        tests+=("$path") ;;
      *) tests=(); break ;;
    esac
  done <"$changes"
fi
if [[ "${#tests[@]}" -gt 0 ]]; then
  ./scripts/verify_phase1.sh --tests "${tests[@]}"
else
  ./scripts/verify_phase1.sh
fi
echo "[build_check] OK mode=$MODE"
