import pytest

from docling.datamodel.base_models import InputFormat, OutputFormat
from docling.datamodel.pipeline_options import (
    PdfBackend,
    ProcessingPipeline,
    TableFormerMode,
)
from docling.datamodel.pipeline_options_vlm_model import (
    InferenceFramework,
    ResponseFormat,
    TransformersModelType,
)
from docling.datamodel.vlm_model_specs import VlmModelType
from docling_core.types.doc import ImageRefMode
from docling_jobkit.datamodel.chunking import HybridChunkerOptions
from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource
from docling_jobkit.datamodel.s3_coords import S3Coordinates
from docling_jobkit.datamodel.task_targets import (
    InBodyTarget,
    PutTarget,
    S3Target,
    ZipTarget,
)

from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2
from docling_serve.grpc.mapping import (
    _map_image_ref_mode,
    _map_inference_framework,
    _map_input_format,
    _map_ocr_engine,
    _map_output_format,
    _map_pdf_backend,
    _map_pipeline,
    _map_response_format,
    _map_table_mode,
    _map_transformers_model_type,
    _map_vlm_model_type,
    _task_status_enum,
    requested_output_formats,
    to_convert_options,
    to_hybrid_chunk_options,
    to_task_sources,
    to_task_target,
)

pytestmark = pytest.mark.unit


def test_enum_mappings():
    assert (
        _map_input_format(docling_serve_types_pb2.INPUT_FORMAT_PDF) == InputFormat.PDF
    )
    assert (
        _map_output_format(docling_serve_types_pb2.OUTPUT_FORMAT_MD)
        == OutputFormat.MARKDOWN
    )
    assert (
        _map_image_ref_mode(docling_serve_types_pb2.IMAGE_REF_MODE_REFERENCED)
        == ImageRefMode.REFERENCED
    )
    assert _map_ocr_engine(docling_serve_types_pb2.OCR_ENGINE_TESSEROCR) == "tesseract"
    assert (
        _map_ocr_engine(docling_serve_types_pb2.OCR_ENGINE_TESSERACT) == "tesseract_cli"
    )
    assert (
        _map_pdf_backend(docling_serve_types_pb2.PDF_BACKEND_DLPARSE_V4)
        == PdfBackend.DLPARSE_V4
    )
    assert (
        _map_table_mode(docling_serve_types_pb2.TABLE_FORMER_MODE_FAST)
        == TableFormerMode.FAST
    )
    assert (
        _map_pipeline(docling_serve_types_pb2.PROCESSING_PIPELINE_VLM)
        == ProcessingPipeline.VLM
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_GOT_OCR_2)
        == VlmModelType.GOT_OCR_2
    )
    assert (
        _map_response_format(docling_serve_types_pb2.RESPONSE_FORMAT_PLAINTEXT)
        == ResponseFormat.PLAINTEXT
    )
    assert (
        _map_inference_framework(
            docling_serve_types_pb2.INFERENCE_FRAMEWORK_TRANSFORMERS
        )
        == InferenceFramework.TRANSFORMERS
    )
    assert (
        _map_transformers_model_type(
            docling_serve_types_pb2.TRANSFORMERS_MODEL_TYPE_AUTOMODEL_IMAGETEXTTOTEXT
        )
        == TransformersModelType.AUTOMODEL_IMAGETEXTTOTEXT
    )

    assert _map_input_format(0) is None
    assert _map_output_format(0) is None


