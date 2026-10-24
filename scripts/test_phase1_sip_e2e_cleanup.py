#!/usr/bin/env python3
"""Regression tests for resource cleanup after the isolated SIP E2E."""

import unittest
import sys
from unittest import mock
import subprocess
from contextlib import redirect_stdout
import io
import json
from pathlib import Path

import test_phase1_sip_e2e


class Phase1SipE2ECleanupTest(unittest.TestCase):
    def test_simulator_control_ignores_proxy_and_rejects_redirect(self):
        import softphone_sip_fixture as sdk
        import http.server,threading,os,urllib.error
        class Handler(http.server.BaseHTTPRequestHandler):
            redirect=False
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(302 if self.redirect else 200)
                if self.redirect:self.send_header('Location','http://127.0.0.1:1/external')
                self.end_headers()
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with mock.patch.dict(os.environ,{'http_proxy':'http://127.0.0.1:1','HTTP_PROXY':'http://127.0.0.1:1','no_proxy':'','NO_PROXY':''}):
                sdk.simulator_control_post(server.server_port,'config',{'fixture':'synthetic'})
                Handler.redirect=True
                with self.assertRaises(urllib.error.HTTPError) as error:
                    sdk.simulator_control_post(server.server_port,'config',{'fixture':'synthetic'})
                self.assertEqual(error.exception.code,302)
                error.exception.close()
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_simulator_forward_response_loss_cleans_only_new_exact_tuple(self):
        import softphone_sip_fixture as sdk
        old=('emulator-5558','tcp:10001','tcp:10002')
        new=('emulator-5558','tcp:10003','tcp:10004')
        foreign=('emulator-5556','tcp:10005','tcp:10004')
        with mock.patch.object(sdk,'simulator_forwards',side_effect=[{old,new,foreign},{old,foreign}]),mock.patch.object(sdk.subprocess,'run') as run:
            sdk.cleanup_simulator_forward('emulator-5558',10004,{old})
        self.assertEqual(run.call_args.args[0],['adb','-s','emulator-5558','forward','--remove','tcp:10003'])

    def test_simulator_incomplete_forward_snapshot_preserves_existing_mappings(self):
        import softphone_sip_fixture as sdk
        with mock.patch.object(sdk.subprocess,'check_output',return_value='incomplete mapping\n'),mock.patch.object(sdk.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'snapshot incomplete'):
                sdk.simulator_forwards('emulator-5558')
            run.assert_not_called()

    def test_simulator_first_snapshot_failure_does_not_delete_forward(self):
        import softphone_sip_fixture as sdk
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'template';path.write_text('fixture')
            env={'PHONE_SOFTPHONE_SIMULATOR':'android','PHONE_SOFTPHONE_DEVICE':'emulator-5558','PHONE_SIM_PORT':'24001',
                 'PHONE_SIM_TEMPLATE':str(path),'PHONE_SIM_HOST':'10.0.2.2','PHONE_SOFTPHONE_ROOT':raw}
            process=mock.Mock(stdout=io.StringIO('PHONE_SIM {"phase":"awaiting_input","port":25001}\n'))
            with mock.patch.object(sdk,'observe_source',return_value='192.168.65.1'),mock.patch.object(sdk.time,'sleep'),mock.patch.object(sdk.subprocess,'Popen',return_value=process),mock.patch.object(sdk,'stop_simulator_process'),mock.patch.object(sdk,'simulator_forwards',side_effect=RuntimeError('snapshot unavailable')),mock.patch.object(sdk,'cleanup_simulator_forward') as cleanup,mock.patch.object(sdk.subprocess,'run',side_effect=[mock.Mock(returncode=0),mock.Mock(returncode=1,stdout=b'')]):
                with self.assertRaisesRegex(RuntimeError,'snapshot unavailable'):
                    sdk.run_simulator_flow([],env,{}, {},mock.Mock(return_value=mock.Mock(stdout='127.0.0.1:24001')),mock.Mock(),mock.Mock())
                cleanup.assert_not_called()

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
        self.assertIn(';alias=192[.]168[.]65[.]1~[0-9]{1,5}~1(;ob)?$', rendered)
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


    def test_restore_failure_removes_retained_ui_before_compose_network(self):
        project="anshin-phone-sip-test-owned";events=[]
        base=["docker","compose","--project-name",project]
        env={'PHONE_TEST_EXPIRES_AT':'2026-10-25T00:00:00+00:00'}
        config={'services':{'backend':{}},'networks':{'default':{}},'volumes':{}}
        manager=mock.Mock()
        def assets(containers,networks,*args,**kwargs):events.append(('assets',list(containers),list(networks)))
        manager.cleanup_named_fixture_assets.side_effect=assets
        manager.verify_fixture_project.side_effect=lambda *args,**kwargs:events.append(('verify',kwargs.get('absent',False)))
        def run(argv,**kwargs):
            if 'config' in argv:return subprocess.CompletedProcess(argv,0,json.dumps(config),'')
            if 'down' in argv:events.append(('down',));raise RuntimeError('partial down')
            return subprocess.CompletedProcess(argv,0,'','')
        with mock.patch.object(test_phase1_sip_e2e,'fixture_manager',return_value=manager),mock.patch.object(test_phase1_sip_e2e,'run',side_effect=run),redirect_stdout(io.StringIO()):
            test_phase1_sip_e2e.cleanup_owned_runtime(base,project,env,True)
        self.assertLess(events.index(('assets',[project+'-management-ui'],[])),events.index(('down',)))
        self.assertIn(('assets',[project+'-backend-1'],[project+'_default']),events)
        self.assertIn(('verify',True),events)
        manager.cleanup_fixture_images.assert_called_once()

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

    def test_first_and_repeated_stop_during_normal_cleanup_finishes_every_phase(self):
        import signal, shutil
        for first in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            with self.subTest(first=first):
                events=[];path=None
                previous={kind:signal.getsignal(kind) for kind in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM)}
                def cleanup(*args):
                    events.append('before')
                    for kind in (first,signal.SIGHUP,signal.SIGINT,signal.SIGTERM):signal.raise_signal(kind)
                    events.extend(('remaining-native-cleanup','terminal-readback'))
                try:
                    with mock.patch.object(test_phase1_sip_e2e,'_cleanup_owned_runtime',side_effect=cleanup):
                        with self.assertRaises(test_phase1_sip_e2e.FixtureInterrupted) as caught:
                            with test_phase1_sip_e2e.fixture_signals(),test_phase1_sip_e2e.fixture_directory(allow_preview=False) as (path,_):
                                (path/'synthetic-input').write_text('fixture')
                                test_phase1_sip_e2e.cleanup_owned_runtime([], 'owned', {}, False)
                    self.assertEqual(first,caught.exception.signum)
                    self.assertEqual(['before','remaining-native-cleanup','terminal-readback'],events)
                    self.assertTrue((path/'synthetic-input').is_file())
                    for kind,handler in previous.items():self.assertIs(signal.getsignal(kind),handler)
                finally:
                    if path is not None:shutil.rmtree(path)

    def test_actual_restore_finally_defers_stops_and_attempts_storage_after_sql_error(self):
        import signal,shutil
        for first in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM):
            for sql_failure in (False,True):
                with self.subTest(first=first,sql_failure=sql_failure):
                    directory=None;events=[]
                    env={'PHONE_TEST_EXPIRES_AT':'2026-10-25T00:00:00+00:00'}
                    def run(argv,**options):
                        if 'pg_restore' in argv or 'tar' in argv:
                            self.assertFalse(options['text']);self.assertEqual(b'synthetic-binary\x00',options['stdin'].read())
                        if 'dropdb' in argv:
                            events.append('dropdb')
                            for kind in (first,signal.SIGHUP,signal.SIGINT,signal.SIGTERM):signal.raise_signal(kind)
                            if sql_failure:raise RuntimeError('SQL cleanup failed')
                        if 'rm' in argv:events.append('restore-storage')
                        return subprocess.CompletedProcess(argv,0,'fixture','')
                    try:
                        with mock.patch.object(test_phase1_sip_e2e,'run',side_effect=run),redirect_stdout(io.StringIO()):
                            with self.assertRaises(test_phase1_sip_e2e.FixtureInterrupted) as caught:
                                with test_phase1_sip_e2e.fixture_signals(),test_phase1_sip_e2e.fixture_directory(allow_preview=False) as (directory,_):
                                    backup=directory/'backup'/'snapshot';backup.mkdir(parents=True)
                                    for name in ('postgres.dump','fax-encrypted.tar'):(backup/name).write_bytes(b'synthetic-binary\x00')
                                    test_phase1_sip_e2e.run_backup_restore(['docker','compose','--project-name','owned'],env,directory)
                        self.assertEqual(first,caught.exception.signum)
                        self.assertEqual(['dropdb','restore-storage'],events)
                        self.assertTrue((directory/'backup'/'snapshot'/'postgres.dump').exists())
                    finally:
                        if directory is not None:shutil.rmtree(directory)

    def test_actual_fax_finally_preserves_primary_and_reaps_both_children_after_unpause_error(self):
        import signal,os,shutil
        for first in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM):
            with self.subTest(first=first):
                primary=RuntimeError('original FAX consumer failure');children=[];streams=[];directory=None;events=[]
                native=subprocess.Popen
                def start(argv,**options):
                    child=native([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True,**options)
                    children.append(child)
                    if options.get('stdout') is not None and options['stdout'] is not subprocess.PIPE:streams.append(options['stdout'])
                    return child
                def run(argv,**options):
                    if 'unpause' in argv:
                        events.append('unpause')
                        for kind in (first,signal.SIGHUP,signal.SIGINT,signal.SIGTERM):signal.raise_signal(kind)
                        raise RuntimeError('secondary unpause failure')
                    return subprocess.CompletedProcess(argv,0,'System uptime','')
                def concurrent(*args):return start([],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                try:
                    with mock.patch.object(test_phase1_sip_e2e,'start_fixture_process',side_effect=start),mock.patch.object(test_phase1_sip_e2e,'run',side_effect=run), \
                         mock.patch.object(test_phase1_sip_e2e,'start_concurrent_voice',side_effect=concurrent),mock.patch.object(test_phase1_sip_e2e,'observe_concurrent_resources',side_effect=primary),redirect_stdout(io.StringIO()):
                        with self.assertRaises(RuntimeError) as caught:
                            with test_phase1_sip_e2e.fixture_signals(),test_phase1_sip_e2e.fixture_directory(allow_preview=False) as (directory,_):
                                test_phase1_sip_e2e.run_fax_flow(['docker','compose'],{}, {'id':'fixture'},directory)
                    self.assertIs(primary,caught.exception)
                    self.assertEqual(['unpause'],events)
                    self.assertEqual(2,len(children));self.assertTrue(all(c.poll() is not None for c in children))
                    self.assertTrue(streams and all(stream.closed for stream in streams))
                    self.assertTrue(directory.exists())
                finally:
                    for child in children:
                        if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
                    if directory is not None:shutil.rmtree(directory)

    def test_actual_native_backup_tar_preserves_binary_and_reaps_owned_helper(self):
        import tempfile,os,hashlib
        root=Path(test_phase1_sip_e2e.ROOT);script=root/'scripts/create_phase1_backup.sh'
        before=hashlib.sha256(script.read_bytes()).hexdigest()
        for mode in ('success','failed-run','stop','outer-HUP','outer-INT','outer-TERM'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(prefix='phone-native-tar-test-') as raw:
                folder=Path(raw);binary=folder/'docker'
                binary.write_text('#!'+sys.executable+'\n'+r'''
import sys,os,json,signal
from pathlib import Path
a=sys.argv[1:];root=Path(os.environ['PHONE_NATIVE_FAKE']);path=root/'state.json'
state=json.loads(path.read_text()) if path.exists() else {'actor':None,'volumes':[]}
def save():path.write_text(json.dumps(state))
with (root/'calls').open('a') as log:log.write(json.dumps(a)+'\n')
if a[0]=='compose':
 if 'ps' in a and '--quiet' in a:print('b'*64)
 elif 'exec' in a:sys.stdout.buffer.write(b'pgdump\0synthetic')
 else:print('[]')
elif a[0]=='inspect' and '--format' in a:print('sha256:'+'c'*64)
elif a[0]=='run':
 assert '--rm' not in a
 labels={a[i+1].split('=',1)[0]:a[i+1].split('=',1)[1] for i,x in enumerate(a[:-1]) if x=='--label'}
 assert all('care.anshin.local.'+x in labels for x in ('ephemeral','owner','task_id','expires_at'))
 assert a[a.index('--volumes-from')+1]=='b'*64+':ro'
 assert labels['com.docker.compose.project']==labels['care.anshin.local.task_id']
 name=a[a.index('--name')+1]
 assert name==os.environ['PHONE_FIXTURE_HELPER_NAME']
 state['actor']={'Id':'a'*64,'Name':'/'+name,'Config':{'Labels':labels},'Mounts':[{'Type':'volume','Name':'d'*64}]};state['volumes']=['d'*64];save()
 if os.environ['PHONE_NATIVE_MODE']=='stop':os.kill(os.getppid(),signal.SIGHUP)
 if os.environ['PHONE_NATIVE_MODE'].startswith('outer-'):
  (root/'child-pids').write_text(json.dumps([os.getpid(),os.getppid()]))
  os.kill(int(os.environ['PHONE_OUTER_PID']),getattr(signal,'SIG'+os.environ['PHONE_NATIVE_MODE'][6:]))
 sys.stdout.buffer.write(b'encrypted-tar\0synthetic\xff')
 if os.environ['PHONE_NATIVE_MODE']=='failed-run':sys.exit(23)
elif a[0]=='ps':
 row=state['actor']
 if row:print(row['Id'])
elif a[0]=='inspect':print(json.dumps([state['actor']]))
elif a[0]=='rm':
 assert a[-1]==state['actor']['Id'];assert '-fv' in a
 state['actor']=None;state['volumes']=[];save()
elif a[:2]==['volume','ls']:print('\n'.join(state['volumes']))
else:sys.exit(91)
''')
                binary.chmod(0o700)
                env=dict(os.environ,PATH=str(folder)+':'+os.environ['PATH'],PHONE_NATIVE_FAKE=str(folder),
                    PHONE_NATIVE_MODE=mode,PHONE_TEST_EXPIRES_AT='2026-10-25T00:00:00+00:00',
                    ANSHIN_PHONE_BACKEND_DIR=str(root.parent.parent.parent.parent/'anshin-phone-backend'))
                # Use the registered primary backend supplied by the caller;
                # no worktree-parent inference supplies an implementation.
                env['ANSHIN_PHONE_BACKEND_DIR']=os.environ['ANSHIN_PHONE_BACKEND_DIR']
                with test_phase1_sip_e2e.fixture_signals() as state:
                    wrapped=test_phase1_sip_e2e.fixture_backup_environment(env,'anshin-phone-sip-test-abcdef12')
                    if mode.startswith('outer-'):
                        program="""import os,sys,signal
sys.path.insert(0,sys.argv[1])
import test_phase1_sip_e2e as owner
os.environ['PHONE_OUTER_PID']=str(os.getpid())
try:
 with owner.fixture_signals():
  owner.run(['bash',sys.argv[2],'--execute',sys.argv[3]],env=dict(os.environ),termination_grace=430)
except owner.FixtureInterrupted as stop:
 sys.exit(128+stop.signum)
raise SystemExit('stop was lost')
"""
                        result=subprocess.run([sys.executable,'-c',program,str(root/'scripts'),str(script),str(folder/'backup')],env=wrapped,capture_output=True,timeout=20)
                        self.assertEqual(128+getattr(__import__('signal'),'SIG'+mode[6:]),result.returncode,result.stderr.decode())
                    else:
                        result=subprocess.run(['bash',str(script),'--execute',str(folder/'backup')],env=wrapped,capture_output=True,timeout=20)
                    self.assertEqual({wrapped['PHONE_FIXTURE_HELPER_NAME']},set(state['attempted']))
                facts=json.loads((folder/'state.json').read_text())
                self.assertIsNone(facts['actor']);self.assertFalse(facts['volumes'])
                calls=[json.loads(line) for line in (folder/'calls').read_text().splitlines()]
                self.assertTrue(any(a[:1]==['rm'] for a in calls))
                self.assertFalse(any(a[:2]==['image','rm'] for a in calls))
                if mode=='success':
                    self.assertEqual(0,result.returncode,result.stderr.decode())
                    archives=list((folder/'backup').glob('*/fax-encrypted.tar'))
                    self.assertEqual(1,len(archives));self.assertEqual(b'encrypted-tar\0synthetic\xff',archives[0].read_bytes())
                else:self.assertNotEqual(0,result.returncode)
        self.assertEqual(before,hashlib.sha256(script.read_bytes()).hexdigest())

    def test_actual_native_capture_helper_create_loss_uses_registered_cleanup(self):
        import os,importlib.util
        from production_runtime import Runtime,RuntimeFailure
        import phone_postgresql_backup_adapter as native
        env=dict(os.environ,PHONE_TEST_EXPIRES_AT='2026-10-25T00:00:00+00:00')
        project='phone-management-capture';labels=test_phase1_sip_e2e.frozen_fixture_labels(project,env)
        for mode in ('partial-down','render-fails'):
         with self.subTest(mode=mode),test_phase1_sip_e2e.fixture_signals() as owner:
             manager=test_phase1_sip_e2e.fixture_manager(env)
             actors={};volumes=set();calls=[];image='sha256:'+'c'*64
             def driver(argv,**options):
                 calls.append(argv)
                 if argv[:2]==['docker','create']:
                     name=argv[argv.index('--name')+1]
                     care=dict(x.split('=',1) for flag,x in zip(argv,argv[1:]) if flag=='--label')
                     self.assertTrue(all(care.get(k)==v for k,v in labels.items()))
                     actors[name]={'Id':'a'*64,'Name':'/'+name,'Config':{'Labels':care,'Image':image},'Mounts':[{'Type':'volume','Name':'d'*64}]}
                     volumes.add('d'*64)
                     raise subprocess.TimeoutExpired('creation response lost',1)
                 if argv[:2]==['docker','ps'] or argv[:3]==['docker','container','ls']:
                     value='\n'.join(row['Id'] for row in actors.values())
                 elif argv[:3]==['docker','volume','ls']:value='\n'.join(volumes)
                 elif argv[:3]==['docker','network','ls'] or argv[:3]==['docker','image','ls']:value=''
                 elif 'inspect' in argv:value=json.dumps(list(actors.values()))
                 elif argv[:2]==['docker','rm']:actors.clear();volumes.clear();value=''
                 elif argv[:2]==['docker','compose'] and 'config' in argv:
                     if mode=='render-fails':raise subprocess.TimeoutExpired('cleanup config unavailable',30)
                     value=json.dumps({'services':{},'networks':{},'volumes':{}})
                 elif argv[:2]==['docker','compose'] and 'down' in argv:raise RuntimeError('partial native down')
                 else:self.fail(str(argv))
                 return subprocess.CompletedProcess(argv,0,value,'')
             with mock.patch.object(manager,'fixture_command',side_effect=driver):
                 runtime=Runtime(project=project,runner=test_phase1_sip_e2e.fixture_runtime_runner(project,env))
                 try:native.helper_create(runtime,{},'db',image,['--network','none'],['true'])
                 except RuntimeFailure as primary:
                     self.assertEqual('phone_capture_helper_creation_unknown',str(primary))
                     self.assertIn(project+'-backup-db',owner['attempted'])
                     with redirect_stdout(io.StringIO()):
                         test_phase1_sip_e2e.cleanup_owned_runtime(['docker','compose','--project-name',project],project,env,True)
                 else:self.fail('actual native helper did not propagate reply loss')
             self.assertFalse(actors);self.assertFalse(volumes)
             self.assertFalse(any(a[:3]==['docker','image','rm'] for a in calls))
             if mode=='render-fails':self.assertFalse(any('down' in a for a in calls))

    def test_cleanup_config_failure_uses_all_original_declarations_and_keeps_primary_inputs(self):
        import tempfile
        owner=test_phase1_sip_e2e
        project='phone-saved-declarations';env={'PHONE_TEST_EXPIRES_AT':'2026-10-25T00:00:00Z'}
        config={'services':{'backend':{'build':'.','image':project+':owned'}},
                'networks':{'private':{'name':project+'-original'},'foreign':{'name':'borrowed-network','external':True}},
                'volumes':{'data':{'name':project+'-data'},'foreign':{'name':'borrowed-volume','external':True}}}
        manager=mock.Mock();events=[]
        def cleanup(containers,networks,labels,**options):
            events.append(('assets',list(containers),list(networks),options.get('volumes',[])))
            if networks:raise RuntimeError('foreign collision retained')
        manager.cleanup_named_fixture_assets.side_effect=cleanup
        manager.cleanup_fixture_images.side_effect=lambda *args,**options:events.append(('images',options['allowed_tags']))
        manager.verify_fixture_project.side_effect=lambda *args,**options:events.append(('absent',options['absent'],options['config']))
        with tempfile.TemporaryDirectory() as raw,owner.fixture_signals() as state:
            source=Path(raw)/'source';source.write_text('preserve')
            owner.remember_fixture_config(project,config)
            # The owner holds a snapshot, unaffected by later consumer mutation.
            config['networks']['private']['name']='replacement-must-not-be-adopted'
            labels=owner.frozen_fixture_labels(project,env)
            state['attempted'][project+'-backup-db']=labels
            state['attempted']['foreign-helper']={**labels,'care.anshin.local.task_id':'foreign'}
            state['created_ids'][project+'-backup-db']='a'*64
            primary=RuntimeError('original business failure')
            with mock.patch.object(owner,'fixture_manager',return_value=manager),mock.patch.object(owner,'run',side_effect=subprocess.TimeoutExpired('config',30)) as run:
                try:
                    raise primary
                except RuntimeError as observed:
                    with redirect_stdout(io.StringIO()):owner.cleanup_owned_runtime(['docker','compose'],project,env,True)
                    self.assertIs(primary,observed)
            self.assertEqual('preserve',source.read_text())
            self.assertEqual(1,run.call_count) # No Compose down on unrendered input.
            self.assertIn(('assets',[project+'-backend-1',project+'-backup-db'],[project+'-original'],[project+'-data']),events)
            self.assertIn(('images',[project+':owned']),events)
            self.assertTrue(any(event[0]=='absent' and event[1] is True for event in events))
            self.assertNotIn('foreign-helper',str(events));self.assertNotIn('borrowed-',str(events[:2]))
            calls=manager.cleanup_named_fixture_assets.call_args_list
            self.assertEqual({project+'-backup-db':'a'*64},calls[-1].kwargs['expected_ids'])

    def test_native_compose_preflight_registers_services_and_pins_stop_identity(self):
        import os
        from production_runtime import Runtime
        env=dict(os.environ,PHONE_TEST_EXPIRES_AT='2026-10-25T00:00:00+00:00')
        project='phone-native-compose-test';identity='a'*64;network='b'*64
        labels=test_phase1_sip_e2e.frozen_fixture_labels(project,env)
        config={'services':{name:{'labels':labels} for name in ('backend','postgres')},
            'networks':{'private':{'name':project+'-hidden'}},'volumes':{}}
        with test_phase1_sip_e2e.fixture_signals() as owner:
            manager=test_phase1_sip_e2e.fixture_manager(env);calls=[];foreign=[True]
            def driver(argv,**options):
                calls.append(argv);value=''
                if argv[:2]==['docker','compose']:
                    if 'config' in argv:value=json.dumps(config)
                    elif 'up' in argv:
                        self.assertEqual({project+'-backend-1',project+'-postgres-1'},set(owner['attempted']))
                elif argv[:3]==['docker','network','ls'] and any('name=' in a for a in argv):value=network
                elif argv[:3]==['docker','network','inspect']:
                    value=json.dumps([{'Id':network,'Name':project+'-hidden','Labels':{} if foreign[0] else labels}])
                elif argv[:2]==['docker','inspect']:
                    value=json.dumps([{'Id':identity,'Name':'/'+project+'-backend-1','Config':{'Labels':labels}}])
                elif argv[:2] in (['docker','stop'],['docker','kill']):
                    self.assertEqual(identity,argv[-1])
                return subprocess.CompletedProcess(argv,0,value,'')
            with mock.patch.object(manager,'fixture_command',side_effect=driver):
                runner=test_phase1_sip_e2e.fixture_runtime_runner(project,env)
                up=['docker','compose','--project-name',project,'up','-d']
                runtime=Runtime(root=test_phase1_sip_e2e.ROOT,project=project,runner=runner)
                profile={'source_root':str(test_phase1_sip_e2e.ROOT),'backend_image':'sha256:'+'c'*64}
                with self.assertRaises(manager.DockerResourceError):
                    runtime.compose(profile,'run','--no-deps','--name',project+'-settings','backend','settings')
                with self.assertRaises(manager.DockerResourceError):runner(up,env=env,capture_output=True,text=True)
                self.assertFalse(any('up' in a or 'run' in a for a in calls));self.assertFalse(owner['attempted'])
                foreign[0]=False;runner(up,env=env,capture_output=True,text=True)
                runtime=Runtime(project=project,runner=runner)
                runtime.command(['docker','stop','--time','30',identity])
                runner(['docker','kill','--signal','TERM',project+'-backend-1'],env=env,capture_output=True,text=True)
                before=len(calls)
                with self.assertRaisesRegex(RuntimeError,'one final target'):
                    runner(['docker','stop',project+'-backend-1','foreign'],env=env)
                self.assertEqual(before,len(calls))

    def test_factory_return_boundary_and_repeated_reap_stop_keep_first_identity(self):
        import importlib.util, signal, os
        governance=Path(os.environ['ANSHIN_GOVERNANCE_ROOT'])
        spec=importlib.util.spec_from_file_location('phone_handoff_owner',governance/'scripts/local_docker_resource_manager.py')
        manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)
        native_command=manager.fixture_command
        for first in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM):
            with self.subTest(first=first):
                created=[]
                def command(argv,**options):
                    factory=options['process_factory']
                    def between_factory_and_manager(*args,**kwargs):
                        child=factory(*args,**kwargs);created.append(child)
                        communicate=child.communicate
                        def repeated(*a,**kw):
                            for kind in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM):signal.raise_signal(kind)
                            return communicate(*a,**kw)
                        child.communicate=repeated
                        # create() has returned, but fixture_command does not
                        # yet hold its process result: this is the former gap.
                        signal.raise_signal(first)
                        return child
                    options['process_factory']=between_factory_and_manager
                    return native_command(argv,**options)
                with mock.patch.object(test_phase1_sip_e2e,'fixture_manager',return_value=manager),mock.patch.object(manager,'fixture_command',side_effect=command):
                    with self.assertRaises(test_phase1_sip_e2e.FixtureInterrupted) as caught:
                        with test_phase1_sip_e2e.fixture_signals():
                            test_phase1_sip_e2e.run([sys.executable,'-c','import time;time.sleep(60)'],env=dict(os.environ))
                self.assertEqual(first,caught.exception.signum)
                self.assertEqual(1,len(created));self.assertIsNotNone(created[0].poll())

    def test_native_volume_observation_accepts_only_original_fixture_care_values(self):
        import stat,copy
        from production_runtime import Runtime, RuntimeFailure
        project='phone-management-observation';env={'PHONE_TEST_EXPIRES_AT':'2026-10-25T00:00:00+00:00'}
        care=test_phase1_sip_e2e.frozen_fixture_labels(project,env)
        for mode in ('valid','unrelated',*care):
            with self.subTest(mode=mode):
                inspections=[]
                def runner(argv,**options):
                    if argv[1:3]==['ps','--all']:value='a'*64
                    elif argv[1:3]==['volume','ls']:value=project+'_postgres-data'
                    elif argv[1:3]==['volume','inspect']:
                        labels={**care,'com.docker.compose.project':project,'com.docker.compose.volume':'postgres-data'}
                        if mode in care:labels[mode]='changed'
                        if mode=='unrelated':labels['foreign.extra']='keep-rejecting'
                        row={'Name':project+'_postgres-data','Driver':'local','Scope':'local','Options':{},
                            'Mountpoint':'/var/lib/docker/volumes/'+project+'_postgres-data/_data',
                            'CreatedAt':'2026-10-24T00:00:00Z','Labels':labels}
                        inspections.append(copy.deepcopy(row));value=json.dumps([row])
                    elif argv[1]=='inspect':value='native-original-container-projection'
                    else:self.fail(str(argv))
                    return subprocess.CompletedProcess(argv,0,value,'')
                runtime=Runtime(project=project,runner=runner,volume_stat=lambda path:{'mode':stat.S_IFDIR|0o700,'device':1,'inode':2})
                test_phase1_sip_e2e.fixture_volume_observation(runtime,project,env)
                if mode=='valid':
                    result=runtime.observation(timeout=5)
                    self.assertEqual({'device':1,'inode':2},result['volumes'][0]['backing'])
                    self.assertFalse(set(care).intersection(result['volumes'][0]['Labels']))
                    self.assertEqual(2,len(inspections));self.assertEqual(inspections[0],inspections[1])
                else:
                    with self.assertRaises((RuntimeError,RuntimeFailure)):runtime.observation(timeout=5)
                # Projection is local to the response; the daemon facts keep
                # their four original fixture ownership values.
                self.assertTrue(all(set(care).issubset(row['Labels']) for row in inspections))

    def test_creation_registration_stop_reaps_the_actual_owned_cli(self):
        import importlib.util, signal, os
        from pathlib import Path
        governance=Path(os.environ['ANSHIN_GOVERNANCE_ROOT'])
        spec=importlib.util.spec_from_file_location('phone_test_common_owner',governance/'scripts/local_docker_resource_manager.py')
        manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)
        native=subprocess.Popen
        for first in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM):
            with self.subTest(first=first):
                created=[]
                def popen(*args,**kwargs):
                    child=native(*args,**kwargs);created.append(child)
                    signal.raise_signal(first)
                    return child
                with mock.patch.object(test_phase1_sip_e2e,'fixture_manager',return_value=manager),mock.patch.object(test_phase1_sip_e2e.subprocess,'Popen',side_effect=popen):
                    with self.assertRaises(test_phase1_sip_e2e.FixtureInterrupted) as caught:
                        with test_phase1_sip_e2e.fixture_signals():
                            test_phase1_sip_e2e.run([sys.executable,'-c','import time;time.sleep(60)'],env=dict(os.environ))
                self.assertEqual(first,caught.exception.signum)
                self.assertEqual(1,len(created));self.assertIsNotNone(created[0].poll())

    def test_term_unwinds_fixture_cleanup_and_retains_inputs(self):
        import os,signal,shutil
        path=None;cleaned=[];previous=signal.getsignal(signal.SIGTERM)
        try:
            with mock.patch.dict(os.environ, {"PHONE_PREVIEW_DIR":""}):
                with self.assertRaises(test_phase1_sip_e2e.FixtureInterrupted) as caught:
                    with test_phase1_sip_e2e.fixture_signals(),test_phase1_sip_e2e.fixture_directory() as (path,_):
                        (path/"source").write_text("retain")
                        try:signal.raise_signal(signal.SIGTERM)
                        finally:cleaned.append(True)
            self.assertEqual(caught.exception.signum,signal.SIGTERM)
            self.assertEqual(cleaned,[True]);self.assertTrue((path/"source").exists())
            self.assertEqual(signal.getsignal(signal.SIGTERM),previous)
        finally:
            if path is not None:shutil.rmtree(path)

    def test_fixture_ownership_labels_cover_builds_and_preserve_external_assets(self):
        compiled={"services":{"backend":{"build":{"context":"fixture"}},"postgres":{"image":"postgres:16"}},
                  "networks":{"owned":{},"shared":{"external":True}},"volumes":{"owned":{},"shared":{"external":True}}}
        equivalent={"driver":"json-file","options":{"max-size":"10m","max-file":"5"}}
        silent={"driver":"none"}
        compiled["services"].update({"bounded":{"logging":equivalent},"silent":{"logging":silent},
                                     "unbounded":{"logging":{"driver":"json-file"}}})
        override=test_phase1_sip_e2e.fixture_ownership_override(compiled,"owned-fixture")
        self.assertEqual(override["services"]["bounded"]["logging"],equivalent)
        self.assertEqual(override["services"]["silent"]["logging"],silent)
        for name in ("backend","postgres","unbounded"):
            self.assertEqual(override["services"][name]["logging"],
                             {"driver":"local","options":{"max-size":"10m","max-file":"5"}})
        labels=test_phase1_sip_e2e.fixture_labels("owned-fixture",override["services"]["backend"]["labels"]["care.anshin.local.expires_at"])
        self.assertEqual(override["services"]["backend"]["build"]["labels"],labels)
        self.assertEqual(override["services"]["postgres"]["labels"],labels)
        for kind in ("volumes","networks"):
            self.assertEqual(override[kind],{"owned":{"labels":labels}})
        self.assertEqual(set(labels),{"care.anshin.local."+key for key in ("owner","task_id","ephemeral","expires_at")})

    def test_fixture_sources_survive_failed_cleanup(self):
        import os,shutil
        path = None
        try:
            with mock.patch.dict(os.environ, {"PHONE_PREVIEW_DIR":""}):
                with self.assertRaisesRegex(RuntimeError, "cleanup-unconfirmed"):
                    with test_phase1_sip_e2e.fixture_directory() as (path, state):
                        (path / "source").write_text("retain")
                        raise RuntimeError("cleanup-unconfirmed")
            self.assertTrue((path / "source").exists())
        finally:
            if path is not None:shutil.rmtree(path)
        with mock.patch.dict(os.environ, {"PHONE_PREVIEW_DIR":""}):
            with test_phase1_sip_e2e.fixture_directory() as (path, state):
                (path / "source").write_text("fixture")
        self.assertFalse(path.exists())

    def test_cleanup_defect_does_not_replace_an_earlier_test_failure(self) -> None:
        cleanup = subprocess.CompletedProcess([], 1, "cleanup failed")
        test_phase1_sip_e2e.ensure_cleanup_succeeded(cleanup, ["image"], True)


if __name__ == "__main__":
    unittest.main()
