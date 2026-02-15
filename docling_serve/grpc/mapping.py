from __future__ import annotations

import logging
from typing import Iterable, Optional, Set

from google.protobuf import json_format

from docling.datamodel.base_models import ConversionStatus, InputFormat, OutputFormat
from docling.datamodel.pipeline_options import PdfBackend, ProcessingPipeline, TableFormerMode
from docling.datamodel.vlm_model_specs import VlmModelType
from docling.datamodel.pipeline_options_vlm_model import (
    InferenceFramework,
    ResponseFormat,
    TransformersModelType,
)
from docling_core.types.doc import ImageRefMode
from docling_jobkit.datamodel.chunking import (
    HierarchicalChunkerOptions,
    HybridChunkerOptions,
)
from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource
from docling_jobkit.datamodel.s3_coords import S3Coordinates
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus, TaskType
from docling_jobkit.datamodel.task_targets import InBodyTarget, PutTarget, S3Target, ZipTarget

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions
from docling_serve.settings import docling_serve_settings
from docling.utils.profiling import ProfilingItem

from .docling_document_converter import docling_document_to_proto
from .gen.ai.docling.core.v1 import docling_document_pb2
from .gen.ai.docling.serve.v1 import docling_serve_pb2, docling_serve_types_pb2

_log = logging.getLogger(__name__)


# -------------------- Proto -> Python domain --------------------


def _enum_name(enum_cls, value: int) -> Optional[str]:
    if value == 0:
        return None
    try:
        return enum_cls.Name(value)
    except Exception:
        return None


def _map_input_format(value: int) -> Optional[InputFormat]:
    name = _enum_name(docling_serve_types_pb2.InputFormat, value)
    if not name:
        return None
    mapping = {
        "INPUT_FORMAT_ASCIIDOC": InputFormat.ASCIIDOC,
        "INPUT_FORMAT_AUDIO": InputFormat.AUDIO,
        "INPUT_FORMAT_CSV": InputFormat.CSV,
        "INPUT_FORMAT_DOCX": InputFormat.DOCX,
        "INPUT_FORMAT_HTML": InputFormat.HTML,
        "INPUT_FORMAT_IMAGE": InputFormat.IMAGE,
        "INPUT_FORMAT_JSON_DOCLING": InputFormat.JSON_DOCLING,
        "INPUT_FORMAT_MD": InputFormat.MD,
        "INPUT_FORMAT_METS_GBS": InputFormat.METS_GBS,
        "INPUT_FORMAT_PDF": InputFormat.PDF,
        "INPUT_FORMAT_PPTX": InputFormat.PPTX,
        "INPUT_FORMAT_XLSX": InputFormat.XLSX,
        "INPUT_FORMAT_XML_JATS": InputFormat.XML_JATS,
        "INPUT_FORMAT_XML_USPTO": InputFormat.XML_USPTO,
    }
    return mapping.get(name)


def _map_output_format(value: int) -> Optional[OutputFormat]:
    name = _enum_name(docling_serve_types_pb2.OutputFormat, value)
    if not name:
        return None
    mapping = {
        "OUTPUT_FORMAT_DOCTAGS": OutputFormat.DOCTAGS,
        "OUTPUT_FORMAT_HTML": OutputFormat.HTML,
        "OUTPUT_FORMAT_HTML_SPLIT_PAGE": OutputFormat.HTML_SPLIT_PAGE,
        "OUTPUT_FORMAT_JSON": OutputFormat.JSON,
        "OUTPUT_FORMAT_MD": OutputFormat.MARKDOWN,
        "OUTPUT_FORMAT_TEXT": OutputFormat.TEXT,
    }
    return mapping.get(name)


def _map_image_ref_mode(value: int) -> Optional[ImageRefMode]:
    name = _enum_name(docling_serve_types_pb2.ImageRefMode, value)
    if not name:
        return None
    mapping = {
        "IMAGE_REF_MODE_EMBEDDED": ImageRefMode.EMBEDDED,
        "IMAGE_REF_MODE_PLACEHOLDER": ImageRefMode.PLACEHOLDER,
        "IMAGE_REF_MODE_REFERENCED": ImageRefMode.REFERENCED,
    }
    return mapping.get(name)


