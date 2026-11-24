"""Smoke Granite Vision 4.1 extraction from an inline file to local MinIO."""

from __future__ import annotations

import argparse
import base64
import json

import boto3
from botocore.exceptions import ClientError

from docling.datamodel.extraction import ExtractionTarget, ExtractionTemplate
from docling.datamodel.extraction_options import ExtractionVlmOptions
from docling.datamodel.service.options import ExtractDocumentsOptions
from docling.datamodel.service.requests import ExtractSourcesRequest, FileSourceRequest
from docling.datamodel.service.responses import (
    PresignedUrlConvertDocumentResponse,
    TaskStatusResponse,
)
from docling.datamodel.service.targets import S3Target
from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions
from docling.models.inference_engines.vlm.base import VlmEngineType

from scripts.local_smoke._common import (
    fetch_result_json,
    http_client,
    load_config,
    model_validate_response,
    print_json,
    require,
    unique_run_id,
    validate_extraction_item,
    wait_for_task,
)

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}


def ensure_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lm-studio-model", required=True)
    parser.add_argument(
        "--lm-studio-url", default="http://127.0.0.1:1234/v1/chat/completions"
    )
    parser.add_argument("--s3-endpoint", default="127.0.0.1:9000")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    cfg = load_config()
    require(cfg.pdf_a.exists(), f"Missing test PDF: {cfg.pdf_a}")
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{args.s3_endpoint}",
        aws_access_key_id=cfg.minio_access_key,
        aws_secret_access_key=cfg.minio_secret_key,
    )
    ensure_bucket(s3, cfg.target_bucket)

    run_id = unique_run_id()
    target_prefix = f"{cfg.target_prefix.strip('/')}/extract-{run_id}/"

    extraction_config = ExtractionVlmOptions.from_preset(
        "granite_vision_4_1",
        engine_options=ApiVlmEngineOptions(
            engine_type=VlmEngineType.API_LMSTUDIO,
            url=args.lm_studio_url,
            params={"model": args.lm_studio_model},
            timeout=args.timeout,
        ),
    )
    request = ExtractSourcesRequest(
        extraction_target=ExtractionTarget(
            output_schema=SCHEMA,
            template=ExtractionTemplate(
                format="example_json", value={"title": "Example paper title"}
            ),
        ),
        options=ExtractDocumentsOptions(
            extraction_custom_config=extraction_config,
            input_channels="image",
            page_range=(1, 1),
        ),
        sources=[
            FileSourceRequest(
                filename=cfg.pdf_a.name,
                base64_string=base64.b64encode(cfg.pdf_a.read_bytes()).decode(),
            )
        ],
        target=S3Target(
            endpoint=args.s3_endpoint,
            verify_ssl=False,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            bucket=cfg.target_bucket,
            key_prefix=target_prefix,
        ),
    )

    with http_client(cfg) as client:
        response = client.post(
            "/v1/extract/source/async", json=request.model_dump(mode="json")
        )
        response.raise_for_status()
        submitted = model_validate_response(TaskStatusResponse, response.json())
        print("submit payload:")
        print_json(submitted.model_dump(mode="json"))

        terminal = wait_for_task(client, submitted.task_id, timeout=args.timeout)
        require(
            terminal["task_status"] == "success",
            f"Extraction task finished with {terminal['task_status']}: {terminal}",
        )
        result = model_validate_response(
            PresignedUrlConvertDocumentResponse,
            fetch_result_json(client, submitted.task_id),
        )
        print("result payload:")
        print_json(result.model_dump(mode="json"))

    require(result.num_succeeded == 1, "Expected one successful extraction.")
    json_keys = [
        item["Key"]
        for item in s3.list_objects_v2(
            Bucket=cfg.target_bucket, Prefix=target_prefix
        ).get("Contents", [])
        if item["Key"].endswith(".extraction.json")
    ]
    require(json_keys, "No extraction JSON artifact found in MinIO.")
    artifact = json.loads(
        s3.get_object(Bucket=cfg.target_bucket, Key=json_keys[0])["Body"].read()
    )
    validate_extraction_item(artifact["items"][0])
    print("extraction artifacts:")
    print_json(json_keys)


if __name__ == "__main__":
    main()
