"""Smoke extraction across source/target/model combinations.

Complements extraction_s3_to_s3_lmstudio.py (which only proves file->S3 with
Granite Vision) by exercising the other source/target pairings the extract
endpoint supports through DoclingServiceClient (extract/extract_all for in-body,
submit_extract for storage targets), for both an LM Studio-served vision model and a plain
OpenAI-API model behind llama-server.

``--doc-format`` switches the PDF for a generated DOCX/Markdown/HTML source
without pages. Such a source runs once as text with a document scope; a model
that accepts no text payload (Granite) must fail with an explicit channel error.

``--page-range``, ``--schema-fail`` and ``--callback-url`` cover page ranges, schema
validation failures and callback delivery through the service.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path

import boto3
import docx
import httpx
from botocore.exceptions import ClientError

from docling.datamodel.extraction import ExtractionTarget, ExtractionTemplate
from docling.datamodel.extraction_options import ExtractionVlmOptions
from docling.datamodel.service.callbacks import CallbackSpec
from docling.datamodel.service.options import ExtractDocumentsOptions
from docling.datamodel.service.requests import S3SourceRequest
from docling.datamodel.service.responses import (
    PresignedUrlConvertDocumentResponse,
    PresignedUrlConvertResponse,
)
from docling.datamodel.service.targets import PresignedUrlTarget, S3Target
from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions
from docling.models.inference_engines.vlm.base import VlmEngineType
from docling.service_client import DoclingServiceClient
from docling.service_client.exceptions import ServiceError

from scripts.local_smoke._common import (
    load_config,
    print_json,
    require,
    unique_run_id,
    validate_extraction_item,
)

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

# prompt_only schema no answer can satisfy (--schema-fail). A plain integer is
# not enough: Granite sees the schema and answered {"title": 2022}.
FAIL_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "integer", "minimum": 1, "maximum": 0}},
    "required": ["title"],
    "additionalProperties": False,
}

UNPAGINATED_FORMATS = ("docx", "md", "html")
TITLE = "Docling Technical Report"
BODY = "Docling converts PDF, DOCX and HTML documents into one unified representation."

MODEL_CONFIGS = {
    "granite": {
        "preset_id": "granite_vision_4_1",
        "engine_type": VlmEngineType.API_LMSTUDIO,
        "default_url": "http://127.0.0.1:1234/v1/chat/completions",
        "default_model": "granite-vision-4.1-4b",
        # generic_chat prompting: an example_json template adds illustrative guidance.
        "template": ExtractionTemplate(
            format="example_json", value={"title": "Example paper title"}
        ),
    },
    "nuextract": {
        "preset_id": "nuextract_3",
        "engine_type": VlmEngineType.API,
        "default_url": "http://127.0.0.1:1235/v1/chat/completions",
        "default_model": "numind/NuExtract3-GGUF:Q5_K_M",
        # NuExtract's own "structured" prep only accepts its native template
        # dialect (or none, auto-derived from output_schema); reject example_json.
        "template": None,
    },
}


def ensure_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)


def start_http_server(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(directory)
    )
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def start_callback_receiver(
    s3, bucket: str, prefix_ref: list[str]
) -> tuple[http.server.ThreadingHTTPServer, str, list[dict]]:
    """Record progress callbacks and artifact availability.

    For DOCUMENT_COMPLETED it also records whether that document's
    ``.extraction.json`` is already under the S3 target prefix, which proves the
    upload precedes the callback.
    """
    events: list[dict] = []
    lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            progress = body["progress"]
            event = {"kind": progress["kind"], "progress": progress}
            with lock:  # arrival order, before the slower artifact check below
                events.append(event)
            if progress["kind"] == "document_completed" and prefix_ref:
                stem = Path(progress["document"]["source"]).stem
                keys = [
                    o["Key"]
                    for o in s3.list_objects_v2(
                        Bucket=bucket, Prefix=prefix_ref[0]
                    ).get("Contents", [])
                ]
                event["artifact_present"] = any(
                    k.endswith(f"{stem}.extraction.json") for k in keys
                )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/callback", events


def check_callbacks(
    events: list[dict], expected_docs: int, check_uploads: bool
) -> None:
    deadline = time.monotonic() + 30
    while not any(e["kind"] == "task_completed" for e in events):
        require(time.monotonic() < deadline, f"No task_completed callback: {events}")
        time.sleep(0.5)
    time.sleep(1)  # let any straggler arrive so misordering is visible
    print("received callbacks:")
    print_json(
        [
            {k: v for k, v in e.items() if k != "progress"}
            | (
                {"source": e["progress"]["document"]["source"]}
                if e["kind"] == "document_completed"
                else {}
            )
            for e in events
        ]
    )
    kinds = [e["kind"] for e in events]
    expected = (
        ["set_num_docs"]
        + ["document_completed"] * expected_docs
        + ["update_processed", "task_completed"]
    )
    require(
        sorted(kinds) == sorted(expected),
        f"Expected callbacks {expected}, got {kinds}.",
    )
    require(
        next(e for e in events if e["kind"] == "set_num_docs")["progress"]["num_docs"]
        == expected_docs,
        f"set_num_docs must report {expected_docs} documents.",
    )
    if check_uploads:
        require(
            all(
                e.get("artifact_present") is True
                for e in events
                if e["kind"] == "document_completed"
            ),
            "A document_completed callback arrived before its upload.",
        )


def write_unpaginated_doc(fmt: str, directory: Path) -> Path:
    """Write a small source whose converted document has no pages."""
    path = directory / f"extract-smoke.{fmt}"
    if fmt == "md":
        path.write_text(f"# {TITLE}\n\n{BODY}\n")
    elif fmt == "html":
        path.write_text(f"<html><body><h1>{TITLE}</h1><p>{BODY}</p></body></html>")
    else:
        document = docx.Document()
        document.add_heading(TITLE, 0)
        document.add_paragraph(BODY)
        document.save(str(path))
    return path


def check_document(
    document: dict,
    expected_scopes: list[dict],
    expect_no_channel: bool,
    schema_fail: bool = False,
) -> None:
    """Check one in-body, presigned or stored extraction document payload."""
    if expect_no_channel:
        require(
            document["status"] == "failure",
            f"Expected a failed document, got {document['status']}.",
        )
        require(
            any("No channel works" in e["error_message"] for e in document["errors"]),
            f"Expected a 'No channel works' error, got {document['errors']}.",
        )
        require(not document["items"], "A failed channel must not produce items.")
        return
    scopes = [item["scope"] for item in document["items"]]
    require(
        scopes == expected_scopes, f"Expected scopes {expected_scopes}, got {scopes}."
    )
    if schema_fail:
        # Docling status rule: no item with extracted_data -> failure; some -> partial.
        require(
            document["status"] != "success",
            "A failed schema validation must not yield a success status.",
        )
        for item in document["items"]:
            require(
                item["validation_status"] == "failed",
                f"Expected validation_status failed, got {item['validation_status']}.",
            )
            require(bool(item["raw_text"]), "raw_text must be kept on failure.")
            require(item["extracted_data"] is None, "Failed items keep no data.")
            require(
                any(
                    e["error_message"].startswith("Schema validation at")
                    for e in item["errors"]
                ),
                f"Expected a structured validation ErrorItem, got {item['errors']}.",
            )
        print(f"schema-fail document status: {document['status']}")
        return
    require(
        document["status"] == "success",
        f"Unexpected extraction status: {document['status']}",
    )
    for item in document["items"]:
        validate_extraction_item(item)


def build_source(args, cfg, s3, run_id: str, doc: Path):
    """Return (source, httpd) in the SDK's friendly input form."""
    if args.source == "file":
        return doc, None
    if args.source == "s3":
        key_prefix = f"{cfg.source_prefix.strip('/')}/extract-src-{run_id}/"
        for doc in args.s3_doc or [doc]:
            s3.put_object(
                Bucket=cfg.source_bucket,
                Key=f"{key_prefix}{doc.name}",
                Body=doc.read_bytes(),
            )
        return (
            S3SourceRequest(
                endpoint=args.s3_endpoint,
                verify_ssl=False,
                access_key=cfg.minio_access_key,
                secret_key=cfg.minio_secret_key,
                bucket=cfg.source_bucket,
                key_prefix=key_prefix,
            ),
            None,
        )
    if args.source == "http":
        httpd, port = start_http_server(doc.parent)
        return f"http://127.0.0.1:{port}/{doc.name}", httpd
    raise ValueError(f"Unknown source kind: {args.source}")


