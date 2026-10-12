#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
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


class EventHandler(BaseHTTPRequestHandler):
    received: list[dict[str, object]] = []

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
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"id":"00000000-0000-0000-0000-000000000001"}' if self.path.startswith("/api/v1/fax-documents?") else b"{}")

    def log_message(self, format: str, *args: object) -> None:
        return


class PbxEventPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        EventHandler.received.clear()

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
