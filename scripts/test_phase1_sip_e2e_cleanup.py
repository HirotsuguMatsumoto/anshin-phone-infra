#!/usr/bin/env python3
"""Regression tests for resource cleanup after the isolated SIP E2E."""

import unittest
from unittest import mock
import subprocess
from contextlib import redirect_stdout
import io
from pathlib import Path

import test_phase1_sip_e2e


class Phase1SipE2ECleanupTest(unittest.TestCase):
    @mock.patch("test_phase1_sip_e2e.run")
    @mock.patch("test_phase1_sip_e2e.ensure_mock_networks_available")
    @mock.patch("test_phase1_sip_e2e.resolve_backend")
    def test_preflight_never_builds_starts_or_cleans_runtime(self, resolve_backend, networks, run) -> None:
        resolve_backend.return_value = Path("/isolated/anshin-phone-backend")
        run.return_value = mock.Mock(stdout="", returncode=0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(test_phase1_sip_e2e.run_isolated_e2e(preflight_only=True), 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-2:], ["config", "--quiet"])

    @mock.patch("test_phase1_sip_e2e.run_isolated_e2e")
    @mock.patch("test_phase1_sip_e2e.docker_heavy_lease")
    def test_help_does_not_acquire_resources_or_start_runtime(self, lease, e2e) -> None:
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
            test_phase1_sip_e2e.main(["--help"])
        self.assertEqual(result.exception.code, 0)
        lease.assert_not_called()
        e2e.assert_not_called()

    @mock.patch("test_phase1_sip_e2e.resolve_backend")
    @mock.patch("test_phase1_sip_e2e.run")
    def test_invalid_backend_stops_before_compose_start(self, run, resolve_backend) -> None:
        resolve_backend.side_effect = RuntimeError("backend source mismatch")
        with self.assertRaisesRegex(RuntimeError, "backend source mismatch"):
            test_phase1_sip_e2e.run_isolated_e2e()
        run.assert_not_called()

    @mock.patch("test_phase1_sip_e2e.ensure_mock_networks_available")
    @mock.patch("test_phase1_sip_e2e.resolve_backend")
    @mock.patch("test_phase1_sip_e2e.run")
    def test_resolved_backend_is_used_for_compose_preflight(self, run, resolve_backend, networks) -> None:
        backend = Path("/isolated/anshin-phone-backend")
        resolve_backend.return_value = backend
        run.side_effect = RuntimeError("preflight stop")
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "preflight stop"):
            test_phase1_sip_e2e.run_isolated_e2e()
        command, = run.call_args_list[0].args
        self.assertEqual(command[-2:], ["config", "--quiet"])
        self.assertEqual(run.call_args_list[0].kwargs["env"]["ANSHIN_PHONE_BACKEND_DIR"], str(backend))

    @mock.patch("test_phase1_sip_e2e.run")
    def test_subnet_collision_is_rejected_before_build(self, run) -> None:
        run.side_effect = [
            mock.Mock(stdout="network-id\n"),
            mock.Mock(stdout='[{"IPAM":{"Config":[{"Subnet":"10.254.0.0/16"}]}}]'),
        ]
        with self.assertRaisesRegex(RuntimeError, "process-start=0"):
            test_phase1_sip_e2e.ensure_mock_networks_available({})
        self.assertEqual(run.call_count, 2)

    @mock.patch("test_phase1_sip_e2e.run")
    def test_nonoverlapping_and_ipv6_networks_are_accepted(self, run) -> None:
        run.side_effect = [
            mock.Mock(stdout="network-id\n"),
            mock.Mock(stdout='[{"IPAM":{"Config":[{"Subnet":"172.31.0.0/16"},{"Subnet":"fd00::/64"}]}}]'),
        ]
        test_phase1_sip_e2e.ensure_mock_networks_available({})


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