def _map_ocr_engine(value: int) -> Optional[str]:
    name = _enum_name(docling_serve_types_pb2.OcrEngine, value)
    if not name:
        return None
    mapping = {
        "OCR_ENGINE_AUTO": "auto",
        "OCR_ENGINE_EASYOCR": "easyocr",
        "OCR_ENGINE_OCRMAC": "ocrmac",
        "OCR_ENGINE_RAPIDOCR": "rapidocr",
        "OCR_ENGINE_TESSEROCR": "tesseract",
        "OCR_ENGINE_TESSERACT": "tesseract_cli",
    }
    return mapping.get(name)


def _map_pdf_backend(value: int) -> Optional[PdfBackend]:
    name = _enum_name(docling_serve_types_pb2.PdfBackend, value)
    if not name:
        return None
    mapping = {
        "PDF_BACKEND_PYPDFIUM2": PdfBackend.PYPDFIUM2,
        "PDF_BACKEND_DLPARSE_V1": PdfBackend.DLPARSE_V1,
        "PDF_BACKEND_DLPARSE_V2": PdfBackend.DLPARSE_V2,
        "PDF_BACKEND_DLPARSE_V4": PdfBackend.DLPARSE_V4,
    }
    return mapping.get(name)


def _map_table_mode(value: int) -> Optional[TableFormerMode]:
    name = _enum_name(docling_serve_types_pb2.TableFormerMode, value)
    if not name:
        return None
    mapping = {
        "TABLE_FORMER_MODE_FAST": TableFormerMode.FAST,
        "TABLE_FORMER_MODE_ACCURATE": TableFormerMode.ACCURATE,
    }
    return mapping.get(name)


def _map_pipeline(value: int) -> Optional[ProcessingPipeline]:
    name = _enum_name(docling_serve_types_pb2.ProcessingPipeline, value)
    if not name:
        return None
    mapping = {
        "PROCESSING_PIPELINE_ASR": ProcessingPipeline.ASR,
        "PROCESSING_PIPELINE_STANDARD": ProcessingPipeline.STANDARD,
        "PROCESSING_PIPELINE_VLM": ProcessingPipeline.VLM,
    }
    return mapping.get(name)


def _map_vlm_model_type(value: int) -> Optional[VlmModelType]:
    name = _enum_name(docling_serve_types_pb2.VlmModelType, value)
    if not name:
        return None
    mapping = {
        "VLM_MODEL_TYPE_SMOLDOCLING": VlmModelType.SMOLDOCLING,
        "VLM_MODEL_TYPE_SMOLDOCLING_VLLM": VlmModelType.SMOLDOCLING_VLLM,
        "VLM_MODEL_TYPE_GRANITE_VISION": VlmModelType.GRANITE_VISION,
        "VLM_MODEL_TYPE_GRANITE_VISION_VLLM": VlmModelType.GRANITE_VISION_VLLM,
        "VLM_MODEL_TYPE_GRANITE_VISION_OLLAMA": VlmModelType.GRANITE_VISION_OLLAMA,
        "VLM_MODEL_TYPE_GOT_OCR_2": VlmModelType.GOT_OCR_2,
    }
    return mapping.get(name)


def _map_response_format(value: int) -> Optional[ResponseFormat]:
    name = _enum_name(docling_serve_types_pb2.ResponseFormat, value)
    if not name:
        return None
    mapping = {
        "RESPONSE_FORMAT_DOCTAGS": ResponseFormat.DOCTAGS,
        "RESPONSE_FORMAT_MARKDOWN": ResponseFormat.MARKDOWN,
        "RESPONSE_FORMAT_HTML": ResponseFormat.HTML,
        "RESPONSE_FORMAT_OTSL": ResponseFormat.OTSL,
        "RESPONSE_FORMAT_PLAINTEXT": ResponseFormat.PLAINTEXT,
    }
    return mapping.get(name)


def _map_inference_framework(value: int) -> Optional[InferenceFramework]:
    name = _enum_name(docling_serve_types_pb2.InferenceFramework, value)
    if not name:
        return None
    mapping = {
        "INFERENCE_FRAMEWORK_MLX": InferenceFramework.MLX,
        "INFERENCE_FRAMEWORK_TRANSFORMERS": InferenceFramework.TRANSFORMERS,
        "INFERENCE_FRAMEWORK_VLLM": InferenceFramework.VLLM,
    }
    return mapping.get(name)


