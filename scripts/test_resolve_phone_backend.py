#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from resolve_phone_backend import (
    REQUIRED_PATHS,
    ResolutionError,
    resolve_backend,
)


def create_backend(path: Path) -> Path:
    for relative in REQUIRED_PATHS:
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path.resolve()


class ResolvePhoneBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.infra = self.workspace / "anshin-phone-infra"
        self.infra.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_resolves_flat_sibling_repository(self) -> None:
        sibling = create_backend(self.workspace / "anshin-phone-backend")

        self.assertEqual(resolve_backend(self.infra), sibling)

    def test_resolves_legacy_nested_repository(self) -> None:
        nested = create_backend(self.infra / "anshin-phone-backend")

        self.assertEqual(resolve_backend(self.infra), nested)

    def test_ignores_inherited_git_context_from_another_repository(self) -> None:
        sibling = create_backend(self.workspace / "anshin-phone-backend")
        unrelated = create_backend(self.workspace / "unrelated")
        poisoned = {
            "GIT_COMMON_DIR": str(unrelated / ".git"),
            "GIT_DIR": str(unrelated / ".git"),
            "GIT_INDEX_FILE": str(unrelated / ".git" / "index"),
            "GIT_OBJECT_DIRECTORY": str(unrelated / ".git" / "objects"),
            "GIT_PREFIX": "poisoned/",
            "GIT_WORK_TREE": str(unrelated),
        }

        with mock.patch.dict(os.environ, poisoned):
            self.assertEqual(resolve_backend(self.infra), sibling)

    def test_rejects_ambiguous_default_and_accepts_explicit_override(self) -> None:
        sibling = create_backend(self.workspace / "anshin-phone-backend")
        nested = create_backend(self.infra / "anshin-phone-backend")

        with self.assertRaisesRegex(ResolutionError, "multiple phone backend"):
            resolve_backend(self.infra)
        self.assertEqual(resolve_backend(self.infra, str(sibling)), sibling)
        self.assertEqual(
            resolve_backend(self.infra, "anshin-phone-backend"), nested
        )

    def test_rejects_override_without_the_backend_contract(self) -> None:
        invalid = self.workspace / "invalid"
        invalid.mkdir()

        with self.assertRaisesRegex(ResolutionError, "missing required files"):
            resolve_backend(self.infra, str(invalid))


if __name__ == "__main__":
    unittest.main()