def run_inbody(
    client,
    source_kind: str,
    source,
    extraction_target,
    options,
    expected_scopes: list[dict],
    expect_no_channel: bool,
    schema_fail: bool,
) -> None:
    # file -> extract(); http/s3 -> extract_all() so both SDK entry points get a
    # success path. S3 (expandable) in-body is rejected server-side with a 422,
    # which extract_all() surfaces as a FAILURE document rather than raising.
    if source_kind == "file":
        documents = [
            client.extract(
                source,
                target=extraction_target,
                options=options,
                raises_on_error=False,
            )
        ]
    else:
        documents = list(
            client.extract_all([source], target=extraction_target, options=options)
        )
    require(len(documents) == 1, f"Expected one document, got {len(documents)}.")
    document = documents[0]
    print("extract result:")
    print_json(document.model_dump(mode="json"))
    if source_kind == "s3":
        require(
            document.status.value == "failure"
            and "status=422" in document.errors[0].error_message,
            "S3 source -> inbody target must be rejected with 422.",
        )
        return
    check_document(
        document.model_dump(mode="json"),
        expected_scopes,
        expect_no_channel,
        schema_fail,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=sorted(MODEL_CONFIGS))
    parser.add_argument("--source", required=True, choices=["file", "s3", "http"])
    parser.add_argument(
        "--target", required=True, choices=["inbody", "presigned", "s3"]
    )
    parser.add_argument("--engine-model", default=None)
    parser.add_argument("--engine-url", default=None)
    parser.add_argument("--s3-endpoint", default="127.0.0.1:9000")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument(
        "--s3-doc",
        type=Path,
        action="append",
        help="Document to upload under the S3 source prefix (repeatable; default: the --doc-format document).",
    )
    parser.add_argument(
        "--doc-format",
        choices=["pdf", *UNPAGINATED_FORMATS],
        default="pdf",
        help="pdf uses SMOKE_PDF_A; the others generate a source without pages.",
    )
    parser.add_argument(
        "--page-range",
        default="1-1",
        help="START-END pages for a PDF; one page-scoped item per page, in order.",
    )
    parser.add_argument(
        "--schema-fail",
        action="store_true",
        help="Use a prompt_only schema the answer cannot satisfy; expect failed validation.",
    )
    parser.add_argument(
        "--callback-url",
        action="store_true",
        help="Register a local callback receiver and check the progress callback counts and artifact availability.",
    )
    args = parser.parse_args()
    page_start, page_end = (int(p) for p in args.page_range.split("-"))

    model_cfg = MODEL_CONFIGS[args.model]
    engine_model = args.engine_model or model_cfg["default_model"]
    engine_url = args.engine_url or model_cfg["default_url"]

    cfg = load_config()
    require(cfg.pdf_a.exists(), f"Missing test PDF: {cfg.pdf_a}")
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{args.s3_endpoint}",
        aws_access_key_id=cfg.minio_access_key,
        aws_secret_access_key=cfg.minio_secret_key,
    )
    ensure_bucket(s3, cfg.source_bucket)
    ensure_bucket(s3, cfg.target_bucket)

    expected_docs = len(args.s3_doc or [None]) if args.source == "s3" else 1
    run_id = unique_run_id()
    httpd = None
    callback_httpd = None
    callback_events: list[dict] = []
    target_prefix = None
    prefix_ref: list[str] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="extract-smoke-"))
    paginated = args.doc_format == "pdf"
    doc = cfg.pdf_a if paginated else write_unpaginated_doc(args.doc_format, tmp_dir)
    try:
        source, httpd = build_source(args, cfg, s3, run_id, doc)

        extraction_target = ExtractionTarget(
            output_schema=FAIL_SCHEMA if args.schema_fail else SCHEMA,
            template=model_cfg["template"],
        )
        extraction_config = ExtractionVlmOptions.from_preset(
            model_cfg["preset_id"],
            engine_options=ApiVlmEngineOptions(
                engine_type=model_cfg["engine_type"],
                url=engine_url,
                params={"model": engine_model},
                timeout=args.timeout,
            ),
        )
        if paginated:
            options = ExtractDocumentsOptions(
                extraction_custom_config=extraction_config,
                input_channels="image",
                page_range=(page_start, page_end),
            )
            expected_scopes = [
                {"kind": "page", "page_no": n} for n in range(page_start, page_end + 1)
            ]
        else:
            # No pages: the default channel resolves to text, the default page
            # range is required, and the one item covers the whole document.
            options = ExtractDocumentsOptions(
                extraction_custom_config=extraction_config
            )
            expected_scopes = [{"kind": "document"}]
        expect_no_channel = (
            not paginated and not extraction_config.model_spec.accepts_text
        )
        expected_succeeded = (
            0 if expect_no_channel or args.schema_fail else expected_docs
        )
        callbacks = None
        if args.callback_url:
            callback_httpd, callback_url, callback_events = start_callback_receiver(
                s3, cfg.target_bucket, prefix_ref
            )
            callbacks = [CallbackSpec(url=callback_url)]

        client = DoclingServiceClient(
            url=cfg.service_url,
            api_key=cfg.api_key,
            status_watcher="polling",
            poll_server_wait=0.5,
            job_timeout=args.timeout,
        )
        with client:
            if args.target == "inbody":
                run_inbody(
                    client,
                    args.source,
                    source,
                    extraction_target,
                    options,
                    expected_scopes,
                    expect_no_channel,
                    args.schema_fail,
                )
                print(
                    f"PASS: model={args.model} doc={args.doc_format} "
                    f"source={args.source} target=inbody"
                )
                return

            if args.target == "presigned":
                storage_target = PresignedUrlTarget()
            else:
                target_prefix = f"{cfg.target_prefix.strip('/')}/extract-{run_id}/"
                prefix_ref.append(target_prefix)
                storage_target = S3Target(
                    endpoint=args.s3_endpoint,
                    verify_ssl=False,
                    access_key=cfg.minio_access_key,
                    secret_key=cfg.minio_secret_key,
                    bucket=cfg.target_bucket,
                    key_prefix=target_prefix,
                )

            expect_rejected = args.source == "s3" and args.target == "presigned"
            try:
                job = client.submit_extract(
                    source=source,
                    extraction_target=extraction_target,
                    options=options,
                    target=storage_target,
                    callbacks=callbacks,
                )
                result = job.result(timeout=args.timeout)
            except Exception as exc:
                if not expect_rejected:
                    raise
                require(
                    isinstance(exc, ServiceError) and exc.status_code == 422,
                    f"Expected admission rejection with HTTP 422, got {type(exc).__name__}: {exc}",
                )
                print(f"rejected as expected: {type(exc).__name__}: {exc}")
                print(f"PASS: model={args.model} source=s3 target=presigned (rejected)")
                return

        print("result payload:")
        print_json(result.model_dump(mode="json"))
        require(
            result.num_succeeded == expected_succeeded,
            f"Expected {expected_succeeded} successful extractions, got {result.num_succeeded}.",
        )

        if args.target == "s3":
            require(
                isinstance(result, PresignedUrlConvertDocumentResponse),
                f"Unexpected result type {type(result).__name__}",
            )
            json_keys = [
                item["Key"]
                for item in s3.list_objects_v2(
                    Bucket=cfg.target_bucket, Prefix=target_prefix
                ).get("Contents", [])
                if item["Key"].endswith(".extraction.json")
            ]
            require(
                len(json_keys) == expected_docs,
                f"Expected {expected_docs} extraction JSON artifacts, got {json_keys}.",
            )
            for key in json_keys:
                artifact = json.loads(
                    s3.get_object(Bucket=cfg.target_bucket, Key=key)["Body"].read()
                )
                check_document(
                    artifact, expected_scopes, expect_no_channel, args.schema_fail
                )
                print(key, "->", artifact["status"], artifact["items"][:1])
            print("extraction artifacts:")
            print_json(json_keys)
        else:
            require(
                isinstance(result, PresignedUrlConvertResponse),
                f"Unexpected result type {type(result).__name__}",
            )
            require(
                len(result.documents) == expected_docs,
                f"Expected {expected_docs} documents, got {len(result.documents)}.",
            )
            for document in result.documents:
                json_artifacts = [
                    a for a in document.artifacts or [] if a.artifact_type == "json"
                ]
                require(json_artifacts, f"Expected a JSON artifact for {document}.")
                presigned_response = httpx.get(
                    str(json_artifacts[0].uri), follow_redirects=True, timeout=120.0
                )
                presigned_response.raise_for_status()
                artifact = presigned_response.json()
                check_document(
                    artifact, expected_scopes, expect_no_channel, args.schema_fail
                )
                print(
                    document.filename, "->", artifact["status"], artifact["items"][:1]
                )

        if args.callback_url:
            check_callbacks(callback_events, expected_docs, args.target == "s3")

        # Checked last so an unexpected acceptance still shows what it produced.
        require(
            not expect_rejected,
            "S3 source -> presigned target must be rejected, but it was accepted.",
        )

        print(
            f"PASS: model={args.model} doc={args.doc_format} "
            f"source={args.source} target={args.target}"
        )
    finally:
        for server in (httpd, callback_httpd):
            if server is not None:
                server.shutdown()
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