def test_to_task_sources_and_target():
    sources = to_task_sources(
        [
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string="aGVsbG8=",
                    filename="test.pdf",
                )
            ),
            docling_serve_types_pb2.Source(
                http=docling_serve_types_pb2.HttpSource(
                    url="https://example.com/doc.pdf"
                )
            ),
            docling_serve_types_pb2.Source(
                s3=docling_serve_types_pb2.S3Source(
                    endpoint="s3.example.com",
                    access_key="a",
                    secret_key="b",
                    bucket="bucket",
                    key_prefix="prefix",
                    verify_ssl=True,
                )
            ),
        ]
    )

    assert isinstance(sources[0], FileSource)
    assert isinstance(sources[1], HttpSource)
    assert isinstance(sources[2], S3Coordinates)

    assert isinstance(to_task_target(None), InBodyTarget)
    assert isinstance(
        to_task_target(
            docling_serve_types_pb2.Target(zip=docling_serve_types_pb2.ZipTarget())
        ),
        ZipTarget,
    )
    assert isinstance(
        to_task_target(
            docling_serve_types_pb2.Target(
                put=docling_serve_types_pb2.PutTarget(url="https://example.com")
            )
        ),
        PutTarget,
    )
    assert isinstance(
        to_task_target(
            docling_serve_types_pb2.Target(
                s3=docling_serve_types_pb2.S3Target(
                    endpoint="s3.example.com",
                    access_key="a",
                    secret_key="b",
                    bucket="bucket",
                    verify_ssl=True,
                )
            )
        ),
        S3Target,
    )


def test_to_task_sources_empty_oneof_raises():
    """A Source with no variant set raises ValueError."""
    with pytest.raises(ValueError, match="no variant set"):
        to_task_sources([docling_serve_types_pb2.Source()])


def test_to_task_sources_mixed_with_empty_oneof_raises():
    """If any Source in the list has no variant, ValueError is raised."""
    with pytest.raises(ValueError, match="index 1"):
        to_task_sources(
            [
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string="aGVsbG8=", filename="a.pdf"
                    )
                ),
                docling_serve_types_pb2.Source(),  # no variant
            ]
        )


def test_to_convert_options_full():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        from_formats=[docling_serve_types_pb2.INPUT_FORMAT_PDF],
        to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_TEXT],
        image_export_mode=docling_serve_types_pb2.IMAGE_REF_MODE_EMBEDDED,
        do_ocr=True,
        force_ocr=False,
        ocr_engine=docling_serve_types_pb2.OCR_ENGINE_EASYOCR,
        ocr_lang=["en"],
        pdf_backend=docling_serve_types_pb2.PDF_BACKEND_PYPDFIUM2,
        table_mode=docling_serve_types_pb2.TABLE_FORMER_MODE_ACCURATE,
        table_cell_matching=True,
        pipeline=docling_serve_types_pb2.PROCESSING_PIPELINE_STANDARD,
        page_range=[1, 2],
        document_timeout=12.0,
        abort_on_error=True,
        do_table_structure=True,
        include_images=True,
        images_scale=0.75,
        md_page_break_placeholder="---",
        do_code_enrichment=True,
        do_formula_enrichment=True,
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_area_threshold=0.2,
        picture_description_local=docling_serve_types_pb2.PictureDescriptionLocal(
            repo_id="repo",
            prompt="describe",
        ),
        vlm_pipeline_model_local="local-model",
    )

    mapped = to_convert_options(options)
    assert mapped.from_formats == [InputFormat.PDF]
    assert mapped.to_formats == [OutputFormat.TEXT]
    assert mapped.image_export_mode == ImageRefMode.EMBEDDED
    assert mapped.do_ocr is True
    assert mapped.force_ocr is False
    assert mapped.ocr_engine == "easyocr"
    assert mapped.ocr_lang == ["en"]
    assert mapped.pdf_backend == PdfBackend.PYPDFIUM2
    assert mapped.table_mode == TableFormerMode.ACCURATE
    assert mapped.table_cell_matching is True
    assert mapped.pipeline == ProcessingPipeline.STANDARD
    assert mapped.page_range == (1, 2)
    assert mapped.document_timeout == 12.0
    assert mapped.abort_on_error is True
    assert mapped.do_table_structure is True
    assert mapped.include_images is True
    assert mapped.images_scale == 0.75
    assert mapped.md_page_break_placeholder == "---"
    assert mapped.do_code_enrichment is True
    assert mapped.do_formula_enrichment is True
    assert mapped.do_picture_classification is True
    assert mapped.do_picture_description is True
    assert mapped.picture_description_area_threshold == 0.2
    data = mapped.model_dump(exclude_none=True)
    assert data["picture_description_local"]["repo_id"] == "repo"
    assert data["picture_description_local"]["prompt"] == "describe"
    assert data["vlm_pipeline_model_local"]["repo_id"] == "local-model"
    assert data["vlm_pipeline_model_local"]["response_format"] == ResponseFormat.DOCTAGS


