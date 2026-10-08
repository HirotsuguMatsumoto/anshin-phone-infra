#!/usr/bin/env python3
"""Network-free, stdlib-only document governance contract for one Git repository.

This file is the canonical source for generated repository-local distributions.
Run scripts/sync_document_governance_distribution.py to update copies.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import platform
import re
import shlex
import stat
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote

CONTRACT_VERSION = "2026-09-03.1"
BUILD_CHECK_MARKER = "anshin-document-governance-build-check:v1"
BUILD_CHECK_COMMAND = "bash scripts/run_document_governance_guard.sh"
QUALITY_PLAN_MARKER = "anshin-quality-plan-handoff:v1"
QUALITY_PLAN_SCHEMA = "anshin.repository-quality-plan.v1"
AI_POLICY_MARKER = "anshin-ai-driven-development-policy:v1"
AI_POLICY_DOC_ID = "anshin.governance.ai-driven-development"
DISTRIBUTION_PATHS = frozenset(
    {
        "scripts/document_governance_portable.py",
        "scripts/run_document_governance_guard.sh",
        "scripts/test_document_governance_guard.sh",
        "scripts/document_governance_contract.json",
    }
)
DISTRIBUTION_BUILD_ADAPTER_TEMPLATE = """
# anshin-quality-plan-handoff:v1
# anshin-quality-plan-producer:v1
{adapter_metadata}
# anshin-quality-plan-dependency: scripts/document_governance_contract.json
# anshin-quality-plan-dependency: scripts/document_governance_portable.py
# anshin-quality-plan-dependency: scripts/run_document_governance_guard.sh
# anshin-quality-plan-dependency: scripts/test_document_governance_guard.sh
{native_dependencies}
{internal_guard}
if [[ "${1:-}" == "--print-plan" ]]; then
  shift
  [[ "${1:-}" == "--" ]] && shift
  python3 scripts/document_governance_portable.py \
    --repository-root "$ROOT_DIR" --build-check-plan -- "$@"
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
    if [[ $distribution_rc -eq 0 && "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" && "$DISTRIBUTION_RESULT_WRITTEN" -eq 0 ]]; then
      if [[ "$(git write-tree)" != "$AUTO_INDEX_TREE" ]] || ! git diff --quiet -- || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
        distribution_rc=1
      elif [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
        python3 scripts/document_governance_portable.py \
          --repository-root "$ROOT_DIR" \
          --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed || distribution_rc=$?
        [[ $distribution_rc -ne 0 ]] || DISTRIBUTION_RESULT_WRITTEN=1
      fi
    fi
    if [[ $distribution_rc -ne 0 && -n "${DISTRIBUTION_RESULT_PATH:-}" && "$DISTRIBUTION_RESULT_WRITTEN" -eq 0 ]]; then
      # Keep the argv non-empty so Bash 3 with nounset can expand it safely
      # even when no optional completed/failed check arguments exist.
      DISTRIBUTION_FAILURE_ARGS=(--repository-root "$ROOT_DIR")
      for completed_id in "${DISTRIBUTION_COMPLETED_CHECK_IDS[@]:-}"; do
        [[ -n "$completed_id" ]] && DISTRIBUTION_FAILURE_ARGS+=(--completed-check "$completed_id")
      done
      [[ -n "${DISTRIBUTION_CURRENT_CHECK_ID:-}" ]] && DISTRIBUTION_FAILURE_ARGS+=(--failed-check "$DISTRIBUTION_CURRENT_CHECK_ID")
      python3 scripts/document_governance_portable.py \
        "${DISTRIBUTION_FAILURE_ARGS[@]}" \
        --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" failed \
        >/dev/null 2>&1 || true
    fi
    exit "$distribution_rc"
  }
  trap write_distribution_failure_result EXIT
  DISTRIBUTION_PROFILE="$(python3 scripts/document_governance_portable.py \
    --repository-root "$ROOT_DIR" --build-check-plan-profile "$3")"
  if [[ "$DISTRIBUTION_PROFILE" == "document-distribution" ]]; then
    set -- --document-distribution
{native_plan_branch}
  else
    python3 scripts/document_governance_portable.py \
      --repository-root "$ROOT_DIR" \
      --execute-build-check-plan "$3"
    if [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
      python3 scripts/document_governance_portable.py \
        --repository-root "$ROOT_DIR" \
        --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed
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
    python3 scripts/document_governance_portable.py \
      --repository-root "$ROOT_DIR" \
      --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed
    DISTRIBUTION_RESULT_WRITTEN=1
  fi
  trap - EXIT
  echo "[build_check] OK profile=document-distribution"
  exit 0
fi
# /anshin-document-distribution-profile:v1
"""
DISTRIBUTION_AGENTS_ADAPTER = """
## Checker配布の限定検査

文書checkerの配布と定型adapterだけの変更は、`anshin.governance.document-management`の10.2に従い、repository-local planを一度生成し、`bash scripts/build_check.sh --auto --plan <path>`へ渡す。それ以外の変更ではrepository固有の通常selectorを維持する。専用profileが不適格を返した場合は検査を省略せず、通常の変更範囲検査へ戻す。
"""
LEGACY_DISTRIBUTION_AGENTS_ADAPTER = """
## Checker配布の限定検査

文書checkerの配布と定型adapterだけの変更は、`anshin.governance.document-management`の10.2に従い、`bash scripts/build_check.sh --document-distribution`をcanonical検査とする。それ以外の変更では本書の通常fast/full条件を維持する。専用profileが不適格を返した場合は検査を省略せず、通常の変更範囲検査へ戻す。
"""
WORKSPACE_ROOT_EXPLANATION = "本書のcommand例で使う`WORKSPACE_ROOT`は、対象repositoryを置く親directoryとして利用環境で設定する。repository名付きのcommand pathはこのrootから解決し、実行directoryに依存しない。"
DISTRIBUTION_HOOK_PATH = ".githooks/pre-commit"
DISTRIBUTION_HOOK_ADAPTER = """
# anshin-document-distribution-hook:v1
distribution_repo_root="$(git rev-parse --show-toplevel)"
distribution_selection="$(bash scripts/run_document_governance_guard.sh --build-check-profile)"
if [[ "$distribution_selection" == document-distribution\\ * ]]; then
  distribution_plan="$(mktemp "${TMPDIR:-/tmp}/anshin-document-plan.XXXXXX")"
  python3 scripts/document_governance_portable.py \
    --repository-root "$distribution_repo_root" --build-check-plan > "$distribution_plan"
  chmod 600 "$distribution_plan"
  if bash scripts/build_check.sh --auto --plan "$distribution_plan"; then
    rm -f "$distribution_plan"
    exit 0
  else
    distribution_rc=$?
    rm -f "$distribution_plan"
    exit "$distribution_rc"
  fi
fi
# /anshin-document-distribution-hook:v1
"""
AI_POLICY_REQUIRED_TEXT = (
    AI_POLICY_DOC_ID,
    "実際の業務経路による結合テスト",
    "自動回帰テストへ固定",
    "独立AI review",
    "prompt injection",
)
DOC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
DOMAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

# Inspect source text, including code fences and reference-style links.
# Runtime server paths and HTTP routes are not repository references.
ABSOLUTE_SOURCE_PATH_PATTERN = re.compile(
    r"""(?<![A-Za-z0-9_./>~])(?:[A-Za-z]:[\\/]|\\\\|/)[^\s`<>\[\]()"'、。）」|]*"""
)
FILE_URI_PATTERN = re.compile(
    r"""file://[^\s`<>\[\]()"'、。）」|]+""",
    re.IGNORECASE,
)
QUOTED_FILE_URI_PATTERN = re.compile(
    r"""(?P<quote>[`"'])(?P<path>file://.*?)(?P=quote)""",
    re.IGNORECASE,
)
QUOTED_ABSOLUTE_PATH_PATTERN = re.compile(
    r"""(?P<quote>[`"'])(?P<path>(?:file://)?(?:[A-Za-z]:[\\/]|\\\\|/).*?)(?P=quote)""",
    re.IGNORECASE,
)
REPOSITORY_NAMES = (
    "anshin",
    "anshin-ads-monorepo",
    "anshin-attendance-kiosk",
    "anshin-auth",
    "anshin-backend",
    "anshin-corporate-strategy",
    "anshin-customer-mobile",
    "anshin-docs",
    "anshin-frontend-mobile",
    "anshin-frontend-monorepo",
    "anshin-helper-service",
    "anshin-marketing-backend",
    "anshin-marketing-infra",
    "anshin-operations-platform",
    "anshin-phone-backend",
    "anshin-phone-infra",
    "anshin-study-backend",
    "anshin-study-infra",
    "anshin-vulnediag-backend",
    "anshin-vulnediag-infra",
    "anshin-www",
    "anshin.care",
)
REPOSITORY_COMPONENT_PATTERN = re.compile(
    r"(?:^|/)(?:"
    + "|".join(map(re.escape, REPOSITORY_NAMES))
    + r"|anshin[a-z0-9_.-]*worktree[a-z0-9_.-]*)(?:/|$)",
    re.IGNORECASE,
)
WINDOWS_UNC_REPOSITORY_PATH_PATTERN = re.compile(
    r"""(?<![A-Za-z0-9_.])(?:[A-Za-z]:[\\/]|\\\\)"""
    r"""(?:[^\\/`<>\[\]()"'、。）」|\r\n]+[\\/])*"""
    r"""(?:"""
    + "|".join(map(re.escape, REPOSITORY_NAMES))
    + r"""|anshin[a-z0-9_.-]*worktree[a-z0-9_.-]*)(?=[\\/]|$)""",
    re.IGNORECASE,
)
POSIX_SPACED_REPOSITORY_PATH_PATTERN = re.compile(
    r"""(?<![A-Za-z0-9_./>~])/(?=[^=`<>\[\]()"'、。）」|,\r\n]*[ \t])"""
    r"""(?:[^/=`<>\[\]()"'、。）」|,\r\n]*[^\s/=`<>\[\]()"'、。）」|,\r\n]/)*"""
    r"""(?:"""
    + "|".join(map(re.escape, REPOSITORY_NAMES))
    + r"""|anshin[a-z0-9_.-]*worktree[a-z0-9_.-]*)(?=/|[ =\t`<>\[\]()"'、。）」|,]|$)"""
    r"""(?:/[^ =\t`<>\[\]()"'、。）」|,\r\n]+)*""",
    re.IGNORECASE,
)
SPACED_FILE_URI_REPOSITORY_PATH_PATTERN = re.compile(
    r"""file://(?=[^`<>\[\]()"'、。）」|,\r\n]*[ \t])"""
    r"""[^`<>\[\]()"'、。）」|,\r\n]*?"""
    r"""(?:"""
    + "|".join(map(re.escape, REPOSITORY_NAMES))
    + r"""|anshin[a-z0-9_.-]*worktree[a-z0-9_.-]*)(?=[/\\]|[ =\t`<>\[\]()"'、。）」|,]|$)"""
    r"""(?:[/\\][^ =\t`<>\[\]()"'、。）」|,\r\n]+)*""",
    re.IGNORECASE,
)
# Fixed server installation namespaces; nested clone/checkouts remain forbidden.
DEPLOYMENT_ROOT_PREFIXES = tuple(
    namespace + name + "/"
    for namespace in ("/etc/", "/var/lib/", "/var/log/", "/opt/", "/ops/")
    for name in REPOSITORY_NAMES
)
FIXED_RUNTIME_PREFIXES = (
    "/etc/anshin/",
    "/var/lib/anshin/",
    "/var/log/anshin/",
    "/opt/anshin/",
    "/opt/anshin-auth/",
    "/opt/anshin-vulnediag-infra/",
    "/usr/local/libexec/anshin/",
    "/opt/keycloak/themes/",
    "/srv/anshin-auth/postgres/",
    "/srv/anshin-backups/",
    "/srv/anshin-container-runtime/",
    "/mnt/anshin-auth-offhost/",
)
SERVER_HOME_RUNTIME_PREFIXES = ("/home/ubuntu/logs/", "/home/ubuntu/dump/")

WEB_ROUTE_PREFIXES = (
    "/login/",
    "/realms/",
    "/api/",
    "/docs/",
    "/assets/",
    "/static/",
    "/healthz",
    "/readyz",
    "/dependencyz",
)
KEYCLOAK_ASSET_ROUTE_PATTERN = re.compile(
    r"^/resources/(?:<cache-key>|[a-z0-9._-]+)/login/[a-z0-9._-]+(?:/|$)",
    re.IGNORECASE,
)
HTTP_OPERATION_PATTERN = r"GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|TRACE"
HTTP_METHOD_ROUTE_CONTEXT = re.compile(
    rf"""(?:^|[\s|])[`"']?(?:{HTTP_OPERATION_PATTERN})[`"']?"""
    r"""\s+(?:[`"']\s*)?$""",
    re.IGNORECASE,
)
HTTP_METHOD_TABLE_BEFORE_ROUTE_CONTEXT = re.compile(
    rf"""(?:^|\|)\s*[`"']?(?:{HTTP_OPERATION_PATTERN})[`"']?"""
    r"""\s*\|\s*(?:[`"']\s*)?$""",
    re.IGNORECASE,
)
HTTP_METHOD_TABLE_AFTER_ROUTE_CONTEXT = re.compile(
    rf"""^[`"']?\s*\|\s*[`"']?(?:{HTTP_OPERATION_PATTERN})""" r"""[`"']?\s*(?:\||$)""",
    re.IGNORECASE,
)
API_PATH_KEY_PATTERN = re.compile(
    r"""^\s*(?P<quote>["']?)(?P<path>/[^\s`"']+?)(?P=quote)\s*:\s*(?:\{\s*)?(?:#.*)?$"""
)
INLINE_API_OPERATION_PATH_PATTERN = re.compile(
    r"""^\s*(?P<quote>["']?)(?P<path>/[^\s`"']+?)(?P=quote)\s*:\s*\{\s*"""
    rf"""(?P<operation_quote>["']?)(?:{HTTP_OPERATION_PATTERN})(?P=operation_quote)\s*:""",
    re.IGNORECASE,
)
API_OPERATION_KEY_PATTERN = re.compile(
    rf"""^(?P<indent>[ \t]+)(?P<quote>["']?)(?:{HTTP_OPERATION_PATTERN})"""
    r"""(?P=quote)\s*:(?:\s|$)""",
    re.IGNORECASE,
)


def _normalized_source_path(value: str) -> str:
    path = unquote(value)
    path = re.sub(r"^file://(?:[^/\s]+)?(?=/)", "", path, flags=re.IGNORECASE)
    path = path.replace("\\", "/")
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return path


def _is_fixed_runtime_path(path: str) -> bool:
    lower = path.lower()
    for prefix in sorted(
        FIXED_RUNTIME_PREFIXES + DEPLOYMENT_ROOT_PREFIXES,
        key=len,
        reverse=True,
    ):
        root = prefix.rstrip("/")
        if lower == root:
            return True
        if not lower.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        if prefix == "/opt/keycloak/themes/":
            owner, separator, nested = remainder.partition("/")
            if owner.lower() == "anshin":
                return (
                    not separator
                    or REPOSITORY_COMPONENT_PATTERN.search(f"/{nested}") is None
                )
        return REPOSITORY_COMPONENT_PATTERN.search(f"/{remainder}") is None
    return False


def _is_http_method_route(source: str, start: int, end: int) -> bool:
    return (
        HTTP_METHOD_ROUTE_CONTEXT.search(source[:start]) is not None
        or HTTP_METHOD_TABLE_BEFORE_ROUTE_CONTEXT.search(source[:start]) is not None
        or HTTP_METHOD_TABLE_AFTER_ROUTE_CONTEXT.search(source[end:]) is not None
    )


def _is_route_candidate(value: str, path: str) -> bool:
    return value.startswith("/") and not value.startswith("//") and path.startswith("/")


def _is_api_operation_path(source_lines: list[str], index: int, path: str) -> bool:
    inline_path = INLINE_API_OPERATION_PATH_PATTERN.match(source_lines[index])
    if inline_path is not None and path.rstrip(":") == inline_path.group("path"):
        return True
    path_key = API_PATH_KEY_PATTERN.match(source_lines[index])
    if path_key is None or path.rstrip(":") != path_key.group("path"):
        return False
    path_indent = len(source_lines[index]) - len(source_lines[index].lstrip(" \t"))
    for following in source_lines[index + 1 :]:
        if not following.strip() or following.lstrip().startswith("#"):
            continue
        operation = API_OPERATION_KEY_PATTERN.match(following)
        return operation is not None and len(operation.group("indent")) > path_indent
    return False


def _is_explicit_web_route(path: str) -> bool:
    return path.lower().startswith(WEB_ROUTE_PREFIXES) or (
        KEYCLOAK_ASSET_ROUTE_PATTERN.match(path) is not None
    )


def nonportable_markdown_path_lines(text: str) -> list[int]:
    lines = []
    source_lines = text.splitlines()
    for index, line in enumerate(source_lines):
        number = index + 1
        source = re.sub(r"https?://[^\s<>`]+", "", line, flags=re.IGNORECASE)
        extracted_paths: list[tuple[str, int, int]] = []

        def remember_quoted_path(
            match: re.Match[str], paths: list[tuple[str, int, int]] = extracted_paths
        ) -> str:
            paths.append((match.group("path"), match.start("path"), match.end("path")))
            return " " * len(match.group())

        def remember_unquoted_path(
            match: re.Match[str], paths: list[tuple[str, int, int]] = extracted_paths
        ) -> str:
            paths.append((match.group(), match.start(), match.end()))
            return " " * len(match.group())

        source = QUOTED_FILE_URI_PATTERN.sub(remember_quoted_path, source)
        source = SPACED_FILE_URI_REPOSITORY_PATH_PATTERN.sub(
            remember_unquoted_path, source
        )
        source = FILE_URI_PATTERN.sub(remember_unquoted_path, source)
        source = unquote(source)
        source = re.sub(
            r"""\$(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)["']?(?=/)""",
            "PORTABLE_ROOT",
            source,
        )
        source = QUOTED_ABSOLUTE_PATH_PATTERN.sub(remember_quoted_path, source)
        if WINDOWS_UNC_REPOSITORY_PATH_PATTERN.search(source):
            lines.append(number)
            continue
        candidates = (
            extracted_paths
            + [
                (match.group(), match.start(), match.end())
                for match in POSIX_SPACED_REPOSITORY_PATH_PATTERN.finditer(source)
                if re.search(r"[ \t]", match.group())
            ]
            + [
                (match.group(), match.start(), match.end())
                for match in ABSOLUTE_SOURCE_PATH_PATTERN.finditer(source)
            ]
        )
        for value, start, end in candidates:
            path = _normalized_source_path(value)
            lower = path.lower()
            route_candidate = _is_route_candidate(value, path)
            if route_candidate and (
                _is_http_method_route(source, start, end)
                or _is_api_operation_path(source_lines, index, path)
            ):
                continue
            if (
                _is_fixed_runtime_path(path)
                or (route_candidate and _is_explicit_web_route(path))
                or re.match(r"^[a-z]:/(?:windows|runtime)/", lower)
            ):
                continue
            personal_root = path.startswith("/Users/") or lower.startswith(
                ("/srv/codex/", "/workspace/", "/workspaces/")
            )
            personal_home = (
                lower.startswith("/home/")
                and lower not in {"/home/", "/home/ms-a2-1"}
                and not any(
                    lower == prefix.rstrip("/") or lower.startswith(prefix)
                    for prefix in SERVER_HOME_RUNTIME_PREFIXES
                )
            )
            if lower.startswith("/home/ubuntu/dump_"):
                personal_home = False
            windows_home = bool(re.match(r"^[a-z]:/users/", lower))
            repository_path = bool(REPOSITORY_COMPONENT_PATTERN.search(path))
            if personal_root or personal_home or windows_home or repository_path:
                lines.append(number)
                break
    return lines


def validate_repository_markdown_paths(
    repository_root: Path, errors: list[str]
) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        errors.append("cannot enumerate repository Markdown paths")
        return
    for name in sorted(set(result.stdout.split("\0")) - {""}):
        path = repository_root / name
        if path.suffix.lower() not in {".md", ".markdown", ".mdx"}:
            continue
        if not path.is_symlink() and not path.is_file():
            continue
        try:
            # Check a symlink target reference without following it outside Git.
            source = (
                str(path.readlink())
                if path.is_symlink()
                else path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError) as exc:
            errors.append(f"{name}: cannot read Markdown: {exc}")
            continue
        for number in nonportable_markdown_path_lines(source):
            errors.append(
                f"{name}:{number}: local absolute repository path is forbidden; "
                "use a repository-prefixed path or a runtime root variable"
            )


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
)
RETIRED_SOURCE_DOCS_LITERAL_PATTERN = re.compile(r"(?m)^[ \t]*source_docs[ \t]*:")
SOURCE_TEMPLATE_SUFFIXES = {".cjs", ".js", ".mjs", ".py", ".sh", ".ts", ".tsx"}
REQUIRED_METADATA = {
    "schema_version",
    "doc_id",
    "title",
    "domain",
    "document_kind",
    "scope",
    "product",
    "owner",
    "authority",
    "status",
    "risk_level",
    "source_doc_ids",
    "consumers",
    "code_paths",
    "contract_paths",
    "test_paths",
    "last_reviewed",
    "review_interval_days",
    "sensitivity",
}
LIST_METADATA = {
    "source_doc_ids",
    "consumers",
    "code_paths",
    "contract_paths",
    "test_paths",
    "generated_artifacts",
    "reviewed_by",
    "approved_by",
}
ALLOWED_KINDS = {
    "spec",
    "index",
    "template",
    "decision",
    "runbook",
    "plan",
    "status",
    "evidence",
    "reference",
    "generated",
}
ALLOWED_SCOPES = {"organization", "repository", "product", "app", "component"}
ALLOWED_AUTHORITIES = {"canonical", "reference", "generated", "derived", "evidence"}
ALLOWED_STATUSES = {"inventory", "draft", "review", "active", "deprecated", "retired"}
ALLOWED_PLAN_STATES = {
    "needs-review",
    "proposed",
    "approved",
    "in-progress",
    "completed",
    "cancelled",
}
ALLOWED_RISKS = {"low", "normal", "high", "critical"}
ALLOWED_SENSITIVITY = {"public", "internal", "restricted"}
FORBIDDEN_GITHUB_ACTIONS_QUALITY_COMMANDS = (
    "build_check.sh",
    "run_document_governance_guard.sh",
)
ALLOWED_GITHUB_ACTIONS_WORKFLOWS = {
    "backend-image.yml": "docker/build-push-action@",
    "backend-image.yaml": "docker/build-push-action@",
    "deploy-production.yml": "sh/release_workflow.py run",
    "deploy-production.yaml": "sh/release_workflow.py run",
    "production-image.yml": "docker/build-push-action@",
    "production-image.yaml": "docker/build-push-action@",
}


