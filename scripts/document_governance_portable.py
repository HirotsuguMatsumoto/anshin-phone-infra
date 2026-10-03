#!/usr/bin/env python3
"""Network-free, stdlib-only document governance contract for one Git repository.

This file is the canonical source for generated repository-local distributions.
Run scripts/sync_document_governance_distribution.py to update copies.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote

CONTRACT_VERSION = "2026-09-03.1"
BUILD_CHECK_MARKER = "anshin-document-governance-build-check:v1"
BUILD_CHECK_COMMAND = "bash scripts/run_document_governance_guard.sh"
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
DISTRIBUTION_BUILD_ADAPTER = """
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
"""
DISTRIBUTION_AGENTS_ADAPTER = """
## Checker配布の限定検査

文書checkerの配布と定型adapterだけの変更は、`anshin.governance.document-management`の10.2に従い、`bash scripts/build_check.sh --document-distribution`をcanonical検査とする。それ以外の変更では本書の通常fast/full条件を維持する。専用profileが不適格を返した場合は検査を省略せず、通常の変更範囲検査へ戻す。
"""
DISTRIBUTION_HOOK_PATH = ".githooks/pre-commit"
DISTRIBUTION_HOOK_ADAPTER = """
# anshin-document-distribution-hook:v1
distribution_selection="$(bash scripts/run_document_governance_guard.sh --build-check-profile)"
if [[ "$distribution_selection" == document-distribution\\ * ]]; then
  bash scripts/build_check.sh --document-distribution
  exit 0
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
    re.I,
)
QUOTED_FILE_URI_PATTERN = re.compile(
    r"""(?P<quote>[`"'])(?P<path>file://.*?)(?P=quote)""",
    re.I,
)
QUOTED_ABSOLUTE_PATH_PATTERN = re.compile(
    r"""(?P<quote>[`"'])(?P<path>(?:file://)?(?:[A-Za-z]:[\\/]|\\\\|/).*?)(?P=quote)""",
    re.I,
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
    re.I,
)
WINDOWS_UNC_REPOSITORY_PATH_PATTERN = re.compile(
    r"""(?<![A-Za-z0-9_.])(?:[A-Za-z]:[\\/]|\\\\)"""
    r"""(?:[^\\/`<>\[\]()"'、。）」|\r\n]+[\\/])*"""
    r"""(?:"""
    + "|".join(map(re.escape, REPOSITORY_NAMES))
    + r"""|anshin[a-z0-9_.-]*worktree[a-z0-9_.-]*)(?=[\\/]|$)""",
    re.I,
)
POSIX_SPACED_REPOSITORY_PATH_PATTERN = re.compile(
    r"""(?<![A-Za-z0-9_./>~])/(?=[^=`<>\[\]()"'、。）」|,\r\n]*[ \t])"""
    r"""(?:[^/=`<>\[\]()"'、。）」|,\r\n]*[^\s/=`<>\[\]()"'、。）」|,\r\n]/)*"""
    r"""(?:"""
    + "|".join(map(re.escape, REPOSITORY_NAMES))
    + r"""|anshin[a-z0-9_.-]*worktree[a-z0-9_.-]*)(?=/|[ =\t`<>\[\]()"'、。）」|,]|$)"""
    r"""(?:/[^ =\t`<>\[\]()"'、。）」|,\r\n]+)*""",
    re.I,
)
SPACED_FILE_URI_REPOSITORY_PATH_PATTERN = re.compile(
    r"""file://(?=[^`<>\[\]()"'、。）」|,\r\n]*[ \t])"""
    r"""[^`<>\[\]()"'、。）」|,\r\n]*?"""
    r"""(?:"""
    + "|".join(map(re.escape, REPOSITORY_NAMES))
    + r"""|anshin[a-z0-9_.-]*worktree[a-z0-9_.-]*)(?=[/\\]|[ =\t`<>\[\]()"'、。）」|,]|$)"""
    r"""(?:[/\\][^ =\t`<>\[\]()"'、。）」|,\r\n]+)*""",
    re.I,
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
    re.I,
)
HTTP_OPERATION_PATTERN = r"GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|TRACE"
HTTP_METHOD_ROUTE_CONTEXT = re.compile(
    rf"""(?:^|[\s|])[`"']?(?:{HTTP_OPERATION_PATTERN})[`"']?"""
    r"""\s+(?:[`"']\s*)?$""",
    re.I,
)
HTTP_METHOD_TABLE_BEFORE_ROUTE_CONTEXT = re.compile(
    rf"""(?:^|\|)\s*[`"']?(?:{HTTP_OPERATION_PATTERN})[`"']?"""
    r"""\s*\|\s*(?:[`"']\s*)?$""",
    re.I,
)
HTTP_METHOD_TABLE_AFTER_ROUTE_CONTEXT = re.compile(
    rf"""^[`"']?\s*\|\s*[`"']?(?:{HTTP_OPERATION_PATTERN})""" r"""[`"']?\s*(?:\||$)""",
    re.I,
)
API_PATH_KEY_PATTERN = re.compile(
    r"""^\s*(?P<quote>["']?)(?P<path>/[^\s`"']+?)(?P=quote)\s*:\s*(?:\{\s*)?(?:#.*)?$"""
)
INLINE_API_OPERATION_PATH_PATTERN = re.compile(
    r"""^\s*(?P<quote>["']?)(?P<path>/[^\s`"']+?)(?P=quote)\s*:\s*\{\s*"""
    rf"""(?P<operation_quote>["']?)(?:{HTTP_OPERATION_PATTERN})(?P=operation_quote)\s*:""",
    re.I,
)
API_OPERATION_KEY_PATTERN = re.compile(
    rf"""^(?P<indent>[ \t]+)(?P<quote>["']?)(?:{HTTP_OPERATION_PATTERN})"""
    r"""(?P=quote)\s*:(?:\s|$)""",
    re.I,
)