def _map_transformers_model_type(value: int) -> Optional[TransformersModelType]:
    name = _enum_name(docling_serve_types_pb2.TransformersModelType, value)
    if not name:
        return None
    mapping = {
        "TRANSFORMERS_MODEL_TYPE_AUTOMODEL": TransformersModelType.AUTOMODEL,
        "TRANSFORMERS_MODEL_TYPE_AUTOMODEL_VISION2SEQ": TransformersModelType.AUTOMODEL_VISION2SEQ,
        "TRANSFORMERS_MODEL_TYPE_AUTOMODEL_CAUSALLM": TransformersModelType.AUTOMODEL_CAUSALLM,
        "TRANSFORMERS_MODEL_TYPE_AUTOMODEL_IMAGETEXTTOTEXT": TransformersModelType.AUTOMODEL_IMAGETEXTTOTEXT,
    }
    return mapping.get(name)


def _value_to_python(value) -> object:
    if value is None:
        return None
    return json_format.MessageToDict(value, preserving_proto_field_name=True)


def to_task_sources(proto_sources: Iterable[docling_serve_types_pb2.Source]):
    sources = []
    for source in proto_sources:
        kind = source.WhichOneof("source")
        if kind == "file":
            file_src = source.file
            sources.append(
                FileSource(
                    base64_string=file_src.base64_string,
                    filename=file_src.filename,
                )
            )
        elif kind == "http":
            http_src = source.http
            sources.append(
                HttpSource(
                    url=http_src.url,
                    headers=dict(http_src.headers),
                )
            )
        elif kind == "s3":
            s3_src = source.s3
            sources.append(
                S3Coordinates(
                    endpoint=s3_src.endpoint,
                    access_key=s3_src.access_key,
                    secret_key=s3_src.secret_key,
                    bucket=s3_src.bucket,
                    key_prefix=s3_src.key_prefix if s3_src.HasField("key_prefix") else "",
                    verify_ssl=s3_src.verify_ssl,
                )
            )
    return sources


def to_task_target(proto_target: Optional[docling_serve_types_pb2.Target]):
    if proto_target is None:
        return InBodyTarget()
    kind = proto_target.WhichOneof("target")
    if kind == "zip":
        return ZipTarget()
    if kind == "put":
        return PutTarget(url=proto_target.put.url)
    if kind == "s3":
        s3_tgt = proto_target.s3
        return S3Target(
            endpoint=s3_tgt.endpoint,
            access_key=s3_tgt.access_key,
            secret_key=s3_tgt.secret_key,
            bucket=s3_tgt.bucket,
            key_prefix=s3_tgt.key_prefix if s3_tgt.HasField("key_prefix") else "",
            verify_ssl=s3_tgt.verify_ssl,
        )
    return InBodyTarget()


def requested_output_formats(
    proto_options: Optional[docling_serve_types_pb2.ConvertDocumentOptions],
) -> Set[OutputFormat]:
    if not proto_options or not proto_options.to_formats:
        return {OutputFormat.MARKDOWN}
    values = [
        v
        for v in (_map_output_format(v) for v in proto_options.to_formats)
        if v is not None
    ]
    return set(values) if values else {OutputFormat.MARKDOWN}