def validate_ai_policy_contract(
    repository_root: Path, metadata: dict[str, Any], errors: list[str]
) -> None:
    if metadata.get("required_ai_policy_marker") != AI_POLICY_MARKER:
        errors.append("contract metadata has an invalid AI policy marker")
    if metadata.get("required_ai_policy_doc_id") != AI_POLICY_DOC_ID:
        errors.append("contract metadata has an invalid AI policy doc_id")

    candidates = {repository_root / "AGENTS.md"}
    completed = subprocess.run(
        ["git", "ls-files", "*AGENTS.md"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        errors.append("cannot discover tracked AGENTS.md files")
        return
    candidates.update(repository_root / line for line in completed.stdout.splitlines())
    opening = f"<!-- {AI_POLICY_MARKER} -->"
    closing = f"<!-- /{AI_POLICY_MARKER} -->"
    for path in sorted(candidates):
        relative = path.relative_to(repository_root)
        if not path.is_file():
            errors.append(f"{relative}: required AI agent entry is missing")
            continue
        text = path.read_text(encoding="utf-8")
        if text.count(opening) != 1 or text.count(closing) != 1:
            errors.append(
                f"{relative}: AI-driven development policy marker is missing "
                "or duplicated"
            )
            continue
        block = text.split(opening, 1)[1].split(closing, 1)[0]
        expected_hash = metadata.get("ai_policy_block_sha256")
        if expected_hash is not None and hashlib.sha256(block.encode("utf-8")).hexdigest() != expected_hash:
            errors.append(f"{relative}: AI policy differs from the common canonical distribution")
        missing = [value for value in AI_POLICY_REQUIRED_TEXT if value not in block]
        if missing:
            errors.append(
                f"{relative}: AI-driven development policy block is incomplete: "
                + ", ".join(missing)
            )


def validate_build_check_contract(
    repository_root: Path, metadata: dict[str, Any], errors: list[str]
) -> None:
    if metadata.get("required_build_check_marker") != BUILD_CHECK_MARKER:
        errors.append("contract metadata has an invalid build check marker")
    if metadata.get("required_build_check_command") != BUILD_CHECK_COMMAND:
        errors.append("contract metadata has an invalid document guard command")

    build_check = repository_root / "scripts/build_check.sh"
    if not build_check.is_file():
        errors.append("repository has no scripts/build_check.sh")
        return
    text = build_check.read_text(encoding="utf-8")
    if BUILD_CHECK_MARKER not in text:
        errors.append(
            "scripts/build_check.sh is missing the document governance marker"
        )
    executable_lines = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if BUILD_CHECK_COMMAND not in executable_lines:
        errors.append(
            "scripts/build_check.sh does not invoke the document governance guard"
        )
    if QUALITY_PLAN_MARKER not in text or "--auto" not in text or "--plan" not in text:
        errors.append(
            "scripts/build_check.sh does not expose the required quality plan handoff"
        )


def validate_github_actions_usage(repository_root: Path, errors: list[str]) -> None:
    """Keep repository quality checks local and outside GitHub-hosted runners."""
    workflows = repository_root / ".github/workflows"
    if not workflows.is_dir():
        return
    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        required_signature = ALLOWED_GITHUB_ACTIONS_WORKFLOWS.get(path.name)
        relative = path.relative_to(repository_root)
        if required_signature is None:
            errors.append(
                f"{relative}: GitHub Actions workflow is outside the absolute "
                "production image/deploy allowlist"
            )
        elif required_signature not in text.lower():
            errors.append(
                f"{relative}: allowed GitHub Actions workflow is missing its "
                f"production release signature: {required_signature}"
            )
        if re.search(r"(?m)^\s+(?:pull_request|schedule):", text):
            errors.append(
                f"{relative}: pull_request/schedule GitHub Actions triggers "
                "are forbidden"
            )
        lines = text.splitlines()
        for line_number, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            command = next(
                (
                    value
                    for value in FORBIDDEN_GITHUB_ACTIONS_QUALITY_COMMANDS
                    if value in line
                ),
                None,
            )
            if command is None:
                continue
            errors.append(
                f"{relative}:{line_number}: GitHub Actions must not invoke {command}; "
                "run repository quality checks locally before commit/push"
            )


def validate_retired_metadata_templates(
    repository_root: Path, errors: list[str]
) -> None:
    """Reject retired frontmatter literals before a generator can recreate them."""
    excluded_parts = {
        ".git",
        ".next",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "vendor",
    }
    for path in repository_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(repository_root)
        if excluded_parts.intersection(relative.parts):
            continue
        is_agent_instruction = path.name == "AGENTS.md"
        is_root_readme = relative == Path("README.md")
        is_source_template = (
            "scripts" in relative.parts
            and path.suffix.lower() in SOURCE_TEMPLATE_SUFFIXES
        )
        if not (is_agent_instruction or is_root_readme or is_source_template):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if is_agent_instruction:
            match = re.search(r"\bsource_docs\b", text)
        else:
            match = RETIRED_SOURCE_DOCS_LITERAL_PATTERN.search(text)
        if match is None:
            continue
        line = text.count("\n", 0, match.start()) + 1
        errors.append(
            f"{relative}:{line}: retired source_docs metadata template/instruction; "
            "use source_doc_ids and store referenced frontmatter doc_id values only"
        )


ALLOWED_TOP_LEVEL = {
    "_governance",
    "changes",
    "decisions",
    "evidence",
    "generated",
    "plans",
    "references",
    "runbooks",
    "specs",
    "status",
    "templates",
}
KIND_DIRECTORIES = {
    "decision": "decisions",
    "evidence": "evidence",
    "generated": "generated",
    "plan": "plans",
    "reference": "references",
    "runbook": "runbooks",
    "spec": "specs",
    "status": "status",
    "template": "templates",
}
FORBIDDEN_NAMES = {".DS_Store"}
FORBIDDEN_SUFFIXES = {
    ".bak",
    ".env",
    ".key",
    ".old",
    ".orig",
    ".p12",
    ".pem",
    ".pfx",
    ".sql",
}
SKIP_PARTS = {".git", ".venv", "node_modules", "vendor"}


class ContractError(Exception):
    pass


def distribution_git(repository_root: Path, *arguments: str) -> bytes:
    # Production callers only inspect Git. Use the same system Git as lifecycle
    # checks; write authority and integration remain with the guarded runner.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    if os.environ.get("GIT_INDEX_FILE"):
        environment["GIT_INDEX_FILE"] = os.environ["GIT_INDEX_FILE"]
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(repository_root), *arguments],
        env=environment,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ContractError("cannot determine distribution profile from Git")
    return result.stdout


ADAPTER_SPEC_PREFIX = "# anshin-quality-plan-adapter-spec: "
GENERATED_HANDOFF_RE = re.compile(
    rb"\n?# anshin-quality-plan-handoff:v1\n.*?# /anshin-quality-plan-handoff:v1\n",
    re.DOTALL,
)
GENERATED_DISTRIBUTION_RE = re.compile(
    rb"\n?# anshin-document-distribution-profile:v1\n.*?# /anshin-document-distribution-profile:v1\n",
    re.DOTALL,
)
GENERATED_BUILD_BLOCKS_RE = re.compile(
    rb"\n?# anshin-quality-plan-handoff:v1\n.*?# /anshin-quality-plan-handoff:v1\n"
    rb"# anshin-document-distribution-profile:v1\n.*?# /anshin-document-distribution-profile:v1\n",
    re.DOTALL,
)
CORE_NATIVE_INIT_RE = re.compile(
    rb"# anshin-core-stored-plan-init:v1\n.*?# /anshin-core-stored-plan-init:v1\n",
    re.DOTALL,
)
CORE_NATIVE_COMPLETION_RE = re.compile(
    rb"# anshin-core-stored-plan-completion:v1\n.*?# /anshin-core-stored-plan-completion:v1\n",
    re.DOTALL,
)
CORE_NATIVE_EXECUTION_RE = re.compile(
    rb"# anshin-core-stored-plan-execution:v1\n.*?# /anshin-core-stored-plan-execution:v1\n",
    re.DOTALL,
)
CORE_NATIVE_SUCCESS_RE = re.compile(
    rb"# anshin-core-stored-plan-success:v1\n.*?# /anshin-core-stored-plan-success:v1\n",
    re.DOTALL,
)


def _strip_generated_build_blocks(base: bytes) -> bytes:
    base = GENERATED_BUILD_BLOCKS_RE.sub(b"\n", base)
    base = GENERATED_HANDOFF_RE.sub(b"\n", base)
    return GENERATED_DISTRIBUTION_RE.sub(b"\n", base)


def _strip_core_native_handoff(base: bytes) -> bytes:
    # Frontend stored-plan shims retain the existing native commands as anchors.
    front_init = b"""    AUTO_PLAN_FILE="$(mktemp)"
    trap 'rm -f "${AUTO_PLAN_FILE:-}"' EXIT
    node apps/anshin-frontend/scripts/select-build-check.js --root-quality-plan > "$AUTO_PLAN_FILE"
"""
    base = re.sub(
        rb"(?ms)^# anshin-frontend-stored-plan-init:v1\n.*?^# /anshin-frontend-stored-plan-init:v1\n",
        lambda _m: front_init,
        base,
    )
    base = re.sub(
        rb"(?ms)^# anshin-frontend-stored-plan-execution:v1\n.*?^# /anshin-frontend-stored-plan-execution:v1\n",
        lambda m: (
            b'      *) node apps/anshin-frontend/scripts/select-build-check.js --execute-root "$selected_id" ;;\n'
            if b"$selected_id" in m[0]
            else re.search(
                rb"(?m)^ *node apps/anshin-frontend/scripts/select-build-check.js --execute-root [^\n]+\n",
                m[0],
            )[0]
        ),
        base,
    )
    base = re.sub(
        rb"(?ms)^# anshin-frontend-stored-plan-(?:policy|success):v1\n.*?^# /anshin-frontend-stored-plan-(?:policy|success):v1\n",
        b"",
        base,
    )
    marker_counts = {
        "initialization": (
            base.count(b"# anshin-core-stored-plan-init:v1"),
            base.count(b"# /anshin-core-stored-plan-init:v1"),
            1,
        ),
        "completion": (
            base.count(b"# anshin-core-stored-plan-completion:v1"),
            base.count(b"# /anshin-core-stored-plan-completion:v1"),
            2,
        ),
        "execution": (
            base.count(b"# anshin-core-stored-plan-execution:v1"),
            base.count(b"# /anshin-core-stored-plan-execution:v1"),
            2,
        ),
        "success": (
            base.count(b"# anshin-core-stored-plan-success:v1"),
            base.count(b"# /anshin-core-stored-plan-success:v1"),
            1,
        ),
    }
    if any(begin or end for begin, end, _expected in marker_counts.values()):
        for name, (begin, end, expected) in marker_counts.items():
            if begin != expected or end != expected:
                raise ContractError(f"generated Core {name} block count differs")
    initialization = b'MODE="full"\nAUTO_ACTIVE=0\nAUTO_CHECK_IDS=()\n'
    execution = b'        "$PREFLIGHT_PYTHON" scripts/select_ai_targeted_tests.py --execution "$check_id"\n'
    success = b"printf '%s\\n' \"[build_check] OK\"\n"
    base = CORE_NATIVE_INIT_RE.sub(lambda _match: initialization, base)
    base = CORE_NATIVE_COMPLETION_RE.sub(lambda _match: b"", base)
    base = CORE_NATIVE_EXECUTION_RE.sub(lambda _match: execution, base)
    return CORE_NATIVE_SUCCESS_RE.sub(lambda _match: success, base)


def _adapter_spec_bytes(spec: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(_quality_plan_json(spec)).decode("ascii")


def _adapter_spec_from_build(build: bytes) -> dict[str, Any]:
    for raw_line in build.decode("utf-8", errors="strict").splitlines():
        if raw_line.startswith(ADAPTER_SPEC_PREFIX):
            try:
                value = json.loads(
                    base64.urlsafe_b64decode(
                        raw_line[len(ADAPTER_SPEC_PREFIX) :].encode("ascii")
                    )
                )
            except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                raise ContractError("build-check adapter metadata is invalid") from exc
            legacy_keys = {
                "kind",
                "invocation",
                "selector",
                "plan_args",
                "execution_args",
            }
            if not isinstance(value, dict) or set(value) not in {
                frozenset(legacy_keys),
                frozenset(legacy_keys | {"dependencies"}),
            }:
                raise ContractError("build-check adapter metadata is invalid")
            if "dependencies" not in value:
                value["dependencies"] = [value["selector"]] if value["selector"] else []
            if value["dependencies"] != sorted(set(value["dependencies"])) or any(
                not isinstance(path, str)
                or not path
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                for path in value["dependencies"]
            ):
                raise ContractError("build-check adapter metadata is invalid")
            return value
    raise ContractError("build-check adapter metadata is missing")


def _legacy_invocation(base_hook: bytes | None) -> list[str]:
    if base_hook is None:
        return []
    invocations: list[list[str]] = []
    for raw_line in base_hook.decode("utf-8", errors="strict").splitlines():
        line = raw_line.strip()
        if "scripts/build_check.sh" not in line or line.startswith("#"):
            continue
        try:
            words = shlex.split(line)
        except ValueError as exc:
            raise ContractError(
                "pre-commit build-check invocation is ambiguous"
            ) from exc
        if "--documents-only" in words or "--auto" in words:
            continue
        try:
            index = words.index("scripts/build_check.sh")
        except ValueError as exc:
            raise ContractError(
                "pre-commit build-check invocation is ambiguous"
            ) from exc
        if index == 0 or words[index - 1] != "bash":
            raise ContractError("pre-commit build-check invocation is ambiguous")
        argv = words[index + 1 :]
        if argv and argv[-1] == ";;":
            argv = argv[:-1]
        if argv not in invocations:
            invocations.append(argv)
    if len(invocations) > 1:
        raise ContractError("pre-commit build-check invocation is ambiguous")
    return invocations[0] if invocations else []


def repository_adapter_spec(
    base: bytes, base_hook: bytes | None = None
) -> dict[str, Any]:
    """Describe the exact existing selector/executor without inventing a new one."""
    text = base.decode("utf-8", errors="strict")
    candidates: list[dict[str, Any]] = []
    core_selector = "scripts/select_ai_targeted_tests.py" in text
    if core_selector:
        if "--execution" not in text:
            raise ContractError("build-check native selector signature is partial")
        candidates.append(
            {
                "kind": "core-native",
                "invocation": [],
                "selector": "scripts/select_ai_targeted_tests.py",
                "dependencies": [
                    "config/quality_gate/heavy_test_inventory.json",
                    "scripts/select_ai_targeted_tests.py",
                ],
                "plan_args": ["--quality-plan", "auto"],
                "execution_args": ["--execution"],
            }
        )
    infrastructure_selector = "scripts/select_build_check.py --mode" in text
    python_selector = "scripts/select_build_check.py" in text
    if infrastructure_selector:
        candidates.append(
            {
                "kind": "legacy",
                "invocation": ["--auto"],
                "selector": "",
                "dependencies": [],
                "plan_args": [],
                "execution_args": [],
            }
        )
    elif python_selector:
        if "--execution" not in text:
            raise ContractError("build-check native selector signature is partial")
        adapter_marker = "adapter_" in text
        execution_kind_marker = "--execution-kind" in text
        if adapter_marker != execution_kind_marker:
            raise ContractError("build-check native selector signature is partial")
        candidates.append(
            {
                "kind": "build-focus" if adapter_marker else "selector-direct",
                "invocation": [],
                "selector": "scripts/select_build_check.py",
                "dependencies": ["scripts/select_build_check.py"],
                "plan_args": ["--profile", "auto"],
                "execution_args": ["--execution"],
            }
        )
    javascript_selector_paths: dict[str, list[list[str]]] = {
        "scripts/select-build-check.js": [],
        "apps/anshin-frontend/scripts/select-build-check.js": [],
    }
    for line in text.splitlines():
        if "select-build-check.js" not in line:
            continue
        try:
            words = shlex.split(line, comments=True)
        except ValueError as exc:
            raise ContractError(
                "build-check native selector signature is partial"
            ) from exc
        matches = [
            (index, word)
            for index, word in enumerate(words)
            if word in javascript_selector_paths
        ]
        if not words:
            continue
        if len(matches) != 1:
            raise ContractError("build-check native selector signature is partial")
        index, selector_path = matches[0]
        prefix = words[:index]
        is_syntax_check = len(prefix) >= 2 and prefix[-2:] == ["node", "--check"]
        if not prefix or not (prefix[-1] == "node" or is_syntax_check):
            raise ContractError("build-check native selector signature is partial")
        argv = words[index + 1 :]
        if is_syntax_check:
            if argv:
                raise ContractError("build-check native selector signature is partial")
            continue
        if argv and argv[-1] == ";;":
            argv = argv[:-1]
        if (
            len(argv) >= 2
            and argv[-2] == ">"
            and argv[-1]
            in {
                "$AUTO_PLAN_FILE",
                "/dev/null",
            }
        ):
            argv = argv[:-2]
        elif argv and argv[-1] == ">/dev/null":
            argv = argv[:-1]
        javascript_selector_paths[selector_path].append(argv)

    def validate_javascript_invocations(invocations: list[list[str]]) -> None:
        planner = [argv for argv in invocations if argv == ["--root-quality-plan"]]
        executor = [
            argv
            for argv in invocations
            if len(argv) == 2
            and argv[0] == "--execute-root"
            and argv[1]
            and not argv[1].startswith("--")
        ]
        if (
            len(planner) + len(executor) != len(invocations)
            or not planner
            or not executor
        ):
            raise ContractError("build-check native selector signature is partial")

    root_javascript_invocations = javascript_selector_paths[
        "scripts/select-build-check.js"
    ]
    if root_javascript_invocations:
        validate_javascript_invocations(root_javascript_invocations)
        candidates.append(
            {
                "kind": "build-focus",
                "invocation": [],
                "selector": "scripts/select-build-check.js",
                "dependencies": ["scripts/select-build-check.js"],
                "plan_args": ["--root-quality-plan", "--"],
                "execution_args": ["--execute-root"],
            }
        )
    if "scripts/build-check-plan.mjs" in text:
        candidates.append(
            {
                "kind": "legacy",
                "invocation": ["--fast"],
                "selector": "",
                "dependencies": [],
                "plan_args": [],
                "execution_args": [],
            }
        )
    frontend_markers = (
        'elif [[ "$file" == apps/anshin-frontend/* ]]',
        "cd apps/anshin-frontend",
        'bash scripts/build_check.sh --fast "${APP_FILES[@]}"',
        "pnpm --dir apps/anshin-frontend run -s guard:build-check-references",
    )
    frontend_marker_presence = [marker in text for marker in frontend_markers]
    frontend_invocations = javascript_selector_paths[
        "apps/anshin-frontend/scripts/select-build-check.js"
    ]
    if frontend_invocations:
        validate_javascript_invocations(frontend_invocations)
    frontend_root = all(frontend_marker_presence)
    if (frontend_invocations and not frontend_root) or (
        any(frontend_marker_presence) and not frontend_root
    ):
        raise ContractError("build-check native selector signature is partial")
    if frontend_root:
        candidates.append(
            {
                "kind": "frontend-root",
                "invocation": [],
                "selector": "apps/anshin-frontend/scripts/select-build-check.js",
                "dependencies": sorted(
                    [
                        "apps/anshin-frontend/scripts/build_check.sh",
                        "apps/anshin-frontend/scripts/select-build-check.js",
                    ]
                    + (
                        [
                            "apps/anshin-frontend/scripts/build-check.config.json",
                            "apps/anshin-frontend/scripts/build-check-plan.js",
                        ]
                        if frontend_invocations
                        else []
                    )
                ),
                "plan_args": ["--root-quality-plan"] if frontend_invocations else [],
                "execution_args": [],
            }
        )
    if len(candidates) > 1:
        raise ContractError("build-check native selector signature is ambiguous")
    if candidates:
        return candidates[0]
    marketing_markers = (
        'MODE="${1:---full}"',
        "--full|--fast|--documents-only",
        "tests.test_marketing_retirement_guard tests.test_release_impact",
        'if [[ "$MODE" == "--full" ]]; then',
        "bash tests/test_marketing_retirement_integration.sh",
    )
    if all(marker in text for marker in marketing_markers):
        return {
            "kind": "marketing-legacy",
            "invocation": [],
            "selector": "",
            "dependencies": [],
            "plan_args": [],
            "execution_args": [],
        }
    return {
        "kind": "legacy",
        "invocation": _legacy_invocation(base_hook),
        "selector": "",
        "dependencies": [],
        "plan_args": [],
        "execution_args": [],
    }


def _frontend_stored_plan_adapter(generated: bytes) -> bytes:
    def replace_once(anchor: bytes, replacement: bytes) -> None:
        nonlocal generated
        if generated.count(anchor) != 1:
            raise ContractError("Frontend native stored-plan anchor differs")
        generated = generated.replace(anchor, replacement, 1)

    replace_once(
        b"    local distribution_rc=$?\n",
        b'    local distribution_rc="${1:-$?}"\n',
    )
    initialization = b"""    AUTO_PLAN_FILE="$(mktemp)"
    trap 'rm -f "${AUTO_PLAN_FILE:-}"' EXIT
    node apps/anshin-frontend/scripts/select-build-check.js --root-quality-plan > "$AUTO_PLAN_FILE"
"""
    replacement = rb"""# anshin-frontend-stored-plan-init:v1
    AUTO_PLAN_FILE="$(mktemp)"
    if [[ "${DISTRIBUTION_FRONTEND_STORED_PLAN:-0}" == "1" ]]; then
      trap 'frontend_rc=$?; rm -f "${AUTO_PLAN_FILE:-}"; write_distribution_failure_result "$frontend_rc"' EXIT
      python3 - "$DISTRIBUTION_PLAN_PATH" > "$AUTO_PLAN_FILE" <<'PY'
import json,subprocess,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
tree=subprocess.check_output(["git","write-tree"],text=True).strip()
clean=subprocess.run(["git","diff","--quiet","--"],check=False).returncode==0 and not subprocess.check_output(["git","ls-files","--others","--exclude-standard","-z"])
print(json.dumps({"checks":p["selected_checks"],"rootFullRisk":p["requires_full"],"candidate":{"exactCandidate":clean,"executableTree":tree if clean else None,"qualification":False}}))
PY
      DISTRIBUTION_COMPLETED_CHECK_IDS=()
      DISTRIBUTION_CURRENT_CHECK_ID="root-local-quality-policy"
    else
      trap 'rm -f "${AUTO_PLAN_FILE:-}"' EXIT
      node apps/anshin-frontend/scripts/select-build-check.js --root-quality-plan > "$AUTO_PLAN_FILE"
    fi
# /anshin-frontend-stored-plan-init:v1
"""
    replace_once(initialization, replacement)
    policy_end = b"PY\n\nfor root_check in root-workflow-policy"
    policy_state = rb"""# anshin-frontend-stored-plan-policy:v1
if [[ "${DISTRIBUTION_FRONTEND_STORED_PLAN:-0}" == "1" ]]; then
  DISTRIBUTION_COMPLETED_CHECK_IDS+=("root-local-quality-policy")
  DISTRIBUTION_CURRENT_CHECK_ID=""
fi
# /anshin-frontend-stored-plan-policy:v1
"""
    replace_once(
        policy_end, b"PY\n\n" + policy_state + b"for root_check in root-workflow-policy"
    )
    execution = rb'(?m)^([ ]*)node apps/anshin-frontend/scripts/select-build-check.js --execute-root "\$(root_check)"\n'

    def execution_state(match: re.Match[bytes]) -> bytes:
        indent, variable = match[1], match[2]
        return (
            b"# anshin-frontend-stored-plan-execution:v1\n"
            + indent
            + b'if [[ "${DISTRIBUTION_FRONTEND_STORED_PLAN:-0}" == "1" ]]; then DISTRIBUTION_CURRENT_CHECK_ID="$'
            + variable
            + b'"; fi\n'
            + match[0]
            + indent
            + b'if [[ "${DISTRIBUTION_FRONTEND_STORED_PLAN:-0}" == "1" ]]; then DISTRIBUTION_COMPLETED_CHECK_IDS+=("$'
            + variable
            + b'"); DISTRIBUTION_CURRENT_CHECK_ID=""; fi\n'
            + b"# /anshin-frontend-stored-plan-execution:v1\n"
        )

    generated, count = re.subn(execution, execution_state, generated)
    if count != 2:
        raise ContractError("Frontend native execution anchors differ")
    selected = b'      *) node apps/anshin-frontend/scripts/select-build-check.js --execute-root "$selected_id" ;;\n'
    selected_state = b"""# anshin-frontend-stored-plan-execution:v1
      *) if [[ "${DISTRIBUTION_FRONTEND_STORED_PLAN:-0}" == "1" ]]; then DISTRIBUTION_CURRENT_CHECK_ID="$selected_id"; fi;
         node apps/anshin-frontend/scripts/select-build-check.js --execute-root "$selected_id";
         if [[ "${DISTRIBUTION_FRONTEND_STORED_PLAN:-0}" == "1" ]]; then DISTRIBUTION_COMPLETED_CHECK_IDS+=("$selected_id"); DISTRIBUTION_CURRENT_CHECK_ID=""; fi ;;
# /anshin-frontend-stored-plan-execution:v1
"""
    replace_once(selected, selected_state)
    success = rb"""# anshin-frontend-stored-plan-success:v1
  if [[ "${DISTRIBUTION_FRONTEND_STORED_PLAN:-0}" == "1" ]]; then
    if [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
      python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed
      DISTRIBUTION_RESULT_WRITTEN=1
    fi
    rm -f "${AUTO_PLAN_FILE:-}"
    trap - EXIT
  fi
# /anshin-frontend-stored-plan-success:v1
"""
    for mode in (b"--full", b"--auto"):
        anchor = b'  echo "[build_check] OK mode=' + mode + b'"\n'
        replace_once(anchor, success + anchor)
    return generated


def distribution_adapter(base: bytes, base_hook: bytes | None = None) -> bytes:
    handoff_count = base.count(b"# anshin-quality-plan-handoff:v1")
    handoff_end_count = base.count(b"# /anshin-quality-plan-handoff:v1")
    distribution_count = base.count(b"# anshin-document-distribution-profile:v1")
    distribution_end_count = base.count(b"# /anshin-document-distribution-profile:v1")
    if (
        handoff_count != handoff_end_count
        or distribution_count != distribution_end_count
    ):
        raise ContractError("generated build-check block is incomplete")
    base = _strip_core_native_handoff(_strip_generated_build_blocks(base))
    anchor = b'\ncd "$ROOT_DIR"\n'
    if base.count(anchor) != 1:
        raise ContractError("build check has no unique repository-root entry")
    spec = repository_adapter_spec(base, base_hook)
    dependencies = spec["dependencies"]
    native_branch = ""
    internal_guard = ""
    if spec["kind"] == "frontend-root" and spec["plan_args"] == ["--root-quality-plan"]:
        internal_guard = """if [[ -n "${DISTRIBUTION_FRONTEND_STORED_PLAN+x}${DISTRIBUTION_PLAN_PATH+x}${DISTRIBUTION_COMPLETED_CHECK_IDS+x}${DISTRIBUTION_CURRENT_CHECK_ID+x}" ]]; then
  printf '%s\\n' "[build_check:auto] ERROR: internal stored-plan state was supplied by the caller" >&2
  exit 2
fi
"""
        native_branch = """  elif [[ "$DISTRIBUTION_PROFILE" == "repository-native" ]]; then
    DISTRIBUTION_FRONTEND_STORED_PLAN=1
    set -- --auto
"""
    elif spec["kind"] == "core-native":
        internal_guard = """if [[ -n "${DISTRIBUTION_CORE_STORED_PLAN+x}${DISTRIBUTION_PLAN_PATH+x}${DISTRIBUTION_COMPLETED_CHECK_IDS+x}${DISTRIBUTION_CURRENT_CHECK_ID+x}" ]]; then
  printf '%s\\n' "[build_check:auto] ERROR: internal stored-plan state was supplied by the caller" >&2
  exit 2
fi
"""
        native_branch = """  elif [[ "$DISTRIBUTION_PROFILE" == "repository-native" ]]; then
    DISTRIBUTION_CORE_STORED_PLAN=1
"""
    adapter = (
        DISTRIBUTION_BUILD_ADAPTER_TEMPLATE.replace(
            "{adapter_metadata}", ADAPTER_SPEC_PREFIX + _adapter_spec_bytes(spec)
        )
        .replace("{native_plan_branch}", native_branch)
        .replace("{internal_guard}", internal_guard)
        .replace(
            "{native_dependencies}",
            "\n".join(
                f"# anshin-quality-plan-dependency: {path}" for path in dependencies
            ),
        )
        .encode()
        .lstrip(b"\n")
    )
    generated = base.replace(anchor, anchor + adapter, 1)
    if spec["kind"] == "core-native":
        initialization = b'MODE="full"\nAUTO_ACTIVE=0\nAUTO_CHECK_IDS=()\n'
        replacement = (
            b"# anshin-core-stored-plan-init:v1\n"
            + initialization
            + rb"""if [[ "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" ]]; then
  AUTO_PLAN="$(cat -- "$DISTRIBUTION_PLAN_PATH")"
  AUTO_INDEX_TREE="$(git write-tree)"
  while IFS= read -r check_id; do AUTO_CHECK_IDS+=("$check_id"); done < <(python3 -c 'import json,sys;[print(v) for v in json.load(open(sys.argv[1],encoding="utf-8"))["selected_checks"]]' "$DISTRIBUTION_PLAN_PATH")
  AUTO_PATHS=()
  while IFS= read -r -d '' path_arg; do AUTO_PATHS+=("$path_arg"); done < <(python3 -c 'import json,sys;[sys.stdout.buffer.write(v.encode()+b"\0") for v in json.load(open(sys.argv[1],encoding="utf-8"))["paths"]]' "$DISTRIBUTION_PLAN_PATH")
  [[ ${#AUTO_CHECK_IDS[@]} -gt 0 && ( " ${AUTO_CHECK_IDS[*]} " == *" core-full-static "* || " ${AUTO_CHECK_IDS[*]} " == *" core-fast "* ) ]] || { printf '%s\n' "[build_check:auto] ERROR: stored Core plan is incomplete" >&2; exit 2; }
  if [[ " ${AUTO_CHECK_IDS[*]} " == *" core-full-static "* ]]; then MODE="full-static"; else MODE="fast"; fi
  AUTO_ACTIVE=1
  DISTRIBUTION_COMPLETED_CHECK_IDS=()
  if [[ "$MODE" == "fast" ]]; then
    DISTRIBUTION_CURRENT_CHECK_ID="core-fast"
    set -- "${AUTO_PATHS[@]}"
  else
    DISTRIBUTION_CURRENT_CHECK_ID="core-full-static"
    set --
  fi
fi
"""
            + b"# /anshin-core-stored-plan-init:v1\n"
        )
        if generated.count(initialization) != 1:
            raise ContractError("Core build-check initialization anchor differs")
        generated = generated.replace(initialization, replacement, 1)
        for aggregate, check_id in (
            (b"  printf '%s\\n' \"[build_check:fast] OK\"\n", b"core-fast"),
            (b'elif [ "$AUTO_ACTIVE" = "1" ]; then\n', b"core-full-static"),
        ):
            if generated.count(aggregate) != 1:
                raise ContractError("Core aggregate completion anchor differs")
            completion = (
                aggregate
                + b"# anshin-core-stored-plan-completion:v1\n"
                + b'  if [[ " ${AUTO_CHECK_IDS[*]} " == *" '
                + check_id
                + b' "* ]]; then\n'
                + b'    DISTRIBUTION_COMPLETED_CHECK_IDS+=("'
                + check_id
                + b'")\n'
                + b'    DISTRIBUTION_CURRENT_CHECK_ID=""\n'
                + b"  fi\n"
                + b"# /anshin-core-stored-plan-completion:v1\n"
            )
            generated = generated.replace(aggregate, completion, 1)
        execution = b'        "$PREFLIGHT_PYTHON" scripts/select_ai_targeted_tests.py --execution "$check_id"\n'
        execution_with_state = (
            b"# anshin-core-stored-plan-execution:v1\n"
            + b'        DISTRIBUTION_CURRENT_CHECK_ID="$check_id"\n'
            + execution
            + b'        DISTRIBUTION_COMPLETED_CHECK_IDS+=("$check_id")\n'
            + b'        DISTRIBUTION_CURRENT_CHECK_ID=""\n'
            + b"# /anshin-core-stored-plan-execution:v1\n"
        )
        if generated.count(execution) != 2:
            raise ContractError("Core selected-check execution anchor differs")
        generated = generated.replace(execution, execution_with_state)
        success = b"printf '%s\\n' \"[build_check] OK\"\n"
        success_replacement = rb"""# anshin-core-stored-plan-success:v1
if [[ "${DISTRIBUTION_CORE_STORED_PLAN:-0}" == "1" ]]; then
  [[ "$(git write-tree)" == "$AUTO_INDEX_TREE" ]] || { printf '%s\n' "[build_check:auto] ERROR: index tree changed during verification" >&2; exit 1; }
  git diff --quiet -- || { printf '%s\n' "[build_check:auto] ERROR: working tree changed during verification" >&2; exit 1; }
  [[ -z "$(git ls-files --others --exclude-standard)" ]] || { printf '%s\n' "[build_check:auto] ERROR: untracked input appeared during verification" >&2; exit 1; }
  if [[ -n "${DISTRIBUTION_RESULT_PATH:-}" ]]; then
    python3 scripts/document_governance_portable.py --repository-root "$ROOT_DIR" --write-build-check-result "$DISTRIBUTION_PLAN_PATH" "$DISTRIBUTION_RESULT_PATH" passed
    DISTRIBUTION_RESULT_WRITTEN=1
  fi
  trap - EXIT
  printf '%s\n' "[build_check] OK mode=--auto"
else
  printf '%s\n' "[build_check] OK"
fi
# /anshin-core-stored-plan-success:v1
"""
        if generated.count(success) != 1:
            raise ContractError("Core build-check success anchor differs")
        generated = generated.replace(success, success_replacement, 1)
    if spec["kind"] == "frontend-root" and spec["plan_args"] == ["--root-quality-plan"]:
        generated = _frontend_stored_plan_adapter(generated)
    return generated


DISTRIBUTION_BROWSER_LINES = [
    [
        "- headless / 別 profile / in-app browser / token 注入だけで完全準拠確認済みと報告してはいけない。",
        "- headless / 別 profile / token 注入だけで完全準拠確認済みと報告してはいけない。",
    ],
    [
        "## Chrome ChatGPT 拡張による画面確認",
        "## 右サイドのin-app browserによる画面確認",
    ],
    [
        "## Google Drive / Google Docs / Google Sheets の Chrome 正本tab",
        "## Google Drive / Google Docs / Google Sheets の in-app browser正本tab",
    ],
    ["### Anshin app の Chrome 正本tab", "### Anshin app の in-app browser正本tab"],
    ["### Chrome 比較確認", "### in-app browser比較確認"],
    [
        "- ChatGPT 拡張が使えない、対象 URL を開けない、ログイン状態が確認できない場合は、代替手段へ切り替えず停止して報告する。",
        "- 右サイドのin-app browserが使えない、対象 URL を開けない、ログイン状態が確認できない場合は、代替手段へ切り替えず停止して報告する。",
    ],
    ["- Chrome 比較確認の結果", "- in-app browser比較確認の結果"],
    [
        "- Google Drive、Google Docs又はGoogle SheetsをChromeで扱う前に、全live Chrome extension instanceと、各instanceの全`browser.user.openTabs()`を確認する。最初の1instance又は`browser.tabs.list()`だけで全Chromeを確認済みと判定してはいけない。",
        "- Google Drive、Google Docs又はGoogle Sheetsをブラウザで扱う前に、右サイドのin-app browserの全open tabを確認する。一部のtabだけで全体を確認済みと判定してはいけない。",
    ],
    [
        "- OAuth connectorとChrome loginを混同しない。回答には確認したinstance数、候補tab数、対象ID、画面上のaccountメール及び4段階の結果を区別して記載する。",
        "- OAuth connectorとin-app browser loginを混同しない。回答には確認したinstance数、候補tab数、対象ID、画面上のaccountメール及び4段階の結果を区別して記載する。",
    ],
    [
        "- `auth.anshin.care` のKeycloak画面、Chromeのprofile名・avatar、URL一致、ChatGPT拡張の接続状態だけでは `h@anshin.care` の正本証明にならない。",
        "- `auth.anshin.care` のKeycloak画面、ブラウザの表示名・avatar、URL一致、ブラウザの接続状態だけでは `h@anshin.care` の正本証明にならない。",
    ],
    [
        "- `https://app.anshin.care/...` または `http://localhost:3010/...` の画面確認を始める前に、Chrome ChatGPT拡張で確認できる全接続instance・全open tabを列挙し、対象hostが一致し、かつ画面内に `h@anshin.care` が表示されているtabを正本候補にする。",
        "- `https://app.anshin.care/...` または `http://localhost:3010/...` の画面確認を始める前に、右サイドのin-app browserで確認できる全open tabを列挙し、対象hostが一致し、かつ画面内に `h@anshin.care` が表示されているtabを正本候補にする。",
    ],
    [
        "- localhost の画面確認・画面テスト・スクリーンショット確認は、必ず app-local rule に従い、ユーザーが起動している Chrome の ChatGPT 拡張を使う。Playwright / CDP / headless / 別 profile / in-app browser / token 注入 / 認証 state 生成だけで確認済みにしない。",
        "- localhost の画面確認・画面テスト・スクリーンショット確認は、必ず app-local rule に従い、右サイドのin-app browserを使う。Playwright / CDP / headless / 別 profile / token 注入 / 認証 state 生成だけで確認済みにしない。",
    ],
    [
        "- ユーザーが `pnpm dev` などで起動した Chrome・localhost を正本にする。画面確認では Chrome の ChatGPT 拡張を使い、ユーザー指定の URL と port をそのまま開く。`127.0.0.1`、別 port、別 Chrome profile、Playwright / CDP / headless browser、in-app browser、token 注入へ置き換えない。",
        "- ユーザーが `pnpm dev` などで起動した localhost を正本にする。画面確認では右サイドのin-app browserを使い、ユーザー指定の URL と port をそのまま開く。`127.0.0.1`、別 port、別 browser profile、Playwright / CDP / headless browser、token 注入へ置き換えない。",
    ],
    [
        "- ユーザー指定 URL と port をそのまま開く。`localhost` を `127.0.0.1` に変えない。別 port、別 Chrome profile、Playwright / CDP / headless browser、in-app browser、token 注入へ置き換えない。",
        "- ユーザー指定 URL と port をそのまま開く。`localhost` を `127.0.0.1` に変えない。別 port、別 browser profile、Playwright / CDP / headless browser、token 注入へ置き換えない。",
    ],
    [
        "- 値はtool出力、ログ、スクリーンショット、報告、test fixture、生成物へ表示・転記せず、Chrome ChatGPT拡張の対象フォームへ直接入力する用途だけに使う。`.env` 自体は編集・生成・commitしてはいけない。",
        "- 値はtool出力、ログ、スクリーンショット、報告、test fixture、生成物へ表示・転記せず、右サイドのin-app browserの対象フォームへ直接入力する用途だけに使う。`.env` 自体は編集・生成・commitしてはいけない。",
    ],
    [
        "- 既存production app tabが0件でもlive extension instanceが一意なら、そのinstanceで`app.anshin.care`を開いてよい。sign-inへ到達した場合は同じtabでGoogle loginを開始し、`h@anshin.care`を選択する。callback後に画面内`h@anshin.care`を再確認して正本tabを確定し、依頼済み本番確認を続行する。別accountが表示された場合だけ停止する。",
        "- 既存production app tabが0件でもin-app browser sessionが一意なら、そのsessionで`app.anshin.care`を開いてよい。sign-inへ到達した場合は同じtabでGoogle loginを開始し、`h@anshin.care`を選択する。callback後に画面内`h@anshin.care`を再確認して正本tabを確定し、依頼済み本番確認を続行する。別accountが表示された場合だけ停止する。",
    ],
    [
        "- 正本tabを特定する前に、新しいChrome window / tabを作成したり、別profileへ切り替えたり、対象tabを遷移・reload・ログアウト・ログインしたりしてはいけない。別profile・別accountのtabを代用しない。",
        "- 正本tabを特定する前に、新しいbrowser tabを作成したり、別profileへ切り替えたり、対象tabを遷移・reload・ログアウト・ログインしたりしてはいけない。別profile・別accountのtabを代用しない。",
    ],
    [
        "- 画面確認・画面テスト・スクリーンショット確認の正本は、ユーザーが起動している Chrome の ChatGPT 拡張である。",
        "- 画面確認・画面テスト・スクリーンショット確認の正本は、右サイドのin-app browserである。",
    ],
    [
        "10. focused test、guard、実画面確認の手順と残リスク。Anshin frontend / customerの画面確認はChrome ChatGPT拡張を正本にする。",
        "10. focused test、guard、実画面確認の手順と残リスク。Anshin frontend / customerの画面確認は右サイドのin-app browserを正本にする。",
    ],
    [
        "backend source、generated、Python library、Docker runtimeの変更をアンシンアプリ実画面で確認する場合は、focused checkと必要なlocal migrationの後、Chrome確認より先にinfra正本 `/Users/matsumotoyuuji/dev/anshin/sh/rebuild_local.sh` を実行する。",
        "backend source、generated、Python library、Docker runtimeの変更をアンシンアプリ実画面で確認する場合は、focused checkと必要なlocal migrationの後、in-app browser確認より先にinfra正本 `/Users/matsumotoyuuji/dev/anshin/sh/rebuild_local.sh` を実行する。",
    ],
    [
        "実装後は `差分・mode選択 → focused check / migration → rebuild → /healthz log確認 → Chrome ChatGPT拡張で画面確認 → 原因層を切り分けて根本修正 → focused checkから再実行` を1サイクルとする。API 5xx、backend log、migration head、OpenAPI / generated同期、library反映を確認せずUIだけを修正しない。正本の詳細手順は `/Users/matsumotoyuuji/dev/anshin/AGENTS.md` の `anshin-local-screen-pdca:v1` とする。",
        "実装後は `差分・mode選択 → focused check / migration → rebuild → /healthz log確認 → 右サイドのin-app browserで画面確認 → 原因層を切り分けて根本修正 → focused checkから再実行` を1サイクルとする。API 5xx、backend log、migration head、OpenAPI / generated同期、library反映を確認せずUIだけを修正しない。正本の詳細手順は `/Users/matsumotoyuuji/dev/anshin/AGENTS.md` の `anshin-local-screen-pdca:v1` とする。",
    ],
    [
        "画面確認が必要な場合は、Chrome ChatGPT 拡張で次を確認する。",
        "画面確認が必要な場合は、右サイドのin-app browserで次を確認する。",
    ],
]

RELEASE_PLAN_ROUTING_BLOCK = """<!-- anshin-release-plan-gate:v2 -->

## Production Release routing

Production releaseの正本はcanonical doc_id `anshin.release.contract`及び対象repositoryのrunbookとする。本書へ運用本文を複製せず、`NOOP / CONTROL_PLANE_ONLY / DEPLOY / BLOCK`、fixed artifact、owner acceptance、rollback及び既存registered ownerを正本から適用する。

"""

INVESTIGATION_REPORTING_BLOCK = """<!-- anshin-investigation-result-gate:v1 -->

## 調査結果の報告

調査はcanonical doc_id `anshin.governance.ai-driven-development`に従い、結論、証拠、影響、未確認事項及び次actionを通常の回答で返す。既存`investigation_report_gate.py`は明示されたmachine-readable成果物の検査にだけ使い、通常回答の必須JSON gate又は不存在のguideを要求しない。

"""

CURRENT_AGENT_MODEL_RULE = "- 利用者がmodelを明示した場合、primary writerとhigh又はcritical変更の独立reviewはその指定を使用する。指定がない場合は利用可能な現行Sol系modelを`high`で使用する。実model labelは証跡へそのまま記録し、point releaseを推測しない。"

ACTIVE_AGENT_LITERAL_REPLACEMENTS = (
    (
        "- Lunaを唯一のwriterとし、Solは複雑設計と独立reviewに限定する。",
        CURRENT_AGENT_MODEL_RULE,
    ),
    (
        "- primary writerはGPT-5.6 Sol `high`とし、high又はcritical変更の独立reviewは別sessionのSol `high`が担当する。",
        CURRENT_AGENT_MODEL_RULE,
    ),
    (
        "最優先: `high`又は`critical`変更は、ownerの仕様承認、change contract及び独立AI reviewを必須とし、重大指摘が解消又はowner判断されるまで完了としてはいけない。",
        "最優先: `high`又は`critical`変更は、change contract及び独立AI reviewを必須とし、重大指摘が解消されるまで完了としてはいけない。通常開発の事前owner承認はUI/UX詳細設計だけに限定する。",
    ),
    (
        "最優先: `.env` 系ファイルは全て Git ignore 対象にする。各 repo の `.gitignore` には少なくとも `*.env*` と `.env*` を含め、不足している場合は `.env` 本体ではなく ignore 設定を修正する。`.env` 系ファイルを新規 tracking してはいけない。既に tracked されている場合は commit / push 前に secret を表示せず停止し、ユーザーへ除外方針を確認する。",
        "最優先: secretを含むruntimeの`.env`及び`.env.*`はGit ignoreを維持し、値を表示又は追跡しない。repositoryが正本とする既知の`.env.example`、`.env.*.example`又は`.env*.sample`はsecret-freeを確認した場合だけ追跡できる。",
    ),
    (
        "- `.env*`は作成・編集・追跡しない。`.gitignore`の`.env*`と`*.env*`を維持する。",
        "- secretを含むruntimeの`.env`及び`.env.*`は作成・追跡せずGit ignoreを維持する。repository正本の既知のexample/sampleはsecret-freeを確認した場合だけ追跡できる。",
    ),
    (
        "- `.env*` は作成・編集・追跡しない。`.gitignore` の `.env*` と `*.env*` を維持する。",
        "- secretを含むruntimeの`.env`及び`.env.*`は作成・追跡せずGit ignoreを維持する。repository正本の既知のexample/sampleはsecret-freeを確認した場合だけ追跡できる。",
    ),
    (
        "| E2E / Playwright / ブラウザ確認 / API smoke を行う | 10秒 timeout |",
        "| E2E / Playwright / ブラウザ確認 / API smoke を行う | 既存operation又はtest ownerのtimeoutとreadiness契約 |",
    ),
    (
        "単一の API 応答、health check、URL 遷移、ボタン有効化、dashboard 表示、メール到着待ちの上限を10秒にする。10秒で反応が無ければバグ・環境不全・前提未達として停止し、ユーザーから「失敗したらすぐ言え」と指示されたテストでは追加調査せず「失敗した / 失敗箇所 / 理由 / 次に直す対象」だけ報告する。",
        "API応答、health check、URL遷移、UI readiness及び外部待機は、実consumerを所有する既存operation又はtestのtimeoutを使う。一律10秒へ上書きせず、失敗時は実測した失敗箇所、理由及び次に直す対象を報告する。",
    ),
)


def migrate_active_agent_policy(text: str) -> str:
    for old, new in ACTIVE_AGENT_LITERAL_REPLACEMENTS:
        text = text.replace(old, new)
    for old, new in (
        ("Chrome ChatGPT 拡張", "右サイドのin-app browser"),
        ("Chrome ChatGPT拡張", "右サイドのin-app browser"),
        ("Chrome の ChatGPT 拡張", "右サイドのin-app browser"),
        ("ChromeのChatGPT拡張", "右サイドのin-app browser"),
        ("Chrome extension instance", "in-app browser session"),
        ("Chrome profile", "browser profile"),
        (
            "開いた後は全live in-app browser sessionの`browser.user.openTabs()`を再取得し、完全一致tabを直前の結果からclaimして、account、権限及び編集モードを再確認する。",
            "開いた後は右サイドin-app browserのopen tabを再確認し、完全一致tabのaccount、権限及び編集モードを確認する。",
        ),
        (
            "候補tabは直前の`openTabs()`結果からclaimし、",
            "候補tabは右サイドin-app browserのopen tabから選び、",
        ),
    ):
        text = text.replace(old, new)
    text = re.sub(
        r"(?s)<!-- anshin-investigation-result-gate:v1 -->.*?(?=<!-- anshin-release-plan-gate:v2 -->)",
        INVESTIGATION_REPORTING_BLOCK,
        text,
    )
    text = re.sub(
        r"(?s)<!-- anshin-release-plan-gate:v2 -->.*?(?=<!-- anshin-document-governance:v2 -->)",
        RELEASE_PLAN_ROUTING_BLOCK,
        text,
    )
    return text


def distribution_agents_adapter(base: bytes) -> bytes:
    replacements = {
        old.encode(): new.encode() for old, new in DISTRIBUTION_BROWSER_LINES
    }
    fixed = b"".join(
        replacements.get(line.rstrip(b"\n"), line.rstrip(b"\n"))
        + (b"\n" if line.endswith(b"\n") else b"")
        for line in base.splitlines(keepends=True)
    )
    migrated_text = migrate_active_agent_policy(fixed.decode("utf-8"))
    misplaced = f"\n{WORKSPACE_ROOT_EXPLANATION}\n\n## 専門用語一覧\n"
    if misplaced in migrated_text:
        migrated_text = migrated_text.replace(misplaced, "\n## 専門用語一覧\n", 1)
        glossary = re.search(r"(?s)(## 専門用語一覧\n\n(?:\|[^\n]*\n)+)", migrated_text)
        if glossary is None:
            raise ContractError("AGENTS glossary has no deterministic table boundary")
        migrated_text = (
            migrated_text[: glossary.end()]
            + "\n"
            + WORKSPACE_ROOT_EXPLANATION
            + "\n"
            + migrated_text[glossary.end() :]
        )
    existing_adapter = DISTRIBUTION_AGENTS_ADAPTER.strip() + "\n"
    migrated_text = migrated_text.replace(
        LEGACY_DISTRIBUTION_AGENTS_ADAPTER.strip() + "\n", ""
    )
    migrated_text = migrated_text.replace(existing_adapter, "")
    migrated = migrated_text.rstrip().encode("utf-8") + b"\n"
    return migrated + DISTRIBUTION_AGENTS_ADAPTER.encode()


def distribution_hook_adapter(base: bytes) -> bytes:
    supported = (
        (b"#!/usr/bin/bash\n", b'\ncd "$repo_root"\n', b"#!/bin/bash\n"),
        (b"#!/usr/bin/env bash\n", b'\ncd "$ROOT_DIR"\n', b"#!/usr/bin/env bash\n"),
    )
    matches = [
        item
        for item in supported
        if base.startswith(item[0]) and base.count(item[1]) == 1
    ]
    if len(matches) != 1:
        raise ContractError("pre-commit hook has no unique supported entry")
    shebang, anchor, replacement = matches[0]
    fixed = replacement + base[len(shebang) :]
    return fixed.replace(anchor, anchor + DISTRIBUTION_HOOK_ADAPTER.encode(), 1)


def distribution_paths_eligible(
    paths: set[str],
    *,
    base_build: bytes | None = None,
    current_build: bytes | None = None,
    base_agents: bytes | None = None,
    current_agents: bytes | None = None,
    base_hook: bytes | None = None,
    current_hook: bytes | None = None,
) -> bool:
    if not paths.intersection(DISTRIBUTION_PATHS):
        return False
    if not paths.issubset(
        DISTRIBUTION_PATHS
        | {"scripts/build_check.sh", "AGENTS.md", DISTRIBUTION_HOOK_PATH}
    ):
        return False
    migration = paths.intersection({"scripts/build_check.sh", "AGENTS.md"})
    if "AGENTS.md" in migration:
        if base_build is None or base_agents is None:
            return False
        if "scripts/build_check.sh" in migration:
            try:
                expected_build = distribution_adapter(base_build, base_hook)
            except ContractError:
                return False
            if current_build != expected_build:
                return False
        elif (
            current_build != base_build
            or base_build.count(b"# anshin-document-distribution-profile:v1") != 1
        ):
            return False
        if current_agents != distribution_agents_adapter(base_agents):
            return False
    elif "scripts/build_check.sh" in migration:
        return False
    if DISTRIBUTION_HOOK_PATH in paths:
        if migration != {"scripts/build_check.sh", "AGENTS.md"} or base_hook is None:
            return False
        try:
            if current_hook != distribution_hook_adapter(base_hook):
                return False
        except ContractError:
            return False
    return True


def distribution_selection(repository_root: Path) -> str:
    target = (
        distribution_git(repository_root, "rev-parse", "--verify", "origin/main")
        .strip()
        .decode("ascii")
    )
    head = (
        distribution_git(repository_root, "rev-parse", "HEAD").strip().decode("ascii")
    )
    base = (
        distribution_git(repository_root, "merge-base", target, head)
        .strip()
        .decode("ascii")
    )
    common_diff = ("diff", "--no-ext-diff", "--no-textconv", "--no-renames")
    path_commands = (
        (*common_diff, "--name-only", "-z", f"{base}...{head}", "--"),
        (*common_diff, "--name-only", "-z", "--cached", "--"),
        (*common_diff, "--name-only", "-z", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    )
    paths: set[str] = set()
    for command in path_commands:
        for raw in distribution_git(repository_root, *command).split(b"\0"):
            if raw:
                paths.add(os.fsdecode(raw))
    extra: dict[str, bytes] = {}
    if "scripts/build_check.sh" in paths or "AGENTS.md" in paths:
        for name, path in (
            ("build", "scripts/build_check.sh"),
            ("agents", "AGENTS.md"),
        ):
            current = repository_root / path
            if not current.is_file() or current.is_symlink():
                return f"repository-fast {base} {target} {head} -"
            extra[f"current_{name}"] = current.read_bytes()
            extra[f"base_{name}"] = distribution_git(
                repository_root, "show", f"{base}:{path}"
            )
    if DISTRIBUTION_HOOK_PATH in paths:
        hook = repository_root / DISTRIBUTION_HOOK_PATH
        if not hook.is_file() or hook.is_symlink():
            return f"repository-fast {base} {target} {head} -"
        extra["current_hook"] = hook.read_bytes()
        extra["base_hook"] = distribution_git(
            repository_root, "show", f"{base}:{DISTRIBUTION_HOOK_PATH}"
        )
    if not distribution_paths_eligible(paths, **extra):
        return f"repository-fast {base} {target} {head} -"
    # Fingerprinting an arbitrary index only proves it did not change, not that
    # its payload was verified. Every layer must contain the old or new asset.
    trees = []
    for revision in (base, head):
        entries = {}
        for row in distribution_git(
            repository_root, "ls-tree", "-z", revision, "--", *sorted(paths)
        ).split(b"\0"):
            if row:
                metadata, name = row.split(b"\t", 1)
                mode, kind, oid = metadata.split()
                entries[os.fsdecode(name)] = (mode, kind, oid)
        trees.append(entries)
    index = {}
    for row in distribution_git(
        repository_root, "ls-files", "--stage", "-z", "--", *sorted(paths)
    ).split(b"\0"):
        if row:
            metadata, name = row.split(b"\t", 1)
            mode, oid, stage = metadata.split()
            if stage != b"0":
                raise ContractError("distribution index has unresolved entries")
            index[os.fsdecode(name)] = (mode, b"blob", oid)
    digest = hashlib.sha256()
    for path in sorted(paths):
        current = repository_root / path
        if not current.is_file() or current.is_symlink():
            raise ContractError(
                "distribution asset is missing or is not a regular file"
            )
        previous = trees[0].get(path)
        if (
            previous is None
            or previous[0] not in {b"100644", b"100755"}
            or previous[1] != b"blob"
        ):
            raise ContractError("distribution baseline is not a regular tracked asset")
        allowed = {
            distribution_git(
                repository_root, "cat-file", "blob", previous[2].decode("ascii")
            ),
            current.read_bytes(),
        }
        for layer in (trees[1], index):
            entry = layer.get(path)
            if entry is None or entry[:2] != previous[:2]:
                raise ContractError("distribution asset mode or presence changed")
            if (
                distribution_git(
                    repository_root, "cat-file", "blob", entry[2].decode("ascii")
                )
                not in allowed
            ):
                raise ContractError(
                    "distribution commit/index contains unverified bytes"
                )
        digest.update(os.fsencode(path) + b"\0")
        digest.update(hashlib.sha256(current.read_bytes()).digest())
    for arguments in (
        (*common_diff, "--raw", "-z", "--cached", "--"),
        (*common_diff, "--raw", "-z", "--"),
        ("ls-files", "--stage", "-z", "--", *sorted(paths)),
    ):
        digest.update(distribution_git(repository_root, *arguments))
    return f"document-distribution {base} {target} {head} {digest.hexdigest()}"


def _quality_plan_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _distribution_changed_paths(repository_root: Path) -> list[str]:
    # The native commit hook has already rejected partial staging and emits
    # exact index paths. Its stored plan must be validated against that same
    # index, including GIT_INDEX_FILE, rather than earlier branch commits or
    # unrelated working files. Direct/branch qualification keeps all inputs.
    if (
        os.environ.get("ANSHIN_BUILD_CHECK_CALLER") == "pre-commit"
        and os.environ.get("ANSHIN_BUILD_CHECK_CHANGE_SCOPE") == "staged"
    ):
        reader = repository_root / "scripts/pre_commit_plan.py"
        if not reader.is_file() or reader.is_symlink():
            raise ContractError("native staged-path reader is unavailable")
        completed = subprocess.run(
            [sys.executable, "-I", str(reader), "--staged-paths"],
            cwd=repository_root,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise ContractError("native staged-path reader rejected repository input")
        return sorted(
            {
                path.decode("utf-8", errors="surrogateescape")
                for path in completed.stdout.split(b"\0")
                if path
            }
        )
    target = (
        distribution_git(repository_root, "rev-parse", "--verify", "origin/main")
        .strip()
        .decode("ascii")
    )
    head = (
        distribution_git(repository_root, "rev-parse", "HEAD").strip().decode("ascii")
    )
    base = (
        distribution_git(repository_root, "merge-base", target, head)
        .strip()
        .decode("ascii")
    )
    values: set[str] = set()
    for arguments in (
        ("diff", "--name-only", "--no-renames", "-z", f"{base}...{head}", "--"),
        ("diff", "--cached", "--name-only", "--no-renames", "-z", "--"),
        ("diff", "--name-only", "--no-renames", "-z", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        values.update(
            path.decode("utf-8", errors="surrogateescape")
            for path in distribution_git(repository_root, *arguments).split(b"\0")
            if path
        )
    return sorted(values)


def _adapter_spec(repository_root: Path) -> dict[str, Any]:
    build = repository_root / "scripts/build_check.sh"
    if not build.is_file() or build.is_symlink():
        raise ContractError("build-check adapter is missing")
    return _adapter_spec_from_build(build.read_bytes())


def _native_selected_checks(
    repository_root: Path, spec: dict[str, Any], paths: list[str]
) -> tuple[list[str], str, bool]:
    selector = spec["selector"]
    selector_paths = paths
    modern_frontend = spec["kind"] == "frontend-root" and spec["plan_args"] == [
        "--root-quality-plan"
    ]
    if spec["kind"] == "frontend-root" and not modern_frontend:
        prefix = "apps/anshin-frontend/"
        if not all(path.startswith(prefix) for path in paths):
            return ["frontend-root-full"], "high", True
        selector_paths = [path[len(prefix) :] for path in paths]
    if spec["kind"] == "core-native":
        wrapper = """import importlib.util,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
root=Path.cwd().resolve(); selector=(root/sys.argv[1]).resolve()
if root not in selector.parents: raise SystemExit('selector escaped snapshot')
spec=importlib.util.spec_from_file_location('_anshin_exact_selector',selector)
if spec is None or spec.loader is None: raise SystemExit('selector import failed')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
if not callable(getattr(module,'quality_plan',None)) or not callable(getattr(module,'_quality_candidate_identity',None)): raise SystemExit('selector pure planner is unavailable')
module._quality_candidate_identity=lambda:{'qualification':False}
try: plan=module.quality_plan(sys.argv[2:],profile='auto')
except module.SelectionError as exc: print(str(exc),file=sys.stderr); raise SystemExit(2)
print(json.dumps(plan,sort_keys=True))
"""
        command = [sys.executable, "-I", "-c", wrapper, selector, *selector_paths]
    elif modern_frontend:
        wrapper = """const path=require('node:path');
const selector=path.resolve(process.argv[1]);
// Historical native selectors read Git identity at module load and planning.
// Supply nonqualification identity only; evaluate owners/checks from source.
const cp=require('node:child_process');
cp.execFileSync=(command,args,options={})=>{
 if(command!=='git') throw new Error('snapshot process launch is forbidden');
 let value;
 if(args[0]==='rev-parse' && args[1]==='--show-toplevel') value=process.cwd()+'\\n';
 else if(args[0]==='rev-parse' && args[1]==='--show-object-format') value='sha1\\n';
 else if((args[0]==='rev-parse' && ['HEAD','HEAD^{tree}'].includes(args[1])) ||
         (args[0]==='merge-base' && args.join(' ')==='merge-base HEAD origin/main')) value='0'.repeat(40)+'\\n';
 else if([
  ['diff','--cached','--binary','--no-ext-diff'],
  ['diff','--name-only','-z','--no-renames','--'],
  ['diff','--name-only','-z','--no-renames','0'.repeat(40),'HEAD','--'],
  ['ls-files','--stage','-z'],
  ['ls-files','-z','--others','--exclude-standard'],
 ].some(allowed=>JSON.stringify(allowed)===JSON.stringify(args))) value='';
 else throw new Error('snapshot Git command is not identity-only');
 return options.encoding ? value : Buffer.from(value);
};
const modulePlan=require(selector);
if(typeof modulePlan.rootQualityPlan!=='function') throw new Error('root pure planner unavailable');
const plan=modulePlan.rootQualityPlan(process.argv.slice(2),{identity:()=>({qualification:false})});
console.log(JSON.stringify(plan));
"""
        command = ["node", "-e", wrapper, selector, *selector_paths]
    else:
        command = [
            "node" if selector.endswith(".js") else sys.executable,
            selector,
            *spec["plan_args"],
            *selector_paths,
        ]
    completed = subprocess.run(
        command,
        cwd=repository_root,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ContractError(
            completed.stderr.strip() or "repository-native quality plan failed"
        )
    if spec["kind"] == "frontend-root" and not modern_frontend:
        lines = completed.stdout.splitlines()
        modes = [
            line.removeprefix("mode: ") for line in lines if line.startswith("mode: ")
        ]
        command_markers = [
            index for index, line in enumerate(lines) if line == "commands:"
        ]
        if (
            len(modes) != 1
            or modes[0] not in {"fast", "full"}
            or len(command_markers) != 1
        ):
            raise ContractError("repository-native quality plan is invalid")
        marker = command_markers[0]
        command_lines = [
            line.strip() for line in lines[marker + 1 :] if line.startswith("  ")
        ]
        if len(command_lines) != 1:
            raise ContractError("repository-native quality plan is invalid")
        try:
            native_argv = shlex.split(command_lines[0])
        except ValueError as exc:
            raise ContractError("repository-native quality plan is invalid") from exc
        expected = (
            ["./scripts/build_check.sh", "--fast", *selector_paths]
            if modes[0] == "fast"
            else ["./scripts/build_check.sh"]
        )
        if native_argv != expected:
            raise ContractError("repository-native quality plan command differs")
        if modes[0] == "fast":
            return ["frontend-root-fast"], "normal", False
        return ["frontend-root-full"], "high", True
    try:
        native = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("repository-native quality plan is not JSON") from exc
    if modern_frontend:
        if (
            not isinstance(native, dict)
            or not isinstance(native.get("rootFullRisk"), bool)
            or native.get("files") != paths
        ):
            raise ContractError("repository-native root quality plan is invalid")
        checks = native.get("checks")
        if (
            not isinstance(checks, list)
            or not checks
            or any(not isinstance(check, str) or not check for check in checks)
            or len(set(checks)) != len(checks)
        ):
            raise ContractError(
                "repository-native root quality plan has invalid check IDs"
            )
        return (
            sorted(checks),
            (
                "high"
                if native["rootFullRisk"] or native.get("appMode") == "full"
                else "normal"
            ),
            native["rootFullRisk"],
        )
    candidate = native.get("candidate", native) if isinstance(native, dict) else None
    if not isinstance(candidate, dict):
        raise ContractError("repository-native quality plan is invalid")
    raw_checks = candidate.get("checks", native.get("checks", []))
    if not isinstance(raw_checks, list):
        raise ContractError("repository-native quality plan is invalid")
    checks: list[str] = []
    for item in raw_checks:
        name = item.get("id") if isinstance(item, dict) else item
        if not isinstance(name, str) or not name or name in checks:
            raise ContractError("repository-native quality plan has invalid check IDs")
        checks.append(name)
    checks.sort()
    if not checks:
        raise ContractError("repository-native quality plan selected no checks")
    native_paths = candidate.get("paths", native.get("paths"))
    if native_paths is not None and sorted(native_paths) != paths:
        raise ContractError("repository-native quality plan paths differ")
    full = bool(
        candidate.get("full_risk", candidate.get("requires_full", False))
        or native.get("full_risk", native.get("requires_full", False))
    )
    risk = "high" if full else "normal"
    return checks, risk, full


def _plan_dependencies(repository_root: Path, spec: dict[str, Any]) -> list[str]:
    dependencies = sorted(set(DISTRIBUTION_PATHS) | set(spec["dependencies"]))
    for relative in dependencies:
        target = repository_root / relative
        if not target.is_file() or target.is_symlink():
            raise ContractError(f"quality-plan dependency is unavailable: {relative}")
    return dependencies


def _document_distribution_eligible(repository_root: Path, paths: list[str]) -> bool:
    allowed = set(DISTRIBUTION_PATHS) | {
        "AGENTS.md",
        "scripts/build_check.sh",
        DISTRIBUTION_HOOK_PATH,
    }
    if not set(paths).issubset(allowed):
        return False
    try:
        contract = json.loads(
            (repository_root / "scripts/document_governance_contract.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    expected_hashes = {
        "checker_sha256": "scripts/document_governance_portable.py",
        "runner_sha256": "scripts/run_document_governance_guard.sh",
        "guard_test_sha256": "scripts/test_document_governance_guard.sh",
    }
    for key, relative in expected_hashes.items():
        target = repository_root / relative
        if (
            not target.is_file()
            or target.is_symlink()
            or contract.get(key) != hashlib.sha256(target.read_bytes()).hexdigest()
        ):
            return False
    if (repository_root / ".git").exists():
        try:
            return distribution_selection(repository_root).startswith(
                "document-distribution "
            )
        except ContractError:
            return False
    expected_modes = {
        "scripts/document_governance_portable.py": 0o755,
        "scripts/run_document_governance_guard.sh": 0o755,
        "scripts/test_document_governance_guard.sh": 0o755,
        "scripts/document_governance_contract.json": 0o644,
    }
    return all(
        stat.S_IMODE((repository_root / relative).stat().st_mode) == mode
        for relative, mode in expected_modes.items()
    )


def distribution_quality_plan(
    repository_root: Path, paths: list[str] | None = None
) -> dict[str, Any]:
    """Return the exact local plan for the existing distribution profile."""
    selected_paths = (
        _distribution_changed_paths(repository_root)
        if paths is None
        else sorted(set(paths))
    )
    if not selected_paths:
        raise ContractError("quality plan requires changed paths")
    # The Gitless producer can prove the immutable common bundle only. Build,
    # hook, and AGENTS normalizations are accepted by bootstrap after their
    # exact base-derived bytes are checked; arbitrary edits take the native gate.
    document_only = _document_distribution_eligible(repository_root, selected_paths)
    spec = _adapter_spec(repository_root)
    if document_only:
        checks = ["document-governance-distribution"]
        profile = "document-distribution"
        risk = "normal"
        requires_full = False
        reasons = ["SELECTED_DOCUMENT_DISTRIBUTION"]
        deferred = ["repository-runtime", "business-test"]
    elif spec["kind"] == "marketing-legacy":
        fast_paths = set(DISTRIBUTION_PATHS) | {
            "AGENTS.md",
            "scripts/build_check.sh",
            "tests/test_marketing_retirement_guard.py",
        }
        if set(selected_paths).issubset(fast_paths):
            checks = ["repository-fast"]
            profile = "repository-fast"
            risk, requires_full = "normal", False
            reasons = ["SELECTED_REPOSITORY_FAST"]
        else:
            checks = ["repository-canonical"]
            profile = "repository-canonical"
            risk, requires_full = "high", True
            reasons = ["SELECTED_REPOSITORY_CANONICAL"]
        deferred = []
    elif spec["kind"] == "legacy":
        checks = ["repository-canonical"]
        profile = "repository-canonical"
        risk, requires_full = "normal", False
        reasons = ["SELECTED_REPOSITORY_CANONICAL"]
        deferred = []
    else:
        checks, risk, requires_full = _native_selected_checks(
            repository_root, spec, selected_paths
        )
        profile = "repository-native"
        reasons = ["SELECTED_REPOSITORY_NATIVE"]
        deferred = []
    dependencies = _plan_dependencies(repository_root, spec)
    dependency = hashlib.sha256()
    for relative in dependencies:
        dependency.update(relative.encode() + b"\0")
        dependency.update((repository_root / relative).read_bytes())
    value: dict[str, Any] = {
        "schema": QUALITY_PLAN_SCHEMA,
        "profile": profile,
        "risk": risk,
        "reasons": reasons,
        "paths": selected_paths,
        "deferred": deferred,
        "owner_ids": checks,
        "selected_tests": [],
        "selected_checks": checks,
        "requires_fixed_sha": True,
        "requires_full": requires_full,
        "producer_command": ["bash", "scripts/build_check.sh", "--print-plan"],
        "producer_dependencies": dependencies,
        "command_sha256": hashlib.sha256(
            (repository_root / "scripts/build_check.sh").read_bytes()
        ).hexdigest(),
        "dependency_sha256": dependency.hexdigest(),
    }
    value["plan_sha256"] = hashlib.sha256(_quality_plan_json(value)).hexdigest()
    return value


def execute_distribution_quality_plan(repository_root: Path, plan_path: Path) -> None:
    validate_distribution_quality_plan(repository_root, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan["profile"] == "document-distribution":
        raise ContractError("document-distribution is executed by the shell adapter")
    spec = _adapter_spec(repository_root)
    if plan["profile"] == "repository-canonical":
        if spec["kind"] not in {"legacy", "marketing-legacy"} or plan[
            "selected_checks"
        ] != ["repository-canonical"]:
            raise ContractError("repository canonical plan does not match its adapter")
        command = ["bash", "scripts/build_check.sh", *spec["invocation"]]
        completed = subprocess.run(command, cwd=repository_root, check=False)
        if completed.returncode:
            raise ContractError("repository canonical build check failed")
        return
    if plan["profile"] == "repository-fast":
        if (
            spec["kind"] != "marketing-legacy"
            or plan["selected_checks"] != ["repository-fast"]
            or plan["requires_full"]
        ):
            raise ContractError("repository fast plan does not match its adapter")
        completed = subprocess.run(
            ["bash", "scripts/build_check.sh", "--fast"],
            cwd=repository_root,
            check=False,
        )
        if completed.returncode:
            raise ContractError("repository fast build check failed")
        return
    if plan["profile"] != "repository-native" or spec["kind"] == "legacy":
        raise ContractError("repository-native plan does not match its adapter")
    if spec["kind"] == "frontend-root" and spec["plan_args"] == ["--root-quality-plan"]:
        raise ContractError("Frontend stored plans execute in the native shell")
    if spec["kind"] == "frontend-root":
        selected = set(plan["selected_checks"])
        if (
            not selected
            or not selected.issubset({"frontend-root-fast", "frontend-root-full"})
            or plan["requires_full"] != ("frontend-root-full" in selected)
        ):
            raise ContractError("repository-native frontend plan is invalid")
    if spec["kind"] == "core-native":
        raise ContractError("Core stored plans execute in the native shell")
    for check_id in plan["selected_checks"]:
        if spec["kind"] == "selector-direct":
            command = [
                sys.executable,
                spec["selector"],
                *spec["execution_args"],
                check_id,
            ]
        elif spec["kind"] == "build-focus":
            command = ["bash", "scripts/build_check.sh", "--focus", check_id]
        elif spec["kind"] == "core-native":
            if check_id == "core-fast":
                command = ["bash", "scripts/build_check.sh", "--fast", *plan["paths"]]
            else:
                command = [
                    sys.executable,
                    spec["selector"],
                    *spec["execution_args"],
                    check_id,
                ]
        elif spec["kind"] == "frontend-root":
            if check_id == "frontend-root-fast":
                command = ["bash", "scripts/build_check.sh", "--fast", *plan["paths"]]
            elif check_id == "frontend-root-full":
                command = ["bash", "scripts/build_check.sh", "--full"]
            else:
                raise ContractError(f"repository-native check is unknown: {check_id}")
        else:
            raise ContractError("repository-native execution kind is unsupported")
        completed = subprocess.run(command, cwd=repository_root, check=False)
        if completed.returncode:
            raise ContractError(f"repository-native check failed: {check_id}")


def validate_distribution_quality_plan(repository_root: Path, plan_path: Path) -> None:
    if not plan_path.is_file() or plan_path.is_symlink():
        raise ContractError("quality plan is missing or is not a regular file")
    if stat.S_IMODE(plan_path.stat().st_mode) != 0o600:
        raise ContractError("quality plan mode must be 0600")
    try:
        actual = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("quality plan is not valid JSON") from exc
    required_keys = {
        "schema",
        "profile",
        "risk",
        "reasons",
        "paths",
        "deferred",
        "owner_ids",
        "selected_tests",
        "selected_checks",
        "requires_fixed_sha",
        "requires_full",
        "producer_command",
        "producer_dependencies",
        "command_sha256",
        "dependency_sha256",
        "plan_sha256",
    }
    unsigned = dict(actual) if isinstance(actual, dict) else {}
    actual_hash = unsigned.pop("plan_sha256", None)
    if (
        set(actual) != required_keys
        or actual.get("schema") != QUALITY_PLAN_SCHEMA
        or actual_hash != hashlib.sha256(_quality_plan_json(unsigned)).hexdigest()
        or actual.get("paths") != _distribution_changed_paths(repository_root)
        or actual.get("selected_checks")
        != sorted(set(actual.get("selected_checks", [])))
        or not actual.get("selected_checks")
        or actual.get("owner_ids") != actual.get("selected_checks")
        or actual.get("producer_command")
        != ["bash", "scripts/build_check.sh", "--print-plan"]
        or actual.get("risk") not in {"low", "normal", "high", "critical"}
        or not isinstance(actual.get("requires_fixed_sha"), bool)
        or not isinstance(actual.get("requires_full"), bool)
    ):
        raise ContractError("quality plan does not match the current repository input")
    spec = _adapter_spec(repository_root)
    dependencies = _plan_dependencies(repository_root, spec)
    digest = hashlib.sha256()
    for relative in dependencies:
        digest.update(relative.encode() + b"\0")
        digest.update((repository_root / relative).read_bytes())
    document_only = _document_distribution_eligible(repository_root, actual["paths"])
    if (
        actual.get("producer_dependencies") != dependencies
        or actual.get("command_sha256")
        != hashlib.sha256(
            (repository_root / "scripts/build_check.sh").read_bytes()
        ).hexdigest()
        or actual.get("dependency_sha256") != digest.hexdigest()
        or (actual.get("profile") == "document-distribution") != document_only
        or (
            actual.get("profile") == "repository-canonical"
            and (
                spec["kind"] not in {"legacy", "marketing-legacy"}
                or actual.get("selected_checks") != ["repository-canonical"]
            )
        )
        or (
            actual.get("profile") == "repository-fast"
            and (
                spec["kind"] != "marketing-legacy"
                or actual.get("selected_checks") != ["repository-fast"]
                or actual.get("requires_full")
            )
        )
        or (
            actual.get("profile") == "repository-native"
            and spec["kind"] in {"legacy", "marketing-legacy"}
        )
        or actual.get("profile")
        not in {
            "document-distribution",
            "repository-canonical",
            "repository-fast",
            "repository-native",
        }
    ):
        raise ContractError("quality plan does not match the current repository input")


def write_distribution_check_result(
    repository_root: Path,
    plan_path: Path,
    result_path: Path,
    status: str,
    *,
    completed_checks: list[str] | None = None,
    failed_check: str | None = None,
) -> None:
    """Write the existing v2 check-result family for one direct or staged run."""
    if status not in {"passed", "failed"}:
        raise ContractError("quality result status is invalid")
    validate_distribution_quality_plan(repository_root, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    revision = distribution_git(repository_root, "rev-parse", "HEAD").decode().strip()
    tree = distribution_git(repository_root, "write-tree").decode().strip()
    staged = subprocess.run(
        ["git", "-C", str(repository_root), "diff", "--cached", "--quiet", "--"],
        check=False,
    )
    if staged.returncode not in {0, 1}:
        raise ContractError("unable to inspect staged distribution input")
    base_revision = revision
    if staged.returncode == 0:
        base_revision = (
            distribution_git(repository_root, "merge-base", "HEAD", "origin/main")
            .decode()
            .strip()
        )
    completed = completed_checks or []
    if (
        len(completed) != len(set(completed))
        or not set(completed).issubset(plan["selected_checks"])
        or failed_check in completed
        or (failed_check is not None and failed_check not in plan["selected_checks"])
    ):
        raise ContractError("quality result check status is invalid")
    statuses = []
    for name in plan["selected_checks"]:
        check_status = status
        if status == "failed" and completed_checks is not None:
            check_status = (
                "passed"
                if name in completed
                else "failed" if name == failed_check else "not_run"
            )
        statuses.append({"name": name, "status": check_status})
    result: dict[str, Any] = {
        "schema": "anshin.check-results.v2",
        "kind": "check-results",
        "revision": revision,
        "check_plan_sha256": plan["plan_sha256"],
        "checks": statuses,
        "status": status,
        "identities": {
            "base_revision": base_revision,
            "tree": tree,
            "paths": plan["paths"],
            "policy_revision": "AI-DD-20260920.1",
            "plan_sha256": plan["plan_sha256"],
            "command_sha256": plan["command_sha256"],
            "dependency_sha256": plan["dependency_sha256"],
            "toolchain": {"python": platform.python_version()},
            "image": "none",
            "environment": platform.system().lower(),
        },
    }
    result["result_sha256"] = hashlib.sha256(
        json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    descriptor = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode()
        )
        stream.write(b"\n")


def test_distribution_profile() -> None:
    base = b'#!/usr/bin/env bash\ncd "$ROOT_DIR"\nlegacy\n'
    agents = b"existing policy\n"
    migration = set(DISTRIBUTION_PATHS) | {"scripts/build_check.sh", "AGENTS.md"}
    values = {
        "base_build": base,
        "current_build": distribution_adapter(base),
        "base_agents": agents,
        "current_agents": agents + DISTRIBUTION_AGENTS_ADAPTER.encode(),
    }
    cases = [
        (set(DISTRIBUTION_PATHS), {}, True),
        (set(), {}, False),
        ({"AGENTS.md"}, {}, False),
        (set(DISTRIBUTION_PATHS) | {"app/business.py"}, {}, False),
        (set(DISTRIBUTION_PATHS) | {"docs/日本語\n境界.md"}, {}, False),
        (migration, values, True),
        (
            migration,
            {**values, "current_build": values["current_build"] + b"extra\n"},
            False,
        ),
        (migration, {**values, "current_agents": b"arbitrary policy\n"}, False),
    ]
    for paths, kwargs, expected in cases:
        if distribution_paths_eligible(paths, **kwargs) != expected:
            raise ContractError("distribution profile regression failed")
    print("[document-governance-distribution-profile-test] OK cases=8")


def scalar(value: str) -> Any:
    value = value.strip()
    if not value or value in {"null", "~"}:
        return None
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = [scalar(item) for item in value[1:-1].split(",") if item.strip()]
        return parsed
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value


def parse_top_level_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if current_list and raw_line.strip().startswith("- "):
            result.setdefault(current_list, []).append(scalar(raw_line.strip()[2:]))
            continue
        if raw_line.startswith((" ", "\t")):
            continue
        match = re.match(r"^([A-Za-z0-9_]+):(?:\s*(.*))?$", raw_line)
        if not match:
            current_list = None
            continue
        key, raw_value = match.group(1), match.group(2) or ""
        if raw_value.strip():
            result[key] = scalar(raw_value)
            current_list = None
        else:
            result[key] = []
            current_list = key
    return result


def frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractError("metadata v2 frontmatter is missing")
    try:
        end = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise ContractError("metadata frontmatter is not terminated") from exc
    return parse_top_level_yaml("\n".join(lines[1:end]))


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not any(part in SKIP_PARTS for part in path.parts):
            yield path


def git_changed_paths(repository_root: Path) -> set[Path]:
    commands = (
        ["git", "-c", "core.quotePath=false", "diff", "--name-only"],
        ["git", "-c", "core.quotePath=false", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    changed: set[Path] = set()
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ContractError(f"cannot discover changed paths: {' '.join(command)}")
        changed.update(
            (repository_root / line).resolve()
            for line in completed.stdout.splitlines()
            if line.strip()
        )
    return changed


def ignored_document_artifact_summary(
    repository_root: Path, documents_root: Path
) -> tuple[int, int]:
    """Return count/bytes without exposing names or reading ignored content."""
    try:
        relative_root = (
            documents_root.resolve().relative_to(repository_root.resolve()).as_posix()
        )
    except ValueError as exc:
        raise ContractError(
            f"documents root escapes repository: {documents_root}"
        ) from exc
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            relative_root,
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ContractError(
            f"cannot inspect Git-ignored document artifacts: {documents_root}"
        )
    count = 0
    total_bytes = 0
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = repository_root / raw_path.decode(errors="surrogateescape")
        try:
            stat = path.lstat()
        except OSError:
            continue
        if path.is_dir():
            continue
        count += 1
        total_bytes += stat.st_size
    return count, total_bytes


def validate_manifest(
    documents_root: Path, root_id: str, errors: list[str]
) -> set[Path]:
    manifest_path = documents_root / "manifest.yaml"
    readme_path = documents_root / "README.md"
    if not manifest_path.is_file():
        errors.append(f"{root_id}: missing documents/manifest.yaml")
        return set()
    if not readme_path.is_file():
        errors.append(f"{root_id}: missing documents/README.md")
    manifest = parse_top_level_yaml(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2:
        errors.append(f"{root_id}: manifest schema_version must be 2")
    if manifest.get("root_id") != root_id:
        errors.append(f"{root_id}: manifest root_id is {manifest.get('root_id')!r}")
    if manifest.get("enforcement") != "required":
        errors.append(f"{root_id}: manifest enforcement must be required")
    canonical = manifest.get("canonical_documents", [])
    if not isinstance(canonical, list):
        errors.append(f"{root_id}: canonical_documents must be a list")
        return set()
    result: set[Path] = set()
    for item in canonical:
        if not isinstance(item, str) or not item:
            errors.append(f"{root_id}: invalid canonical document path {item!r}")
            continue
        target = (documents_root / item).resolve()
        try:
            target.relative_to(documents_root.resolve())
        except ValueError:
            errors.append(f"{root_id}: canonical path escapes documents root: {item}")
            continue
        if not target.is_file():
            errors.append(f"{root_id}: canonical document does not exist: {item}")
        result.add(target)
    return result


def validate_metadata(path: Path, canonical: bool, errors: list[str]) -> str | None:
    try:
        data = frontmatter(path)
    except (OSError, UnicodeError, ContractError) as exc:
        errors.append(f"{path}: {exc}")
        return None
    if "source_docs" in data:
        errors.append(
            f"{path}: source_docs is retired; use source_doc_ids with doc_id values "
            "only (filesystem paths and URLs are forbidden)"
        )
    missing = sorted(REQUIRED_METADATA - data.keys())
    if missing:
        errors.append(f"{path}: missing metadata keys: {', '.join(missing)}")
    if data.get("schema_version") != 2:
        errors.append(f"{path}: schema_version must be 2")
    doc_id = data.get("doc_id")
    if not isinstance(doc_id, str) or not DOC_ID_PATTERN.fullmatch(doc_id):
        errors.append(f"{path}: invalid doc_id {doc_id!r}")
        doc_id = None
    domain = data.get("domain")
    if not isinstance(domain, str) or not DOMAIN_PATTERN.fullmatch(domain):
        errors.append(f"{path}: invalid domain {domain!r}")
    enums = (
        ("document_kind", ALLOWED_KINDS),
        ("scope", ALLOWED_SCOPES),
        ("authority", ALLOWED_AUTHORITIES),
        ("status", ALLOWED_STATUSES),
        ("risk_level", ALLOWED_RISKS),
        ("sensitivity", ALLOWED_SENSITIVITY),
    )
    for key, allowed in enums:
        if data.get(key) not in allowed:
            errors.append(f"{path}: invalid {key} {data.get(key)!r}")
    plan_state = data.get("plan_state")
    if data.get("document_kind") == "plan":
        if plan_state not in ALLOWED_PLAN_STATES:
            errors.append(f"{path}: plan document requires a valid plan_state")
    elif plan_state is not None:
        errors.append(f"{path}: plan_state is only valid for document_kind=plan")
    for key in LIST_METADATA:
        if key in data and not isinstance(data[key], list):
            errors.append(f"{path}: {key} must be a list")
    source_doc_ids = data.get("source_doc_ids")
    if isinstance(source_doc_ids, list):
        for index, source_doc in enumerate(source_doc_ids):
            if not isinstance(source_doc, str) or not DOC_ID_PATTERN.fullmatch(
                source_doc
            ):
                errors.append(
                    f"{path}: source_doc_ids[{index}] must be a doc_id such as "
                    "anshin.domain.document; filesystem paths and URLs are forbidden"
                )
        if len(source_doc_ids) != len(set(map(str, source_doc_ids))):
            errors.append(f"{path}: source_doc_ids must not contain duplicates")
    successor = data.get("successor")
    if successor is not None and (
        not isinstance(successor, str) or not DOC_ID_PATTERN.fullmatch(successor)
    ):
        errors.append(f"{path}: successor must be a portable doc_id")
    interval = data.get("review_interval_days")
    if not isinstance(interval, int) or interval <= 0:
        errors.append(f"{path}: review_interval_days must be a positive integer")
    if canonical and data.get("authority") != "canonical":
        errors.append(
            f"{path}: manifest canonical document must use authority=canonical"
        )
    if data.get("status") == "active" and data.get("authority") == "canonical":
        for key in (
            "last_reviewed",
            "reviewed_by",
            "approved_by",
            "approved_at",
            "approval_ref",
        ):
            if data.get(key) in (None, "", []):
                errors.append(f"{path}: active canonical document requires {key}")
    return doc_id


def validate_links(
    path: Path,
    repository_root: Path,
    errors: list[str],
    *,
    enforce_missing: bool = True,
    changed_paths: set[Path] | None = None,
) -> None:
    repository_root = repository_root.resolve()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path}: cannot read Markdown: {exc}")
        return
    for raw_target in MARKDOWN_LINK_PATTERN.findall(text):
        target = raw_target.strip().strip("<>").split("#", 1)[0].split("?", 1)[0]
        if (
            not target
            or "http" in target
            or re.match(r"^(?:artifact:|doc:|mailto:|tel:|data:)", target)
        ):
            continue
        target = unquote(target)
        if nonportable_markdown_path_lines(target):
            errors.append(
                f"{path}: local absolute Markdown link is forbidden: {target}"
            )
            continue
        if target.startswith("/"):
            continue
        resolved = (path.parent / target).resolve()
        if resolved.exists():
            continue
        try:
            resolved.relative_to(repository_root)
        except ValueError:
            # This is a sibling-repository link. A single clone cannot prove it;
            # the mandatory workspace aggregate owns that coverage.
            continue
        if not enforce_missing and resolved not in (changed_paths or set()):
            # Existing links may point to nested sibling repositories or
            # intentionally untracked restricted assets that are unavailable in
            # a standalone clone. The full 23-root workspace aggregate owns
            # existing-link coverage; this clone still fails for a changed
            # Markdown file or a deleted target.
            continue
        errors.append(f"{path}: broken relative Markdown link: {target}")


def validate_root(
    repository_root: Path,
    root_id: str,
    documents_root: Path,
    errors: list[str],
    ids: dict[str, list[Path]],
    hashes: dict[str, list[Path]],
    changed_paths: set[Path],
) -> int:
    if not documents_root.is_dir():
        errors.append(f"{root_id}: documents root does not exist: {documents_root}")
        return 0
    canonical = validate_manifest(documents_root, root_id, errors)
    count = 0
    for path in iter_files(documents_root):
        relative = path.relative_to(documents_root)
        is_changed = path.resolve() in changed_paths
        is_canonical = path.resolve() in canonical
        has_metadata = False
        if path.suffix.lower() == ".md":
            try:
                with path.open("r", encoding="utf-8") as handle:
                    has_metadata = handle.readline().strip() == "---"
            except (OSError, UnicodeError):
                has_metadata = False
        root_control = relative.as_posix() in {"README.md", "manifest.yaml"}
        if (
            not root_control
            and relative.parts
            and relative.parts[0] not in ALLOWED_TOP_LEVEL
        ):
            errors.append(f"{root_id}: non-canonical top-level path: {relative}")
        lower_name = path.name.lower()
        if is_changed and (
            path.name in FORBIDDEN_NAMES
            or lower_name.startswith(".env")
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
        ):
            errors.append(f"{root_id}: forbidden document artifact: {relative}")
        if path.suffix.lower() == ".md" and (
            has_metadata or is_changed or is_canonical
        ):
            try:
                metadata = frontmatter(path)
            except (OSError, UnicodeError, ContractError):
                metadata = {}
            doc_id = validate_metadata(path, is_canonical, errors)
            if doc_id:
                ids[doc_id].append(path)
            # The repository-root README and manifest are control-plane files,
            # not domain documents.  The workspace checker already exempts
            # them; keep the portable single-repository checker equivalent so
            # CI does not require a non-existent second path segment.
            if (
                not root_control
                and relative.parts
                and relative.parts[0] != "_governance"
            ):
                document_kind = metadata.get("document_kind")
                if document_kind == "index" and path.name != "README.md":
                    errors.append(
                        f"{root_id}: index document must be named README.md: {relative}"
                    )
                expected_directory = KIND_DIRECTORIES.get(document_kind)
                if expected_directory and relative.parts[0] != expected_directory:
                    errors.append(
                        f"{root_id}: document_kind {document_kind} requires "
                        f"{expected_directory}/<domain>/: {relative}"
                    )
                domain = metadata.get("domain")
                if (
                    document_kind in {*KIND_DIRECTORIES, "index"}
                    and isinstance(domain, str)
                    and (len(relative.parts) < 2 or relative.parts[1] != domain)
                ):
                    errors.append(
                        f"{root_id}: document domain {domain} must match the "
                        f"second path segment: {relative}"
                    )
            validate_links(
                path,
                repository_root,
                errors,
                enforce_missing=is_changed,
                changed_paths=changed_paths,
            )
            count += 1
        if (
            has_metadata
            and path.name not in {"README.md", "manifest.yaml"}
            and "_governance" not in relative.parts
        ):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes[digest].append(path)
        if is_changed and path.suffix.lower() in {
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".xml",
            ".svg",
            ".csv",
        }:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(
                        f"{root_id}: secret-like content detected: {relative}"
                    )
                    break
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--contract-metadata", type=Path)
    parser.add_argument("--completed-check", action="append", default=[])
    parser.add_argument("--failed-check")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build-check-profile", action="store_true")
    mode.add_argument("--test-build-check-profile", action="store_true")
    mode.add_argument("--build-check-plan", action="store_true")
    mode.add_argument("--build-check-plan-profile", type=Path)
    mode.add_argument("--validate-build-check-plan", type=Path)
    mode.add_argument("--execute-build-check-plan", type=Path)
    mode.add_argument(
        "--write-build-check-result",
        nargs=3,
        metavar=("PLAN", "RESULT", "STATUS"),
    )
    parser.add_argument("plan_paths", nargs="*")
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    if (
        args.build_check_profile
        or args.test_build_check_profile
        or args.build_check_plan
        or args.build_check_plan_profile is not None
        or args.validate_build_check_plan is not None
        or args.execute_build_check_plan is not None
        or args.write_build_check_result is not None
    ):
        try:
            if args.test_build_check_profile:
                test_distribution_profile()
            elif args.build_check_plan:
                sys.stdout.buffer.write(
                    json.dumps(
                        distribution_quality_plan(
                            repository_root, args.plan_paths or None
                        ),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ).encode("utf-8")
                    + b"\n"
                )
            elif args.build_check_plan_profile is not None:
                validate_distribution_quality_plan(
                    repository_root, args.build_check_plan_profile
                )
                value = json.loads(
                    args.build_check_plan_profile.read_text(encoding="utf-8")
                )
                print(value["profile"])
            elif args.validate_build_check_plan is not None:
                validate_distribution_quality_plan(
                    repository_root, args.validate_build_check_plan
                )
            elif args.execute_build_check_plan is not None:
                execute_distribution_quality_plan(
                    repository_root, args.execute_build_check_plan
                )
            elif args.write_build_check_result is not None:
                write_distribution_check_result(
                    repository_root,
                    Path(args.write_build_check_result[0]),
                    Path(args.write_build_check_result[1]),
                    args.write_build_check_result[2],
                    completed_checks=(
                        args.completed_check
                        if args.write_build_check_result[2] == "failed"
                        and (args.completed_check or args.failed_check)
                        else None
                    ),
                    failed_check=args.failed_check,
                )
            else:
                print(distribution_selection(repository_root))
        except (ContractError, OSError, UnicodeError) as error:
            print(f"[document-governance-profile] ERROR: {error}", file=sys.stderr)
            return 1
        return 0
    if args.contract_metadata is None:
        parser.error("--contract-metadata is required for document validation")
    metadata = json.loads(args.contract_metadata.read_text(encoding="utf-8"))
    errors: list[str] = []
    if metadata.get("contract_version") != CONTRACT_VERSION:
        errors.append(
            "contract version mismatch: "
            f"{metadata.get('contract_version')!r} != {CONTRACT_VERSION!r}"
        )
    validate_ai_policy_contract(repository_root, metadata, errors)
    validate_build_check_contract(repository_root, metadata, errors)
    validate_github_actions_usage(repository_root, errors)
    validate_retired_metadata_templates(repository_root, errors)
    validate_repository_markdown_paths(repository_root, errors)
    roots = metadata.get("roots")
    if not isinstance(roots, list) or not roots:
        errors.append("contract metadata has no registered roots")
        roots = []
    ids: dict[str, list[Path]] = defaultdict(list)
    hashes: dict[str, list[Path]] = defaultdict(list)
    documents = 0
    try:
        changed_paths = git_changed_paths(repository_root)
    except ContractError as exc:
        errors.append(str(exc))
        changed_paths = set()
    for root in roots:
        if not isinstance(root, dict):
            errors.append(f"invalid root metadata: {root!r}")
            continue
        root_id = root.get("id")
        documents_path = root.get("documents_path")
        if not isinstance(root_id, str) or not isinstance(documents_path, str):
            errors.append(f"invalid root metadata: {root!r}")
            continue
        documents_root = repository_root / documents_path
        try:
            ignored_count, ignored_bytes = ignored_document_artifact_summary(
                repository_root, documents_root
            )
        except ContractError as exc:
            errors.append(str(exc))
        else:
            if ignored_count:
                errors.append(
                    f"{root_id}: document root contains {ignored_count} Git-ignored "
                    f"unmanaged artifacts ({ignored_bytes} bytes); move "
                    "restricted/runtime "
                    "data outside the document root or register reviewable files as "
                    "governed documents"
                )
        documents += validate_root(
            repository_root,
            root_id,
            documents_root,
            errors,
            ids,
            hashes,
            changed_paths,
        )
    for doc_id, paths in ids.items():
        if len(paths) > 1:
            errors.append(
                f"duplicate doc_id {doc_id}: {', '.join(str(path) for path in paths)}"
            )
    for digest, paths in hashes.items():
        physical = {path.resolve() for path in paths}
        if len(physical) > 1:
            errors.append(
                f"duplicate document content {digest}: "
                f"{', '.join(str(path) for path in paths)}"
            )
    if errors:
        for error in errors:
            print(f"[document-governance-portable] ERROR: {error}", file=sys.stderr)
        print(
            "[document-governance-portable] FAILED "
            f"errors={len(errors)} roots={len(roots)} documents={documents}",
            file=sys.stderr,
        )
        return 1
    print(
        f"[document-governance-portable] OK contract={CONTRACT_VERSION} "
        f"roots={len(roots)} documents={documents}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
