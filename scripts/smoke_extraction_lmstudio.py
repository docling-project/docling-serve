"""Run one extraction request through docling-serve and LM Studio.

A PDF ``--source`` extracts page 1 from its image. A source without pages
(DOCX/Markdown/HTML) runs once as text with a document scope, which needs a
model that accepts text (NuExtract3); Granite rejects it with a channel error.
"""

import argparse
from pathlib import Path

from docling.datamodel.extraction import ExtractionTarget, ExtractionTemplate
from docling.datamodel.extraction_options import ExtractionVlmOptions
from docling.datamodel.service.options import ExtractDocumentsOptions
from docling.datamodel.service.responses import ExtractDocumentResponse
from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions
from docling.models.inference_engines.vlm.base import VlmEngineType
from docling.service_client import DoclingServiceClient, StatusWatcherKind

SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("granite", "nuextract3"), default="granite")
    parser.add_argument("--lm-studio-model", required=True)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).parents[1] / "tests" / "2206.01062v1.pdf",
    )
    parser.add_argument("--serve-url", default="http://127.0.0.1:5001")
    parser.add_argument(
        "--lm-studio-url",
        default="http://127.0.0.1:1234/v1/chat/completions",
    )
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    if args.model == "granite":
        preset = "granite_vision_4_1"
        engine_type = VlmEngineType.API_LMSTUDIO
        template = ExtractionTemplate(
            format="example_json", value={"title": "Example paper title"}
        )
    else:
        preset = "nuextract_3"
        # NuExtract3 needs per-request chat_template_kwargs. The generic API
        # transport sends them; this smoke exposes whether LM Studio honors them.
        engine_type = VlmEngineType.API
        template = ExtractionTemplate(format="nuextract", value={"title": "string"})

    extraction_config = ExtractionVlmOptions.from_preset(
        preset,
        engine_options=ApiVlmEngineOptions(
            engine_type=engine_type,
            url=args.lm_studio_url,
            params={"model": args.lm_studio_model},
            timeout=args.timeout,
        ),
    )
    paginated = args.source.suffix.lower() == ".pdf"
    if paginated:
        options = ExtractDocumentsOptions(
            extraction_custom_config=extraction_config,
            input_channels="image",
            page_range=(1, 1),
        )
    else:
        # No pages: default channel (text) and default page range, one document item.
        options = ExtractDocumentsOptions(extraction_custom_config=extraction_config)
    client = DoclingServiceClient(
        args.serve_url,
        status_watcher=StatusWatcherKind.POLLING,
        job_timeout=args.timeout,
        http_read_timeout=args.timeout,
    )
    result = client.submit_extract(
        source=args.source,
        extraction_target=ExtractionTarget(output_schema=SCHEMA, template=template),
        options=options,
    ).result(timeout=args.timeout)
    if not isinstance(result, ExtractDocumentResponse):
        raise SystemExit("smoke failed: expected an in-body extraction result")
    print(result.model_dump_json(indent=2))
    if result.num_failed or not result.documents or not result.documents[0].items:
        raise SystemExit("smoke failed: extraction returned no items")
    item = result.documents[0].items[0]
    if item.extracted_data is None or item.validation_status != "passed":
        raise SystemExit("smoke failed: extraction did not produce schema-valid data")
    expected_kind = "page" if paginated else "document"
    if item.scope.kind != expected_kind:
        raise SystemExit(
            f"smoke failed: expected {expected_kind} scope, got {item.scope}"
        )


if __name__ == "__main__":
    main()