def to_convert_options(
    proto_options: Optional[docling_serve_types_pb2.ConvertDocumentOptions],
) -> ConvertDocumentsRequestOptions:
    data: dict[str, object] = {}
    if not proto_options:
        return ConvertDocumentsRequestOptions()

    if proto_options.from_formats:
        values = [
            v
            for v in (_map_input_format(v) for v in proto_options.from_formats)
            if v is not None
        ]
        if values:
            data["from_formats"] = values

    if proto_options.to_formats:
        values = [
            v
            for v in (_map_output_format(v) for v in proto_options.to_formats)
            if v is not None
        ]
        if values:
            data["to_formats"] = values

    if proto_options.HasField("image_export_mode"):
        val = _map_image_ref_mode(proto_options.image_export_mode)
        if val is not None:
            data["image_export_mode"] = val

    if proto_options.HasField("do_ocr"):
        data["do_ocr"] = proto_options.do_ocr

    if proto_options.HasField("force_ocr"):
        data["force_ocr"] = proto_options.force_ocr

    if proto_options.HasField("ocr_engine"):
        val = _map_ocr_engine(proto_options.ocr_engine)
        if val is not None:
            data["ocr_engine"] = val

    if proto_options.ocr_lang:
        data["ocr_lang"] = list(proto_options.ocr_lang)

    if proto_options.HasField("pdf_backend"):
        val = _map_pdf_backend(proto_options.pdf_backend)
        if val is not None:
            data["pdf_backend"] = val

    if proto_options.HasField("table_mode"):
        val = _map_table_mode(proto_options.table_mode)
        if val is not None:
            data["table_mode"] = val

    if proto_options.HasField("table_cell_matching"):
        data["table_cell_matching"] = proto_options.table_cell_matching

    if proto_options.HasField("pipeline"):
        val = _map_pipeline(proto_options.pipeline)
        if val is not None:
            data["pipeline"] = val

    if proto_options.page_range:
        if len(proto_options.page_range) == 2:
            data["page_range"] = tuple(proto_options.page_range)

    if proto_options.HasField("document_timeout"):
        data["document_timeout"] = proto_options.document_timeout

    if proto_options.HasField("abort_on_error"):
        data["abort_on_error"] = proto_options.abort_on_error

    if proto_options.HasField("do_table_structure"):
        data["do_table_structure"] = proto_options.do_table_structure

    if proto_options.HasField("include_images"):
        data["include_images"] = proto_options.include_images

    if proto_options.HasField("images_scale"):
        data["images_scale"] = proto_options.images_scale

    if proto_options.HasField("md_page_break_placeholder"):
        data["md_page_break_placeholder"] = proto_options.md_page_break_placeholder

    if proto_options.HasField("do_code_enrichment"):
        data["do_code_enrichment"] = proto_options.do_code_enrichment

    if proto_options.HasField("do_formula_enrichment"):
        data["do_formula_enrichment"] = proto_options.do_formula_enrichment

    if proto_options.HasField("do_picture_classification"):
        data["do_picture_classification"] = proto_options.do_picture_classification

    if proto_options.HasField("do_picture_description"):
        data["do_picture_description"] = proto_options.do_picture_description

    if proto_options.HasField("picture_description_area_threshold"):
        data["picture_description_area_threshold"] = (
            proto_options.picture_description_area_threshold
        )

    if proto_options.HasField("picture_description_local"):
        local = proto_options.picture_description_local
        local_data = {"repo_id": local.repo_id}
        if local.HasField("prompt"):
            local_data["prompt"] = local.prompt
        if local.generation_config:
            local_data["generation_config"] = {
                k: _value_to_python(v) for k, v in local.generation_config.items()
            }
        data["picture_description_local"] = local_data

    if proto_options.HasField("picture_description_api"):
        api = proto_options.picture_description_api
        api_data = {"url": api.url}
        if api.headers:
            api_data["headers"] = dict(api.headers)
        if api.params:
            api_data["params"] = {k: _value_to_python(v) for k, v in api.params.items()}
        if api.HasField("timeout"):
            api_data["timeout"] = api.timeout
        if api.HasField("concurrency"):
            api_data["concurrency"] = api.concurrency
        if api.HasField("prompt"):
            api_data["prompt"] = api.prompt
        data["picture_description_api"] = api_data

    if proto_options.HasField("vlm_pipeline_model"):
        val = _map_vlm_model_type(proto_options.vlm_pipeline_model)
        if val is not None:
            data["vlm_pipeline_model"] = val

    if proto_options.HasField("vlm_pipeline_model_local"):
        if proto_options.vlm_pipeline_model_local:
            data["vlm_pipeline_model_local"] = {
                "repo_id": proto_options.vlm_pipeline_model_local,
                "inference_framework": InferenceFramework.TRANSFORMERS,
                "response_format": ResponseFormat.DOCTAGS,
                "transformers_model_type": TransformersModelType.AUTOMODEL,
            }

    if proto_options.HasField("vlm_pipeline_model_api"):
        if proto_options.vlm_pipeline_model_api:
            data["vlm_pipeline_model_api"] = {
                "url": proto_options.vlm_pipeline_model_api,
                "response_format": ResponseFormat.DOCTAGS,
            }

    return ConvertDocumentsRequestOptions.model_validate(data)


