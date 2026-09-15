#!/usr/bin/env python3
"""Resolve the separate phone backend repository used by Phase 1 validation."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


REQUIRED_PATHS = (
    "Dockerfile",
    "app/main.py",
    "alembic.ini",
    "migrations/versions/20260822_0001_initial_phone_control_plane.py",
)


class ResolutionError(RuntimeError):
    pass


def isolated_git_environment() -> dict[str, str]:
    """Remove hook-scoped Git paths before inspecting another repository."""
    environment = os.environ.copy()
    for key in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_QUARANTINE_PATH",
        "GIT_WORK_TREE",
    ):
        environment.pop(key, None)
    return environment


def normalize_candidate(infra_root: Path, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = infra_root / candidate
    return candidate.resolve()


def validation_error(candidate: Path) -> str | None:
    if not candidate.is_dir():
        return "directory does not exist"
    missing = [
        relative
        for relative in REQUIRED_PATHS
        if not (candidate / relative).is_file()
    ]
    if missing:
        return f"missing required files: {', '.join(missing)}"
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
        env=isolated_git_environment(),
    )
    if result.returncode != 0:
        return "not a Git repository"
    if Path(result.stdout.strip()).resolve() != candidate:
        return "path is not the root of its Git repository"
    return None


def resolve_backend(infra_root: Path, override: str | None = None) -> Path:
    infra_root = infra_root.resolve()
    if override:
        candidate = normalize_candidate(infra_root, override)
        error = validation_error(candidate)
        if error:
            raise ResolutionError(
                f"ANSHIN_PHONE_BACKEND_DIR is invalid: {candidate}: {error}"
            )
        return candidate

    candidates = tuple(
        dict.fromkeys(
            (
                (infra_root.parent / "anshin-phone-backend").resolve(),
                (infra_root / "anshin-phone-backend").resolve(),
            )
        )
    )
    valid = [
        candidate
        for candidate in candidates
        if validation_error(candidate) is None
    ]
    if not valid:
        expected = ", ".join(str(candidate) for candidate in candidates)
        raise ResolutionError(
            "phone backend repository was not found; expected one of: "
            f"{expected}; set ANSHIN_PHONE_BACKEND_DIR to an explicit "
            "repository root"
        )
    if len(valid) > 1:
        choices = ", ".join(str(candidate) for candidate in valid)
        raise ResolutionError(
            "multiple phone backend repositories are valid: "
            f"{choices}; set ANSHIN_PHONE_BACKEND_DIR explicitly"
        )
    return valid[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--infra-root", type=Path, required=True)
    parser.add_argument("--override")
    arguments = parser.parse_args()
    try:
        backend = resolve_backend(arguments.infra_root, arguments.override)
    except ResolutionError as error:
        parser.exit(2, f"[phone-backend-resolver] ERROR: {error}\n")
    print(backend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
