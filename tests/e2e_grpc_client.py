#!/usr/bin/env python3
"""End-to-end gRPC client tests for Docling Serve.

Requires a running gRPC server (docling-serve-grpc run --port PORT).
Usage:
    python tests/e2e_grpc_client.py [--port PORT] [--pdf PATH]

Default port: 50051
Default PDF:  tests/2206.01062v1.pdf
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import grpc

# Add the repo root so we can import generated stubs
REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2 as pb2,
    docling_serve_pb2_grpc as pb2_grpc,
    docling_serve_types_pb2 as types_pb2,
)


class GrpcE2ETests:
    """End-to-end gRPC client tests."""

    def __init__(self, host: str, port: int, pdf_path: Path | None):
        self.address = f"{host}:{port}"
        self.pdf_path = pdf_path
        self.passed = 0
        self.failed = 0
        self.skipped = 0

        # 2 GB message limits
        options = [
            ("grpc.max_send_message_length", 2 * 1024 * 1024 * 1024 - 1),
            ("grpc.max_receive_message_length", 2 * 1024 * 1024 * 1024 - 1),
        ]
        self.channel = grpc.insecure_channel(self.address, options=options)
        self.stub = pb2_grpc.DoclingServeServiceStub(self.channel)

    def _pass(self, name: str, detail: str = ""):
        self.passed += 1
        msg = f"  PASS: {name}"
        if detail:
            msg += f" ({detail})"
        print(msg)

    def _fail(self, name: str, detail: str = ""):
        self.failed += 1
        msg = f"  FAIL: {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    def _skip(self, name: str, reason: str = ""):
        self.skipped += 1
        msg = f"  SKIP: {name}"
        if reason:
            msg += f" — {reason}"
        print(msg)

    def _make_file_request(
        self,
        filename: str = "test.pdf",
        options: types_pb2.ConvertDocumentOptions | None = None,
    ) -> types_pb2.ConvertDocumentRequest:
        """Build a ConvertDocumentRequest from the test PDF."""
        if self.pdf_path is None or not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")
        b64 = base64.b64encode(self.pdf_path.read_bytes()).decode()
        source = types_pb2.Source(
            file=types_pb2.FileSource(base64_string=b64, filename=filename)
        )
        req = types_pb2.ConvertDocumentRequest(sources=[source])
        if options:
            req.options.CopyFrom(options)
        return req

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_health(self):
        print("\n=== 1. Health Check ===")
        resp = self.stub.Health(pb2.HealthRequest())
        if resp.status:
            self._pass("Health status", resp.status)
        else:
            self._fail("Health status", "empty status")
        if resp.version:
            self._pass("Health version", resp.version)
        else:
            self._fail("Health version", "empty version")

    def test_convert_source(self):
        print("\n=== 2. ConvertSource (unary, real PDF) ===")
        if not self.pdf_path or not self.pdf_path.exists():
            self._skip("ConvertSource", "no test PDF")
            return

        t0 = time.monotonic()
        req = pb2.ConvertSourceRequest(request=self._make_file_request())
        resp = self.stub.ConvertSource(req)
        elapsed = time.monotonic() - t0

        doc = resp.response.document
        if doc.doc.schema_name == "DoclingDocument":
            self._pass("schema_name", doc.doc.schema_name)
        else:
            self._fail("schema_name", f"got {doc.doc.schema_name!r}")

        if doc.doc.name:
            self._pass("doc.name", doc.doc.name)
        else:
            self._fail("doc.name", "empty")

        if len(doc.doc.texts) > 0:
            self._pass("texts", f"{len(doc.doc.texts)} text items")
        else:
            self._fail("texts", "no text items")

        if len(doc.doc.body.children) > 0:
            self._pass("body.children", f"{len(doc.doc.body.children)} children")
        else:
            self._fail("body.children", "empty body")

        if doc.doc.origin.mimetype:
            self._pass("origin.mimetype", doc.doc.origin.mimetype)
        else:
            self._fail("origin.mimetype", "empty")

        # Check pages
        if len(doc.doc.pages) > 0:
            self._pass("pages", f"{len(doc.doc.pages)} page(s)")
            for page_no, page in doc.doc.pages.items():
                if page.size.width > 0 and page.size.height > 0:
                    self._pass(
                        f"page[{page_no}].size",
                        f"{page.size.width:.0f}x{page.size.height:.0f}",
                    )
                    break
        else:
            self._fail("pages", "no pages")

        # Tables (optional, depends on PDF content)
        if len(doc.doc.tables) > 0:
            self._pass("tables", f"{len(doc.doc.tables)} table(s)")
        else:
            print("  INFO: no tables (may be expected for this PDF)")

        print(f"  Conversion took {elapsed:.2f}s")

    def test_convert_source_stream(self):
        print("\n=== 3. ConvertSourceStream (server streaming, real PDF) ===")
        if not self.pdf_path or not self.pdf_path.exists():
            self._skip("ConvertSourceStream", "no test PDF")
            return

        req = pb2.ConvertSourceStreamRequest(request=self._make_file_request())
        t0 = time.monotonic()
        responses = list(self.stub.ConvertSourceStream(req))
        elapsed = time.monotonic() - t0

        if len(responses) > 0:
            self._pass("stream responses", f"{len(responses)} message(s)")
        else:
            self._fail("stream responses", "no messages received")
            return

        last = responses[-1]
        if last.response.document.doc.schema_name == "DoclingDocument":
            self._pass("stream final document", "DoclingDocument")
        else:
            self._fail(
                "stream final document",
                f"got {last.response.document.doc.schema_name!r}",
            )

        print(f"  Stream completed in {elapsed:.2f}s")

    def test_watch_convert_source(self):
        print("\n=== 4. WatchConvertSource (server streaming with status) ===")
        if not self.pdf_path or not self.pdf_path.exists():
            self._skip("WatchConvertSource", "no test PDF")
            return

        req = pb2.WatchConvertSourceRequest(request=self._make_file_request())
        t0 = time.monotonic()
        statuses = []
        for msg in self.stub.WatchConvertSource(req):
            statuses.append(msg.response)
        elapsed = time.monotonic() - t0

        if len(statuses) > 0:
            self._pass("watch responses", f"{len(statuses)} status update(s)")
        else:
            self._fail("watch responses", "no messages")
            return

        last = statuses[-1]
        if last.task_id:
            self._pass("task_id", last.task_id)
        else:
            self._fail("task_id", "empty")

        # Terminal status should be SUCCESS
        status_name = types_pb2.TaskStatus.Name(last.task_status)
        if last.task_status == types_pb2.TASK_STATUS_SUCCESS:
            self._pass("terminal status", status_name)
        else:
            self._fail("terminal status", f"got {status_name}")

        print(f"  Watch completed in {elapsed:.2f}s")

    def test_convert_with_json_export(self):
        print("\n=== 5. ConvertSource with JSON export ===")
        if not self.pdf_path or not self.pdf_path.exists():
            self._skip("JSON export", "no test PDF")
            return

        opts = types_pb2.ConvertDocumentOptions(
            to_formats=[types_pb2.OUTPUT_FORMAT_JSON]
        )
        req = pb2.ConvertSourceRequest(request=self._make_file_request(options=opts))
        resp = self.stub.ConvertSource(req)

        doc = resp.response.document
        json_str = doc.exports.json
        if json_str:
            self._pass("json export", f"{len(json_str)} bytes")
            try:
                parsed = json.loads(json_str)
                if "schema_name" in parsed:
                    self._pass("json content", "valid DoclingDocument JSON")
                else:
                    self._fail("json content", "missing schema_name in JSON")
            except json.JSONDecodeError as e:
                self._fail("json content", f"invalid JSON: {e}")
        else:
            self._fail("json export", "empty json field")

    def test_convert_with_markdown_export(self):
        print("\n=== 6. ConvertSource with Markdown export ===")
        if not self.pdf_path or not self.pdf_path.exists():
            self._skip("Markdown export", "no test PDF")
            return

        opts = types_pb2.ConvertDocumentOptions(to_formats=[types_pb2.OUTPUT_FORMAT_MD])
        req = pb2.ConvertSourceRequest(request=self._make_file_request(options=opts))
        resp = self.stub.ConvertSource(req)

        doc = resp.response.document
        md_str = doc.exports.md
        if md_str:
            self._pass("markdown export", f"{len(md_str)} chars")
            if len(md_str.strip()) > 10:
                self._pass("markdown content", "non-trivial content")
            else:
                self._fail("markdown content", "suspiciously short")
        else:
            self._fail("markdown export", "empty md field")

    def test_convert_empty_source_rejected(self):
        print("\n=== 7. ConvertSource with empty source (expect error) ===")
        try:
            req = pb2.ConvertSourceRequest(
                request=types_pb2.ConvertDocumentRequest(
                    sources=[types_pb2.Source()]  # no oneof variant set
                )
            )
            self.stub.ConvertSource(req)
            self._fail("empty source", "no error raised")
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                self._pass("empty source rejected", e.details())
            else:
                self._fail("empty source", f"wrong status: {e.code()} — {e.details()}")

    def test_convert_no_sources_rejected(self):
        print("\n=== 8. ConvertSource with no sources (expect error) ===")
        try:
            req = pb2.ConvertSourceRequest(
                request=types_pb2.ConvertDocumentRequest(sources=[])
            )
            self.stub.ConvertSource(req)
            self._fail("no sources", "no error raised")
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                self._pass("no sources rejected", e.details())
            else:
                self._fail("no sources", f"wrong status: {e.code()} — {e.details()}")

    def test_async_workflow(self):
        print("\n=== 9. Async workflow: submit -> poll -> get result ===")
        if not self.pdf_path or not self.pdf_path.exists():
            self._skip("Async workflow", "no test PDF")
            return

        # Step 1: Submit async
        req = pb2.ConvertSourceAsyncRequest(request=self._make_file_request())
        submit_resp = self.stub.ConvertSourceAsync(req)
        task_id = submit_resp.response.task_id

        if task_id:
            self._pass("async submit", f"task_id={task_id}")
        else:
            self._fail("async submit", "no task_id")
            return

        # Step 2: Poll until done
        t0 = time.monotonic()
        terminal = False
        status = None
        status_name = ""
        for _ in range(120):
            poll_req = pb2.PollTaskStatusRequest(
                request=types_pb2.TaskStatusPollRequest(task_id=task_id, wait_time=1.0)
            )
            poll_resp = self.stub.PollTaskStatus(poll_req)
            status = poll_resp.response.task_status
            status_name = types_pb2.TaskStatus.Name(status)
            if status in (
                types_pb2.TASK_STATUS_SUCCESS,
                types_pb2.TASK_STATUS_FAILURE,
            ):
                terminal = True
                break
            time.sleep(0.5)
        elapsed = time.monotonic() - t0

        if terminal and status == types_pb2.TASK_STATUS_SUCCESS:
            self._pass("poll terminal status", f"{status_name} in {elapsed:.1f}s")
        elif terminal:
            self._fail("poll terminal status", f"{status_name}")
            return
        else:
            self._fail("poll timeout", "did not reach terminal status")
            return

        # Step 3: Get result
        get_req = pb2.GetConvertResultRequest(
            request=types_pb2.TaskResultRequest(task_id=task_id)
        )
        result_resp = self.stub.GetConvertResult(get_req)
        doc = result_resp.response.document
        if doc.doc.schema_name == "DoclingDocument":
            self._pass("get result", "DoclingDocument")
        else:
            self._fail("get result", f"got {doc.doc.schema_name!r}")

    def test_clear_converters(self):
        print("\n=== 10. ClearConverters ===")
        self.stub.ClearConverters(pb2.ClearConvertersRequest())
        self._pass("ClearConverters", "no error")

    def test_clear_results(self):
        print("\n=== 11. ClearResults ===")
        self.stub.ClearResults(pb2.ClearResultsRequest())
        self._pass("ClearResults", "no error")

    def run_all(self):
        print(f"Connecting to gRPC server at {self.address}")
        if self.pdf_path:
            print(
                f"Test PDF: {self.pdf_path}"
                f" ({self.pdf_path.stat().st_size / 1024:.0f} KB)"
            )
        print()

        self.test_health()
        self.test_convert_source()
        self.test_convert_source_stream()
        self.test_watch_convert_source()
        self.test_convert_with_json_export()
        self.test_convert_with_markdown_export()
        self.test_convert_empty_source_rejected()
        self.test_convert_no_sources_rejected()
        self.test_async_workflow()
        self.test_clear_converters()
        self.test_clear_results()

        print("\n" + "=" * 50)
        total = self.passed + self.failed + self.skipped
        print(
            f"Results: {self.passed} passed, {self.failed} failed,"
            f" {self.skipped} skipped ({total} total)"
        )
        if self.failed > 0:
            print("SOME TESTS FAILED")
            return 1
        print("ALL TESTS PASSED")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="E2E gRPC client tests for Docling Serve"
    )
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=50051, help="Server port")
    parser.add_argument("--pdf", type=str, default=None, help="Path to test PDF")
    args = parser.parse_args()

    if args.pdf:
        pdf_path = Path(args.pdf)
    else:
        pdf_path = Path(__file__).parent / "2206.01062v1.pdf"

    if not pdf_path.exists():
        print(f"WARNING: test PDF not found at {pdf_path}")
        print("PDF-dependent tests will be skipped.")
        pdf_path = None

    tests = GrpcE2ETests(args.host, args.port, pdf_path)
    sys.exit(tests.run_all())


if __name__ == "__main__":
    main()