def to_hierarchical_chunk_options(
    proto_options: Optional[docling_serve_types_pb2.HierarchicalChunkerOptions],
) -> HierarchicalChunkerOptions:
    if not proto_options:
        return HierarchicalChunkerOptions()
    return HierarchicalChunkerOptions(
        use_markdown_tables=proto_options.use_markdown_tables,
        include_raw_text=proto_options.include_raw_text,
    )


def to_hybrid_chunk_options(
    proto_options: Optional[docling_serve_types_pb2.HybridChunkerOptions],
) -> HybridChunkerOptions:
    if not proto_options:
        return HybridChunkerOptions()
    data = {
        "use_markdown_tables": proto_options.use_markdown_tables,
        "include_raw_text": proto_options.include_raw_text,
    }
    if proto_options.HasField("max_tokens"):
        data["max_tokens"] = proto_options.max_tokens
    if proto_options.HasField("tokenizer"):
        data["tokenizer"] = proto_options.tokenizer
    if proto_options.HasField("merge_peers"):
        data["merge_peers"] = proto_options.merge_peers
    return HybridChunkerOptions(**data)


# -------------------- Python domain -> Proto --------------------


def _docling_document_to_proto(doc) -> docling_document_pb2.DoclingDocument:
    return docling_document_to_proto(doc)


def _error_item_to_proto(error) -> docling_serve_types_pb2.ErrorItem:
    component = error.component_type
    if hasattr(component, "value"):
        component = component.value
    return docling_serve_types_pb2.ErrorItem(
        component_type=str(component),
        error_message=error.error_message,
        module_name=error.module_name,
    )


def _timings_to_proto(timings: dict[str, ProfilingItem]) -> dict[str, float]:
    return {key: item.total() for key, item in timings.items()}


def _build_exports(
    doc,
    requested_formats: Optional[Set[OutputFormat]],
) -> Optional[docling_serve_types_pb2.DocumentExports]:
    def wants(fmt: OutputFormat) -> bool:
        return requested_formats is None or fmt in requested_formats

    exports = docling_serve_types_pb2.DocumentExports()
    has_any = False

    if wants(OutputFormat.JSON) and doc.json_content is not None:
        exports.json = doc.json_content.model_dump_json(exclude_none=True)
        has_any = True
    if wants(OutputFormat.MARKDOWN) and doc.md_content is not None:
        exports.md = doc.md_content
        has_any = True
    if wants(OutputFormat.HTML) and doc.html_content is not None:
        exports.html = doc.html_content
        has_any = True
    if wants(OutputFormat.TEXT) and doc.text_content is not None:
        exports.text = doc.text_content
        has_any = True
    if wants(OutputFormat.DOCTAGS) and doc.doctags_content is not None:
        exports.doctags = doc.doctags_content
        has_any = True

    return exports if has_any else None


def export_document_to_proto(
    doc, requested_formats: Optional[Set[OutputFormat]] = None
) -> docling_serve_types_pb2.ExportDocumentResponse:
    message = docling_serve_types_pb2.ExportDocumentResponse(filename=doc.filename)
    if doc.json_content is not None:
        message.doc.CopyFrom(_docling_document_to_proto(doc.json_content))
    exports = _build_exports(doc, requested_formats)
    if exports is not None:
        message.exports.CopyFrom(exports)
    return message


def document_response_to_proto(
    doc, requested_formats: Optional[Set[OutputFormat]] = None
) -> docling_serve_types_pb2.DocumentResponse:
    message = docling_serve_types_pb2.DocumentResponse(filename=doc.filename)
    if doc.json_content is not None:
        message.doc.CopyFrom(_docling_document_to_proto(doc.json_content))
    exports = _build_exports(doc, requested_formats)
    if exports is not None:
        message.exports.CopyFrom(exports)
    return message