def test_to_convert_options_picture_description_api():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        picture_description_api=docling_serve_types_pb2.PictureDescriptionApi(
            url="https://api.example.com",
            timeout=3.0,
            concurrency=2,
            prompt="describe",
        )
    )

    mapped = to_convert_options(options)
    data = mapped.model_dump(exclude_none=True)
    assert str(data["picture_description_api"]["url"]) == "https://api.example.com/"
    assert data["picture_description_api"]["timeout"] == 3.0
    assert data["picture_description_api"]["concurrency"] == 2
    assert data["picture_description_api"]["prompt"] == "describe"


def test_requested_output_formats_default_and_custom():
    assert requested_output_formats(None) == set()
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        to_formats=[
            docling_serve_types_pb2.OUTPUT_FORMAT_TEXT,
            docling_serve_types_pb2.OUTPUT_FORMAT_MD,
        ]
    )
    assert requested_output_formats(options) == {
        OutputFormat.TEXT,
        OutputFormat.MARKDOWN,
    }


def test_to_hybrid_chunk_options():
    options = docling_serve_types_pb2.HybridChunkerOptions(
        use_markdown_tables=True,
        include_raw_text=False,
        max_tokens=256,
        tokenizer="tok",
        merge_peers=True,
    )

    mapped = to_hybrid_chunk_options(options)
    assert isinstance(mapped, HybridChunkerOptions)
    assert mapped.use_markdown_tables is True
    assert mapped.include_raw_text is False
    assert mapped.max_tokens == 256
    assert mapped.tokenizer == "tok"
    assert mapped.merge_peers is True


def test_task_status_enum():
    assert (
        _task_status_enum("success")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_SUCCESS
    )
    assert (
        _task_status_enum("unknown")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_UNSPECIFIED
    )


def test_enum_mappings_unspecified_returns_none():
    """UNSPECIFIED (0) must map to None for every enum mapper."""
    assert _map_input_format(0) is None
    assert _map_output_format(0) is None
    assert _map_image_ref_mode(0) is None
    assert _map_ocr_engine(0) is None
    assert _map_pdf_backend(0) is None
    assert _map_table_mode(0) is None
    assert _map_pipeline(0) is None
    assert _map_vlm_model_type(0) is None
    assert _map_response_format(0) is None
    assert _map_inference_framework(0) is None
    assert _map_transformers_model_type(0) is None


def test_enum_mappings_bogus_values_return_none():
    """Out-of-range / future enum values must map to None, not crash."""
    bogus = 9999
    assert _map_input_format(bogus) is None
    assert _map_output_format(bogus) is None
    assert _map_image_ref_mode(bogus) is None
    assert _map_ocr_engine(bogus) is None
    assert _map_pdf_backend(bogus) is None
    assert _map_table_mode(bogus) is None
    assert _map_pipeline(bogus) is None
    assert _map_vlm_model_type(bogus) is None
    assert _map_response_format(bogus) is None
    assert _map_inference_framework(bogus) is None
    assert _map_transformers_model_type(bogus) is None


def test_task_status_enum_all_values():
    """Every known TaskStatus string maps to the correct proto enum."""
    assert (
        _task_status_enum("pending")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_PENDING
    )
    assert (
        _task_status_enum("started")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_STARTED
    )
    assert (
        _task_status_enum("failure")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_FAILURE
    )
