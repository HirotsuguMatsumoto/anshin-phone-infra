#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
from contextlib import redirect_stdout
import hashlib
import json
import os
import sys
from unittest.mock import patch
from pathlib import Path
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spool = load_module("pbx_event_spool", ROOT / "deploy/asterisk/scripts/pbx_event_spool.py")
forwarder = load_module("pbx_event_forwarder", ROOT / "deploy/pbx-event-forwarder/forwarder.py")
management = load_module('pbx_management', ROOT / 'deploy/asterisk/scripts/pbx_management.py')
with patch.dict(sys.modules, {'pbx_management': management, 'pbx_event_spool': spool}):
    worker = load_module('pbx_fax_worker', ROOT / 'deploy/asterisk/scripts/pbx_fax_worker.py')
JOB = '00000000-0000-0000-0000-000000000002'
CLAIM = '00000000-0000-0000-0000-000000000003'
NEXT_CLAIM = '00000000-0000-0000-0000-000000000004'


class EventHandler(BaseHTTPRequestHandler):
    received: list[dict[str, object]] = []
    response_hook = None

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = raw if self.headers.get("Content-Type") == "image/tiff" else json.loads(raw)
        self.__class__.received.append(
            {
                "path": self.path,
                "token": self.headers.get("X-Anshin-Internal-Token"),
                "body": body,
            }
        )
        if self.path.startswith('/api/v1/fax-documents?'):
            response = {'id': '00000000-0000-0000-0000-000000000001', 'content_type': 'image/tiff', 'byte_count': len(raw), 'page_count': 1}
        elif self.path.endswith('/result'):
            response = {'id': JOB, 'tenant_id': 'anshin-phase1', 'status': {'sent': 'sent', 'permanent_failure': 'failed', 'retryable_failure': 'queued'}[body['outcome']], 'failure_code': body['failure_code']}
        else:
            response = body
        code = 200
        if self.__class__.response_hook:
            code, response = self.__class__.response_hook(self.path, body, response)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format: str, *args: object) -> None:
        return