def convert_result_to_proto(
    result, processing_time: float, requested_formats: Optional[Set[OutputFormat]] = None
) -> docling_serve_types_pb2.ConvertDocumentResponse:
    status = result.status
    if hasattr(status, "value"):
        status = status.value
    response = docling_serve_types_pb2.ConvertDocumentResponse(
        document=document_response_to_proto(result.content, requested_formats),
        errors=[_error_item_to_proto(err) for err in result.errors],
        processing_time=processing_time,
        status=str(status),
        timings=_timings_to_proto(result.timings),
    )
    return response


def chunk_result_to_proto(
    result, processing_time: float, requested_formats: Optional[Set[OutputFormat]] = None
) -> docling_serve_types_pb2.ChunkDocumentResponse:
    chunks = []
    for chunk in result.chunks:
        message = docling_serve_types_pb2.Chunk(
            filename=chunk.filename,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            headings=chunk.headings or [],
            captions=chunk.captions or [],
            doc_items=chunk.doc_items or [],
            page_numbers=chunk.page_numbers or [],
            metadata={k: str(v) for k, v in (chunk.metadata or {}).items()},
        )
        if chunk.raw_text is not None:
            message.raw_text = chunk.raw_text
        if chunk.num_tokens is not None:
            message.num_tokens = chunk.num_tokens
        chunks.append(message)

    documents = []
    for doc in result.documents:
        status = doc.status
        if hasattr(status, "value"):
            status = status.value
        documents.append(
            docling_serve_types_pb2.Document(
                kind=doc.kind,
                content=export_document_to_proto(doc.content, requested_formats),
                status=str(status),
                errors=[_error_item_to_proto(err) for err in doc.errors],
            )
        )

    return docling_serve_types_pb2.ChunkDocumentResponse(
        chunks=chunks,
        documents=documents,
        processing_time=processing_time,
    )


def task_status_to_proto(
    task: Task, position: Optional[int]
) -> docling_serve_types_pb2.TaskStatusPollResponse:
    task_meta = None
    if task.processing_meta is not None:
        meta = task.processing_meta
        if hasattr(meta, "model_dump"):
            meta = meta.model_dump()
        task_meta = docling_serve_types_pb2.TaskStatusMetadata(
            num_docs=meta.get("num_docs", 0),
            num_processed=meta.get("num_processed", 0),
            num_succeeded=meta.get("num_succeeded", 0),
            num_failed=meta.get("num_failed", 0),
        )
    task_type = task.task_type
    if hasattr(task_type, "value"):
        task_type = task_type.value
    response = docling_serve_types_pb2.TaskStatusPollResponse(
        task_id=task.task_id,
        task_type=str(task_type) if task_type is not None else "",
        task_status=_task_status_enum(task.task_status),
        task_meta=task_meta,
    )
    if position is not None:
        response.task_position = position
    return response


def _task_status_enum(status: TaskStatus | str) -> int:
    if isinstance(status, str):
        try:
            status = TaskStatus(status)
        except Exception:
            return docling_serve_types_pb2.TaskStatus.TASK_STATUS_UNSPECIFIED
    mapping = {
        TaskStatus.PENDING: docling_serve_types_pb2.TaskStatus.TASK_STATUS_PENDING,
        TaskStatus.STARTED: docling_serve_types_pb2.TaskStatus.TASK_STATUS_STARTED,
        TaskStatus.SUCCESS: docling_serve_types_pb2.TaskStatus.TASK_STATUS_SUCCESS,
        TaskStatus.FAILURE: docling_serve_types_pb2.TaskStatus.TASK_STATUS_FAILURE,
    }
    return mapping.get(status, docling_serve_types_pb2.TaskStatus.TASK_STATUS_UNSPECIFIED)


def clear_response_to_proto(status: str = "ok") -> docling_serve_types_pb2.ClearResponse:
    return docling_serve_types_pb2.ClearResponse(status=status)


def with_single_use_cleanup(orchestrator, task_id: str) -> None:
    if not docling_serve_settings.single_use_results:
        return

    import asyncio

    async def _remove_task_impl():
        await asyncio.sleep(docling_serve_settings.result_removal_delay)
        await orchestrator.delete_task(task_id=task_id)

    asyncio.create_task(_remove_task_impl())