def _normalized_source_path(value: str) -> str:
    path = unquote(value)
    path = re.sub(r"^file://(?:[^/\s]+)?(?=/)", "", path, flags=re.I)
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
        source = re.sub(r"https?://[^\s<>`]+", "", line, flags=re.I)
        extracted_paths: list[tuple[str, int, int]] = []

        def remember_quoted_path(match: re.Match[str]) -> str:
            extracted_paths.append(
                (match.group("path"), match.start("path"), match.end("path"))
            )
            return " " * len(match.group())

        def remember_unquoted_path(match: re.Match[str]) -> str:
            extracted_paths.append((match.group(), match.start(), match.end()))
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


def distribution_adapter(base: bytes) -> bytes:
    anchor = b'\ncd "$ROOT_DIR"\n'
    if base.count(anchor) != 1:
        raise ContractError("build check has no unique repository-root entry")
    return base.replace(anchor, anchor + DISTRIBUTION_BUILD_ADAPTER.encode(), 1)


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
    existing_adapter = DISTRIBUTION_AGENTS_ADAPTER.strip() + "\n"
    migrated_text = migrated_text.replace(existing_adapter, "")
    migrated = migrated_text.rstrip().encode("utf-8") + b"\n"
    return migrated + DISTRIBUTION_AGENTS_ADAPTER.encode()


def distribution_hook_adapter(base: bytes) -> bytes:
    anchor = b'\ncd "$repo_root"\n'
    if not base.startswith(b"#!/usr/bin/bash\n") or base.count(anchor) != 1:
        raise ContractError("pre-commit hook has no unique supported entry")
    fixed = b"#!/bin/bash\n" + base.split(b"\n", 1)[1]
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
                expected_build = distribution_adapter(base_build)
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build-check-profile", action="store_true")
    mode.add_argument("--test-build-check-profile", action="store_true")
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    if args.build_check_profile or args.test_build_check_profile:
        try:
            if args.test_build_check_profile:
                test_distribution_profile()
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