class PbxEventPipelineTest(unittest.TestCase):
    def test_carrier_did_uses_to_and_optional_consistent_alert_info(self):
        for header, alert in [('<sip:0300000001@pbx.invalid>', ''),
                              ('"Customer" <sip:+81300000001@pbx.invalid>;tag=abc', '0300000001')]:
            self.assertEqual(management.inbound_did(header, alert), '0300000001')
        for header, alert in [('', ''), ('<sip:registration-contact@pbx.invalid>', ''),
                              ('<sip:0300000001@pbx.invalid>', '0300000002'),
                              ('<sip:0300000001@pbx.invalid>', 'malformed'),
                              ('<sip:0300000001@pbx.invalid>\r\nInjected: value', '')]:
            with self.subTest(header=header, alert=alert), self.assertRaises(ValueError):
                management.inbound_did(header, alert)

    def test_voice_route_captures_identity_before_dial_and_fax_stays_read_only(self):
        for mode, identity, extra in [("inbound", "0300000001", ["pbx-1"]),
                                      ("outbound", "2001", ["pbx-2"]),
                                      ("fax", "0300000002", [])]:
            with patch.dict(os.environ, {"ANSHIN_PHONE_TENANT_ID": "tenant"}), \
                    patch.object(sys, "stdin", io.StringIO("\n" + "200 result=1\n" * 3)), \
                    patch.object(management, "request", return_value={
                        "tenant_id": "tenant", "allowed": True,
                        "national_number": identity if mode != "outbound" else "0300000001",
                        "extensions": [] if mode == "fax" else ["2001"],
                    }) as request, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(management.authorize([mode, identity, *extra]), 0)
                self.assertIn('PHONE_ROUTE_ALLOWED "1"', output.getvalue())
                if mode == "fax":
                    self.assertTrue(request.call_args.args[0].startswith("/api/v1/pbx-route?"))
                    self.assertEqual(len(request.call_args.args), 1)
                else:
                    self.assertEqual(request.call_args.args[0], "/api/v1/pbx-route")
                    self.assertEqual(request.call_args.args[1]["pbx_unique_id"], extra[0])

    def test_voice_route_without_snapshot_or_backend_failure_never_dials(self):
        for arguments in [["outbound", "2001"], ["inbound", "0300000001", "bad/id"],
                          ["inbound", "0300000001", "pbx-1"]]:
            with patch.dict(os.environ, {"ANSHIN_PHONE_TENANT_ID": "tenant"}), \
                    patch.object(sys, "stdin", io.StringIO("\n" + "200 result=1\n" * 3)), \
                    patch.object(management, "request", side_effect=OSError("synthetic")) as request, \
                    redirect_stdout(io.StringIO()) as output:
                management.authorize(arguments)
                self.assertIn('PHONE_ROUTE_ALLOWED "0"', output.getvalue())
                if len(arguments) < 3 or "/" in arguments[2]:
                    request.assert_not_called()

    def test_answer_attribution_only_accepts_inbound_extensions(self):
        args = ["call", "tenant", "0300000001", "pbx-1", "inbound",
                "090****0000", "ANSWER", "2026-10-22T00:00:00Z",
                "2026-10-22T00:00:10Z", "2026-10-22T00:01:00Z"]
        self.assertEqual(spool.build_event(args + ["2001"])["payload"]["answered_extension"], "2001")
        self.assertNotIn("answered_extension", spool.build_event(args + ["-"])["payload"])
        args[4] = "outbound"
        self.assertNotIn("answered_extension", spool.build_event(args + ["-"])["payload"])
        for extension in ["2001", "carrier-endpoint"]:
            with self.assertRaises(ValueError):
                spool.build_event(args + [extension])

    def setUp(self) -> None:
        EventHandler.received.clear()
        EventHandler.response_hook = None

    def run_forwarder(self, root, originals):
        server = ThreadingHTTPServer(('127.0.0.1', 0), EventHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {'PBX_FAX_SPOOL_DIR': str(originals)}):
                return forwarder.process_once(root, 'test-internal-token', f'http://127.0.0.1:{server.server_address[1]}')
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def attempt(self, root, *, status='SUCCESS', dial='ANSWER', claim=CLAIM):
        original = root / (JOB + '-' + claim + '.tif')
        original.write_bytes(b'synthetic-sent-TIFF')
        with patch.object(spool, 'FAX_ROOT', root), patch.object(worker, 'write_event', lambda event: spool.write_event(event, root)), patch.dict(os.environ, {'ANSHIN_PHONE_TENANT_ID': 'anshin-phase1'}):
            worker.complete([JOB, claim, status, dial])
        return original, root / 'pending' / ('fax-attempt-' + claim + '.json')

    def test_call_event_is_masked_written_and_forwarded(self) -> None:
        event = spool.build_event(
            [
                "call",
                "anshin-phase1",
                "0300000001",
                "pbx-test-001",
                "inbound",
                "09012340000",
                "ANSWER",
                "2026-08-21T00:00:00Z",
                "-",
                "2026-08-21T00:01:00Z",
                "2001",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="anshin-phone-event-test-") as temp_dir:
            root = Path(temp_dir)
            path = spool.write_event(event, root)
            stored = path.read_text(encoding="utf-8")
            self.assertNotIn("09012340000", stored)
            self.assertIn("090****0000", stored)

            server = ThreadingHTTPServer(("127.0.0.1", 0), EventHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = forwarder.process_once(
                    root,
                    "test-internal-token",
                    f"http://127.0.0.1:{server.server_address[1]}",
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

            self.assertEqual(result, (1, 0, 0))
            self.assertFalse(path.exists())
            self.assertTrue((root / "sent" / path.name).exists())
            self.assertEqual(EventHandler.received[0]["path"], "/api/v1/pbx-events/calls")
            self.assertEqual(EventHandler.received[0]["token"], "test-internal-token")
            self.assertEqual(EventHandler.received[0]["body"]["answered_extension"], "2001")

    def test_fax_reference_contains_only_spool_basename(self) -> None:
        event = spool.build_event(
            [
                "fax",
                "anshin-phase1",
                "0300000002",
                "pbx-fax-001",
                "inbound",
                "090****0000",
                "SUCCESS",
                "2026-08-21T00:00:00Z",
                "/var/spool/asterisk/fax/test-fax.tif",
            ]
        )
        payload = event["payload"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["storage_reference"], "fax-spool://test-fax.tif")

    def test_original_upload_precedes_history_and_cleanup_waits_for_consumer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="anshin-phone-event-test-") as temp_dir:
            root = Path(temp_dir)
            originals = root / "originals"
            originals.mkdir()
            original = originals / "synthetic.tif"
            original.write_bytes(b"synthetic-unit-pipeline-input")
            with patch.object(spool, 'FAX_ROOT', originals):
                event = spool.build_event(["fax", "anshin-phase1", "0300000002", "pbx-fax-upload-001", "inbound", "090****0000", "SUCCESS", "2026-08-21T00:00:00Z", str(original)])
            path = spool.write_event(event, root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), EventHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.dict(os.environ, {"PBX_FAX_SPOOL_DIR": str(originals)}):
                    result = forwarder.process_once(root, "test-internal-token", f"http://127.0.0.1:{server.server_address[1]}")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            self.assertEqual(result, (1, 0, 0))
            self.assertTrue(EventHandler.received[0]["path"].startswith("/api/v1/fax-documents?"))
            self.assertEqual(EventHandler.received[1]["path"], "/api/v1/pbx-events/faxes")
            self.assertEqual(EventHandler.received[1]["body"]["storage_reference"], "fax-document:00000000-0000-0000-0000-000000000001")
            self.assertFalse(original.exists())
            self.assertTrue((root / "sent" / path.name).exists())

    def test_malformed_event_is_moved_to_dead_letter(self) -> None:
        with tempfile.TemporaryDirectory(prefix="anshin-phone-event-test-") as temp_dir:
            root = Path(temp_dir)
            pending = root / "pending"
            pending.mkdir()
            malformed = pending / "malformed.json"
            malformed.write_text('{"kind":"unknown","payload":{}}', encoding="utf-8")

            result = forwarder.process_once(root, "test-internal-token", "http://127.0.0.1:1")

            self.assertEqual(result, (0, 1, 0))
            self.assertTrue((root / "dead-letter" / malformed.name).exists())

    def test_completion_retains_source_until_matching_ack_and_never_cleans_new_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, event = self.attempt(root)
            newer = root / (JOB + '-' + NEXT_CLAIM + '.tif')
            newer.write_bytes(b'new-attempt')
            self.assertTrue(original.exists())
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertFalse(original.exists())
            self.assertTrue(newer.exists())
            self.assertNotIn('fax_local', EventHandler.received[-1]['body'])
            # Replayed exact completion is safe and cannot consume a retry.
            original, event = self.attempt(root)
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertFalse(original.exists())

    def test_unknown_timeout_and_conflicting_ack_preserve_source(self):
        for code, overrides, expected in [(503, {}, (0, 0, 1)), (409, {}, (0, 1, 0)), (200, {'status': 'failed', 'failure_code': 'DELIVERY_UNCONFIRMED'}, (0, 1, 0)), (200, {'tenant_id': 'other'}, (0, 1, 0))]:
            with self.subTest(code=code, overrides=overrides), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original, event = self.attempt(root)
                EventHandler.response_hook = lambda path, body, result: (code, dict(result, **overrides))
                self.assertEqual(self.run_forwarder(root, root), expected)
                self.assertTrue(original.exists())
        EventHandler.response_hook = None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, event = self.attempt(root, status='UNKNOWN', dial='UNKNOWN')
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertTrue(original.exists())

    def test_network_failure_and_replacement_during_ack_preserve_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, event = self.attempt(root)
            with patch.dict(os.environ, {'PBX_FAX_SPOOL_DIR': str(root)}):
                self.assertEqual(forwarder.process_once(root, 'test', 'http://127.0.0.1:1'), (0, 0, 1))
            self.assertTrue(original.exists())
            def replace_source(path, body, result):
                replacement = root / 'replacement'
                replacement.write_bytes(original.read_bytes())
                replacement.replace(original)
                return 200, result
            EventHandler.response_hook = replace_source
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertTrue(original.exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, event = self.attempt(root)
            def replace_event(path, body, result):
                replacement = root / 'replacement'
                replacement.write_bytes(event.read_bytes())
                replacement.replace(event)
                return 200, result
            EventHandler.response_hook = replace_event
            self.assertEqual(self.run_forwarder(root, root), (0, 0, 1))
            self.assertTrue(event.exists()); self.assertTrue(original.exists())

    def test_sent_move_failure_and_unlink_failure_preserve_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, event = self.attempt(root)
            with patch.object(forwarder, 'move', side_effect=OSError):
                self.assertEqual(self.run_forwarder(root, root), (0, 0, 1))
            self.assertTrue(event.exists()); self.assertTrue(original.exists())
            with patch.object(forwarder.os, 'unlink', side_effect=PermissionError):
                self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertTrue(original.exists())

    def test_received_history_ack_failure_retains_source_and_replay_exact_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'received.tif'; original.write_bytes(b'synthetic-received-TIFF')
            with patch.object(spool, 'FAX_ROOT', root):
                event = spool.build_event(['fax', 'anshin-phase1', '0300000002', 'received-1', 'inbound', '090****0000', 'SUCCESS', '2026-08-21T00:00:00Z', str(original)])
            pending = spool.write_event(event, root)
            EventHandler.response_hook = lambda path, body, result: (200, dict(result, storage_reference='fax-document:wrong')) if path.endswith('/faxes') else (200, result)
            self.assertEqual(self.run_forwarder(root, root), (0, 1, 0))
            self.assertTrue(original.exists())
            dead = root / 'dead-letter' / pending.name
            digest = hashlib.sha256(dead.read_bytes()).hexdigest()
            with self.assertRaises(ValueError): forwarder.replay_dead_letter(root, '../' + dead.name, digest)
            with self.assertRaises(ValueError): forwarder.replay_dead_letter(root, dead.name, '0' * 64)
            pending.write_text('collision')
            with self.assertRaises(FileExistsError): forwarder.replay_dead_letter(root, dead.name, digest)
            pending.unlink()
            untouched = root / 'dead-letter' / 'untouched.json'; untouched.write_text('{}')
            forwarder.replay_dead_letter(root, dead.name, digest)
            self.assertTrue(untouched.exists()); self.assertFalse(dead.exists())
            EventHandler.response_hook = None
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertFalse(original.exists())

    def test_delayed_callfile_does_not_adopt_new_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(worker, 'CALL_ROOT', root):
                worker.enqueue({'id': JOB, 'claim_id': CLAIM})
            callfile = root / 'outgoing' / (JOB + '-' + CLAIM + '.call')
            self.assertIn('__FAX_QUEUED_CLAIM_ID=' + CLAIM, callfile.read_text())
            with patch.dict(os.environ, {'ANSHIN_PHONE_TENANT_ID': 'anshin-phase1'}), patch.object(worker, 'request', return_value={'id': JOB, 'tenant_id': 'anshin-phase1', 'claim_id': NEXT_CLAIM}), patch.object(worker, 'set_variable') as variable:
                self.assertEqual(worker.prepare(JOB, CLAIM), 0)
                variable.assert_called_once_with('FAX_JOB_READY', '0')

    def test_metadata_inspection_failure_preserves_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(worker, 'fax_local_source', side_effect=ValueError('oversize')):
                original, event = self.attempt(root)
            self.assertNotIn('fax_local', json.loads(event.read_text()))
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertTrue(original.exists())

    def test_attempt_result_survives_missing_or_changed_source_after_spooling(self):
        for missing in (True, False):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original, event = self.attempt(root)
                if missing: original.unlink()
                else: original.write_bytes(b'changed-after-event')
                self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
                self.assertEqual(EventHandler.received[-1]['body']['outcome'], 'sent')
                self.assertEqual(original.exists(), not missing)

    def test_legacy_receive_delivery_and_exact_replay_preserve_unbound_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'legacy.tif'; original.write_bytes(b'synthetic-legacy-TIFF')
            with patch.object(spool, 'fax_local_source', side_effect=ValueError('unavailable')):
                event = spool.build_event(['fax', 'anshin-phase1', '0300000002', 'legacy-receive', 'inbound', '090****0000', 'SUCCESS', '2026-08-21T00:00:00Z', str(original)])
            path = spool.write_event(event, root)
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertTrue(original.exists())
            # Existing old-format DLQ can be replayed without adopting its file
            # for deletion or making a physical FAX transmission.
            dead = root / 'dead-letter'; dead.mkdir()
            source = dead / path.name; source.write_text(json.dumps(event))
            forwarder.replay_dead_letter(root, source.name, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(self.run_forwarder(root, root), (1, 0, 0))
            self.assertTrue(original.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
