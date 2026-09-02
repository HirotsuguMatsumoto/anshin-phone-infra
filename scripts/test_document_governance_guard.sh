#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="${1:-$(git rev-parse --show-toplevel)}"
CHECKER="$REPOSITORY_ROOT/scripts/document_governance_portable.py"
RUNNER="$REPOSITORY_ROOT/scripts/run_document_governance_guard.sh"
GUARD_TEST="$REPOSITORY_ROOT/scripts/test_document_governance_guard.sh"
METADATA="$REPOSITORY_ROOT/scripts/document_governance_contract.json"

python3 - "$CHECKER" "$RUNNER" "$GUARD_TEST" "$METADATA" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

checker, runner, guard_test, metadata_path = map(Path, sys.argv[1:])
for path in (checker, runner, guard_test, metadata_path):
    if not path.is_file():
        print(
            f"[document-governance-distribution-test] ERROR: missing distribution file: {path}",
            file=sys.stderr,
        )
        raise SystemExit(1)
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
required_marker = "anshin-document-governance-build-check:v1"
required_command = "bash scripts/run_document_governance_guard.sh"
required_ai_policy_marker = "anshin-ai-driven-development-policy:v1"
required_ai_policy_doc_id = "anshin.governance.ai-driven-development"
if metadata.get("required_build_check_marker") != required_marker:
    print(
        "[document-governance-distribution-test] ERROR: invalid build check marker contract",
        file=sys.stderr,
    )
    raise SystemExit(1)
if metadata.get("required_build_check_command") != required_command:
    print(
        "[document-governance-distribution-test] ERROR: invalid document guard command contract",
        file=sys.stderr,
    )
    raise SystemExit(1)
if metadata.get("required_ai_policy_marker") != required_ai_policy_marker:
    print(
        "[document-governance-distribution-test] ERROR: invalid AI policy marker contract",
        file=sys.stderr,
    )
    raise SystemExit(1)
if metadata.get("required_ai_policy_doc_id") != required_ai_policy_doc_id:
    print(
        "[document-governance-distribution-test] ERROR: invalid AI policy doc_id contract",
        file=sys.stderr,
    )
    raise SystemExit(1)
expected = {
    checker: metadata.get("checker_sha256"),
    runner: metadata.get("runner_sha256"),
    guard_test: metadata.get("guard_test_sha256"),
}
for path, digest in expected.items():
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        print(
            f"[document-governance-distribution-test] ERROR: generated contract drift: {path}",
            file=sys.stderr,
        )
        raise SystemExit(1)
build_check = metadata_path.parent / "build_check.sh"
if not build_check.is_file():
    print(
        "[document-governance-distribution-test] ERROR: scripts/build_check.sh is missing",
        file=sys.stderr,
    )
    raise SystemExit(1)
build_check_text = build_check.read_text(encoding="utf-8")
if required_marker not in build_check_text:
    print(
        "[document-governance-distribution-test] ERROR: build check marker is missing",
        file=sys.stderr,
    )
    raise SystemExit(1)
executable_lines = {
    line.strip()
    for line in build_check_text.splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
if required_command not in executable_lines:
    print(
        "[document-governance-distribution-test] ERROR: build check does not invoke the document guard",
        file=sys.stderr,
    )
    raise SystemExit(1)
print("[document-governance-distribution-test] OK")
PY
