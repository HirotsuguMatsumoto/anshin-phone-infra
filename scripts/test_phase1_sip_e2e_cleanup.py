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
    def test_simulator_compose_replaces_mock_port_reset_with_loopback_binding(self):
        import softphone_sip_fixture as sdk
        import tempfile,os,json
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            env={**os.environ,'PHONE_SOFTPHONE_SIMULATOR':'android','PHONE_SOFTPHONE_DEVICE':'emulator-5558',
                 'ANSHIN_PHONE_SECRET_DIR':raw,'ANSHIN_PHONE_BACKEND_DIR':raw,'PUBLIC_SIP_IP':'192.0.2.1',
                 'PUBLIC_RTP_IP':'192.0.2.2','CARRIER_AUTH_MODE':'ip','CARRIER_HOST':'mock-carrier','CARRIER_SOURCE_CIDRS':'10.254.250.10/32',
                 'SMARTPHONE_SOURCE_CIDRS':'10.254.250.30/32','CARRIER_SIP_USERNAME':'fixture','TEL_DID':'0300000001','FAX_DID':'0300000002'}
            with mock.patch.object(sdk.subprocess,'run',return_value=mock.Mock(stdout='phone-softphone-20261022\nOK\n')):
                override=sdk.prepare_simulator(test_phase1_sip_e2e.ROOT,root,env,root)
            result=subprocess.run(test_phase1_sip_e2e.compose_args('phone-config-unit')+['--file',str(override),'config','--format','json'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            ports=json.loads(result.stdout)['services']['kamailio']['ports']
            self.assertEqual(len(ports),1)
            self.assertEqual((ports[0]['host_ip'],ports[0]['published'],ports[0]['target'],ports[0]['protocol']),('127.0.0.1',env['PHONE_SIM_PORT'],5070,'udp'))

    def test_simulator_cleanup_stops_group_even_after_leader_exit(self):
        import softphone_sip_fixture as sdk
        import signal
        process = mock.Mock(pid=123, returncode=0)
        with mock.patch.object(sdk.os,'killpg') as kill:
            sdk.stop_simulator_process(process)
        self.assertEqual(kill.call_args_list,[mock.call(123,signal.SIGTERM),mock.call(123,signal.SIGKILL)])
        with mock.patch.object(sdk.os,'killpg',side_effect=ProcessLookupError):
            sdk.stop_simulator_process(process)

    def test_simulator_template_keeps_production_carrier_isolated(self):
        import softphone_sip_fixture as sdk
        rendered = sdk.simulator_template(test_phase1_sip_e2e.ROOT, '10.0.2.2', 24001, '192.168.65.1')
        self.assertIn('advertise 10.0.2.2:24001', rendered)
        self.assertIn('$Rp == 5070 && src_ip != 192.168.65.1/32', rendered)
        self.assertIn('Fixture Contact Alias Forbidden', rendered)
        self.assertIn(';alias=192[.]168[.]65[.]1~[0-9]{1,5}~1$', rendered)
        self.assertIn('Fixture Alias Mismatch', rendered)
        self.assertIn('$fs = "udp:__SBC_EDGE_IP__:5060";', rendered)
        self.assertIn('route(FIXTURE_TARGET);', rendered)
        for source,port in [('0.0.0.0',24001),('8.8.8.8',24001),('192.168.65.1',70000)]:
            with self.assertRaises((ValueError,RuntimeError)):
                sdk.simulator_template(test_phase1_sip_e2e.ROOT,'10.0.2.2',port,source)

    @mock.patch('test_phase1_sip_e2e.docker_test_lease')
    @mock.patch('test_phase1_sip_e2e.run_isolated_e2e', return_value=0)
    def test_softphone_uses_existing_fixture_owner_and_lease(self, fixture, lease):
        self.assertEqual(test_phase1_sip_e2e.main(['--fixture','softphone']),0)
        fixture.assert_called_once_with(fixture_only='softphone')
        lease.assert_called_once_with()

    def test_softphone_missing_or_dirty_inputs_stop_before_archive_or_runtime(self):
        import softphone_sip_fixture as sdk
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            with mock.patch.object(sdk.subprocess,'run') as process:
                with self.assertRaisesRegex(RuntimeError,'explicit Softphone'):
                    sdk.prepare_softphone_override(root,root,{},mock.Mock())
                process.assert_not_called()
            source=root/'mobile/ios/anshin_phone_softphone/Sources/PhoneNative'
            source.mkdir(parents=True);(source/'phone_sip.cpp').write_text('fixture')
            run=mock.Mock(side_effect=[mock.Mock(stdout=sdk.PIN+'\n'),mock.Mock(stdout='dirty')])
            with mock.patch.object(sdk.subprocess,'run') as process:
                with self.assertRaisesRegex(RuntimeError,'pin or cleanliness'):
                    sdk.prepare_softphone_override(root,root,{'PHONE_SOFTPHONE_ROOT':str(root/'mobile'),'PHONE_PJSIP_SOURCE':str(root/'sdk')},run)
                process.assert_not_called()

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
    @mock.patch("test_phase1_sip_e2e.docker_test_lease")
    def test_help_does_not_acquire_resources_or_start_runtime(self, lease, e2e) -> None:
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
            test_phase1_sip_e2e.main(["--help"])
        self.assertEqual(result.exception.code, 0)
        lease.assert_not_called()
        e2e.assert_not_called()

    @mock.patch('test_phase1_sip_e2e.docker_test_lease')
    @mock.patch('test_phase1_sip_e2e.run_isolated_e2e', return_value=0)
    def test_main_preflight_does_not_acquire_resource_lease(self, e2e, lease):
        self.assertEqual(test_phase1_sip_e2e.main(['--preflight']), 0)
        e2e.assert_called_once_with(preflight_only=True)
        lease.assert_not_called()

    def test_independent_shared_leases_coexist_and_both_exclude_global_exclusive(self):
        import fcntl, os, sys, tempfile
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'test.lock'
            script = ('import fcntl,os,sys; '
                      'fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600); '
                      '\ntry: fcntl.flock(fd,int(sys.argv[2])|fcntl.LOCK_NB)'
                      '\nexcept BlockingIOError: sys.exit(75)\n')
            def acquire(mode):
                return subprocess.run([sys.executable, '-c', script, str(path), str(mode)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5).returncode
            with mock.patch.object(test_phase1_sip_e2e, 'DOCKER_HEAVY_LOCK_PATH', path):
                with test_phase1_sip_e2e.docker_test_lease():
                    self.assertEqual(acquire(fcntl.LOCK_SH), 0)
                    self.assertEqual(acquire(fcntl.LOCK_EX), 75)
                with path.open('r+') as exclusive:
                    fcntl.flock(exclusive, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaisesRegex(RuntimeError, 'exclusive Docker'):
                        with test_phase1_sip_e2e.docker_test_lease():
                            self.fail('shared lease entered during global exclusive')
                self.assertEqual(acquire(fcntl.LOCK_EX), 0)

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


    @mock.patch("test_phase1_sip_e2e.cleanup_residue",return_value=[])
    @mock.patch("test_phase1_sip_e2e.project_image_ids",return_value=[])
    @mock.patch("test_phase1_sip_e2e.run")
    def test_restore_failure_removes_retained_ui_before_compose_network(self, run, images, residue):
        run.return_value = mock.Mock(returncode=0,stdout="")
        project="anshin-phone-sip-test-owned"
        base=["docker","compose","--project-name",project]
        with redirect_stdout(io.StringIO()):
            test_phase1_sip_e2e.cleanup_owned_runtime(base,project,{},True)
        self.assertEqual(run.call_args_list[0].args[0],["docker","rm","--force",project+"-management-ui"])
        self.assertEqual(run.call_args_list[1].args[0],base+["down","--rmi","local","--volumes","--remove-orphans"])
        residue.assert_called_once_with(base,project,{},[])

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
