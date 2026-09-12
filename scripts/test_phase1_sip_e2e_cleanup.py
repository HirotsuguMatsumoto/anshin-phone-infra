#!/usr/bin/env python3
"""Regression tests for resource cleanup after the isolated SIP E2E."""

import unittest
from unittest import mock
import subprocess

import test_phase1_sip_e2e


class Phase1SipE2ECleanupTest(unittest.TestCase):
    def test_cleanup_removes_project_images_volumes_and_orphans(self) -> None:
        base = ["docker", "compose", "--project-name", "anshin-phone-sip-test-test"]
        self.assertEqual(
            test_phase1_sip_e2e.cleanup_args(base),
            base + ["down", "--rmi", "local", "--volumes", "--remove-orphans"],
        )

    def test_uses_the_workspace_wide_docker_heavy_lease(self) -> None:
        self.assertEqual(
            str(test_phase1_sip_e2e.DOCKER_HEAVY_LOCK_PATH),
            "/tmp/anshin-local-docker-heavy.lock",
        )

    @mock.patch("test_phase1_sip_e2e.run")
    def test_cleanup_residue_checks_every_project_resource(self, run: mock.Mock) -> None:
        run.return_value = mock.Mock(returncode=0, stdout="")
        base = ["docker", "compose", "--project-name", "anshin-phone-sip-test-abcdef12"]
        self.assertEqual(
            test_phase1_sip_e2e.cleanup_residue(base, "anshin-phone-sip-test-abcdef12", {}),
            [],
        )
        self.assertEqual(run.call_count, 4)

    @mock.patch("test_phase1_sip_e2e.run")
    def test_cleanup_residue_reports_nonempty_results(self, run: mock.Mock) -> None:
        run.side_effect = [
            mock.Mock(returncode=0, stdout="container-id\n"),
            mock.Mock(returncode=0, stdout=""),
            mock.Mock(returncode=0, stdout=""),
            mock.Mock(returncode=0, stdout="image-id\n"),
        ]
        base = ["docker", "compose", "--project-name", "anshin-phone-sip-test-abcdef12"]
        self.assertEqual(
            test_phase1_sip_e2e.cleanup_residue(base, "anshin-phone-sip-test-abcdef12", {}),
            ["container", "image"],
        )

    @mock.patch("test_phase1_sip_e2e.run")
    def test_cleanup_detects_a_dangling_project_image_by_exact_id(self, run: mock.Mock) -> None:
        run.side_effect = [
            mock.Mock(returncode=0, stdout=""),
            mock.Mock(returncode=0, stdout=""),
            mock.Mock(returncode=0, stdout=""),
            mock.Mock(returncode=0, stdout=""),
            mock.Mock(returncode=0, stdout="still exists"),
        ]
        base = ["docker", "compose", "--project-name", "anshin-phone-sip-test-abcdef12"]
        self.assertEqual(
            test_phase1_sip_e2e.cleanup_residue(
                base,
                "anshin-phone-sip-test-abcdef12",
                {},
                ["sha256:built-image"],
            ),
            ["image"],
        )

    def test_cleanup_nonzero_fails_an_otherwise_successful_e2e(self) -> None:
        cleanup = subprocess.CompletedProcess([], 1, "cleanup failed")
        with self.assertRaises(RuntimeError):
            test_phase1_sip_e2e.ensure_cleanup_succeeded(cleanup, [], False)

    def test_cleanup_residue_fails_an_otherwise_successful_e2e(self) -> None:
        cleanup = subprocess.CompletedProcess([], 0, "")
        with self.assertRaises(RuntimeError):
            test_phase1_sip_e2e.ensure_cleanup_succeeded(cleanup, ["image"], False)

    def test_cleanup_defect_does_not_replace_an_earlier_test_failure(self) -> None:
        cleanup = subprocess.CompletedProcess([], 1, "cleanup failed")
        test_phase1_sip_e2e.ensure_cleanup_succeeded(cleanup, ["image"], True)


if __name__ == "__main__":
    unittest.main()
