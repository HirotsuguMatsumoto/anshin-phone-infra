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
LOCAL_ABSOLUTE_PATH_PATTERN = re.compile(r"^(?:/Users/|/home/|[A-Za-z]:[\\/])")
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
    "deploy-production.yml": "ssh",
    "deploy-production.yaml": "ssh",
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
        if LOCAL_ABSOLUTE_PATH_PATTERN.match(target):
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
    parser.add_argument("--contract-metadata", type=Path, required=True)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
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
