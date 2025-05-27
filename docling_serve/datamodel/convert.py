# Define the input options for the API
from typing import Annotated, Any, Optional

from fastapi import Form, HTTPException, status
from pydantic import AnyUrl, BaseModel, Field, ValidationError, model_validator
from typing_extensions import Self

from docling.datamodel.base_models import InputFormat, OutputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    PdfBackend,
    PdfPipeline,
    PictureDescriptionBaseOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.datamodel.settings import (
    DEFAULT_PAGE_RANGE,
    PageRange,
)
from docling.models.factories import get_ocr_factory
from docling_core.types.doc import ImageRefMode

from docling_serve.settings import docling_serve_settings

ocr_factory = get_ocr_factory(
    allow_external_plugins=docling_serve_settings.allow_external_plugins
)
ocr_engines_enum = ocr_factory.get_enum()


class PictureDescriptionLocal(BaseModel):
    repo_id: Annotated[
        str,
        Field(
            description="Repository id from the Hugging Face Hub.",
            examples=[
                "HuggingFaceTB/SmolVLM-256M-Instruct",
                "ibm-granite/granite-vision-3.2-2b",
            ],
        ),
    ]
    prompt: Annotated[
        str,
        Field(
            description="Prompt used when calling the vision-language model.",
            examples=[
                "Describe this image in a few sentences.",
                "This is a figure from a document. Provide a detailed description of it.",
            ],
        ),
    ] = "Describe this image in a few sentences."
    generation_config: Annotated[
        dict[str, Any],
        Field(
            description="Config from https://huggingface.co/docs/transformers/en/main_classes/text_generation#transformers.GenerationConfig",
            examples=[{"max_new_tokens": 200, "do_sample": False}],
        ),
    ] = {"max_new_tokens": 200, "do_sample": False}


class PictureDescriptionApi(BaseModel):
    url: Annotated[
        AnyUrl,
        Field(
            description="Endpoint which accepts openai-api compatible requests.",
            examples=[
                AnyUrl(
                    "http://localhost:8000/v1/chat/completions"
                ),  # example of a local vllm api
                AnyUrl(
                    "http://localhost:11434/v1/chat/completions"
                ),  # example of ollama
            ],
        ),
    ]
    headers: Annotated[
        dict[str, str],
        Field(
            description="Headers used for calling the API endpoint. For example, it could include authentication headers."
        ),
    ] = {}
    params: Annotated[
        dict[str, Any],
        Field(
            description="Model parameters.",
            examples=[
                {  # on vllm
                    "model": "HuggingFaceTB/SmolVLM-256M-Instruct",
                    "max_completion_tokens": 200,
                },
                {  # on vllm
                    "model": "ibm-granite/granite-vision-3.2-2b",
                    "max_completion_tokens": 200,
                },
                {  # on ollama
                    "model": "granite3.2-vision:2b"
                },
            ],
        ),
    ] = {}
    timeout: Annotated[float, Field(description="Timeout for the API request.")] = 20
    prompt: Annotated[
        str,
        Field(
            description="Prompt used when calling the vision-language model.",
            examples=[
                "Describe this image in a few sentences.",
                "This is a figures from a document. Provide a detailed description of it.",
            ],
        ),
    ] = "Describe this image in a few sentences."


class ConvertDocumentsOptions(BaseModel):
    from_formats: Annotated[
        list[InputFormat],
        Field(
            description=(
                "Input format(s) to convert from. String or list of strings. "
                f"Allowed values: {', '.join([v.value for v in InputFormat])}. "
                "Optional, defaults to all formats."
            ),
            examples=[[v.value for v in InputFormat]],
        ),
    ] = list(InputFormat)

    to_formats: Annotated[
        list[OutputFormat],
        Field(
            description=(
                "Output format(s) to convert to. String or list of strings. "
                f"Allowed values: {', '.join([v.value for v in OutputFormat])}. "
                "Optional, defaults to Markdown."
            ),
            examples=[[OutputFormat.MARKDOWN]],
        ),
    ] = [OutputFormat.MARKDOWN]

    image_export_mode: Annotated[
        ImageRefMode,
        Field(
            description=(
                "Image export mode for the document (in case of JSON,"
                " Markdown or HTML). "
                f"Allowed values: {', '.join([v.value for v in ImageRefMode])}. "
                "Optional, defaults to Embedded."
            ),
            examples=[ImageRefMode.EMBEDDED.value],
            # pattern="embedded|placeholder|referenced",
        ),
    ] = ImageRefMode.EMBEDDED

    do_ocr: Annotated[
        bool,
        Field(
            description=(
                "If enabled, the bitmap content will be processed using OCR. "
                "Boolean. Optional, defaults to true"
            ),
            # examples=[True],
        ),
    ] = True

    force_ocr: Annotated[
        bool,
        Field(
            description=(
                "If enabled, replace existing text with OCR-generated "
                "text over content. Boolean. Optional, defaults to false."
            ),
            # examples=[False],
        ),
    ] = False

    ocr_engine: Annotated[  # type: ignore
        ocr_engines_enum,  # type: ignore
        Field(
            description=(
                "The OCR engine to use. String. "
                f"Allowed values: {', '.join([v.value for v in ocr_engines_enum])}. "
                "Optional, defaults to easyocr."
            ),
            examples=[EasyOcrOptions.kind],
        ),
    ] = ocr_engines_enum(EasyOcrOptions.kind)  # type: ignore

    ocr_lang: Annotated[
        Optional[list[str]],
        Field(
            description=(
                "List of languages used by the OCR engine. "
                "Note that each OCR engine has "
                "different values for the language names. String or list of strings. "
                "Optional, defaults to empty."
            ),
            examples=[["fr", "de", "es", "en"]],
        ),
    ] = None

    pdf_backend: Annotated[
        PdfBackend,
        Field(
            description=(
                "The PDF backend to use. String. "
                f"Allowed values: {', '.join([v.value for v in PdfBackend])}. "
                f"Optional, defaults to {PdfBackend.DLPARSE_V4.value}."
            ),
            examples=[PdfBackend.DLPARSE_V4],
        ),
    ] = PdfBackend.DLPARSE_V4

    table_mode: Annotated[
        TableFormerMode,
        Field(
            description=(
                "Mode to use for table structure, String. "
                f"Allowed values: {', '.join([v.value for v in TableFormerMode])}. "
                "Optional, defaults to fast."
            ),
            examples=[TableStructureOptions().mode],
            # pattern="fast|accurate",
        ),
    ] = TableStructureOptions().mode

    pipeline: Annotated[
        PdfPipeline,
        Field(description="Choose the pipeline to process PDF or image files."),
    ] = PdfPipeline.STANDARD

    page_range: Annotated[
        PageRange,
        Field(
            description="Only convert a range of pages. The page number starts at 1.",
            examples=[(1, 4)],
        ),
    ] = DEFAULT_PAGE_RANGE

    document_timeout: Annotated[
        float,
        Field(
            description="The timeout for processing each document, in seconds.",
            gt=0,
            le=docling_serve_settings.max_document_timeout,
        ),
    ] = docling_serve_settings.max_document_timeout

    abort_on_error: Annotated[
        bool,
        Field(
            description=(
                "Abort on error if enabled. Boolean. Optional, defaults to false."
            ),
            # examples=[False],
        ),
    ] = False

    return_as_file: Annotated[
        bool,
        Field(
            description=(
                "Return the output as a zip file "
                "(will happen anyway if multiple files are generated). "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_table_structure: Annotated[
        bool,
        Field(
            description=(
                "If enabled, the table structure will be extracted. "
                "Boolean. Optional, defaults to true."
            ),
            examples=[True],
        ),
    ] = True

    include_images: Annotated[
        bool,
        Field(
            description=(
                "If enabled, images will be extracted from the document. "
                "Boolean. Optional, defaults to true."
            ),
            examples=[True],
        ),
    ] = True

    images_scale: Annotated[
        float,
        Field(
            description="Scale factor for images. Float. Optional, defaults to 2.0.",
            examples=[2.0],
        ),
    ] = 2.0

    md_page_break_placeholder: Annotated[
        str,
        Field(
            description="Add this placeholder betweek pages in the markdown output.",
            examples=["<!-- page-break -->", ""],
        ),
    ] = ""

    do_code_enrichment: Annotated[
        bool,
        Field(
            description=(
                "If enabled, perform OCR code enrichment. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_formula_enrichment: Annotated[
        bool,
        Field(
            description=(
                "If enabled, perform formula OCR, return LaTeX code. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_picture_classification: Annotated[
        bool,
        Field(
            description=(
                "If enabled, classify pictures in documents. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_picture_description: Annotated[
        bool,
        Field(
            description=(
                "If enabled, describe pictures in documents. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    picture_description_area_threshold: Annotated[
        float,
        Field(
            description="Minimum percentage of the area for a picture to be processed with the models.",
            examples=[PictureDescriptionBaseOptions().picture_area_threshold],
        ),
    ] = PictureDescriptionBaseOptions().picture_area_threshold

    picture_description_local: Annotated[
        Optional[PictureDescriptionLocal],
        Field(
            description="Options for running a local vision-language model in the picture description. The parameters refer to a model hosted on Hugging Face. This parameter is mutually exclusive with picture_description_api."
        ),
    ] = None

    picture_description_api: Annotated[
        Optional[PictureDescriptionApi],
        Field(
            description="API details for using a vision-language model in the picture description. This parameter is mutually exclusive with picture_description_local."
        ),
    ] = None

    @model_validator(mode="after")
    def picture_description_exclusivity(self) -> Self:
        # Validate picture description options
        if (
            self.picture_description_local is not None
            and self.picture_description_api is not None
        ):
            raise ValueError(
                "The parameters picture_description_local and picture_description_api are mutually exclusive, only one of them can be set."
            )

        return self

    @classmethod
    def as_form(
        cls,
        from_formats: list[InputFormat] = Form(
            default=list(InputFormat),
            description="Input format(s) to convert from.",
        ),
        to_formats: list[OutputFormat] = Form(
            default=[OutputFormat.MARKDOWN],
            description="Output format(s) to convert to.",
        ),
        image_export_mode: ImageRefMode = Form(
            default=ImageRefMode.EMBEDDED,
            description="Image export mode for the document.",
        ),
        do_ocr: bool = Form(
            default=True,
            description="If enabled, the bitmap content will be processed using OCR.",
        ),
        force_ocr: bool = Form(
            default=False,
            description="If enabled, replace existing text with OCR-generated text over content.",
        ),
        ocr_engine: ocr_engines_enum = Form(  # type: ignore
            default=ocr_engines_enum(EasyOcrOptions.kind),  # type: ignore[operator]
            description="The OCR engine to use.",
        ),
        ocr_lang: Optional[list[str]] = Form(
            default=None,
            description="List of languages used by the OCR engine.",
        ),
        pdf_backend: PdfBackend = Form(
            default=PdfBackend.DLPARSE_V4,
            description="The PDF backend to use.",
        ),
        table_mode: TableFormerMode = Form(
            default=TableStructureOptions().mode,
            description="Mode to use for table structure.",
        ),
        pipeline: PdfPipeline = Form(
            default=PdfPipeline.STANDARD,
            description="Choose the pipeline to process PDF or image files.",
        ),
        page_range: PageRange = Form(
            default=DEFAULT_PAGE_RANGE,
            description="Only convert a range of pages. The page number starts at 1.",
        ),
        document_timeout: float = Form(
            default=docling_serve_settings.max_document_timeout,
            description="The timeout for processing each document, in seconds.",
        ),
        abort_on_error: bool = Form(
            default=False,
            description="Abort on error if enabled.",
        ),
        return_as_file: bool = Form(
            default=False,
            description="Return the output as a zip file.",
        ),
        do_table_structure: bool = Form(
            default=True,
            description="If enabled, the table structure will be extracted.",
        ),
        include_images: bool = Form(
            default=True,
            description="If enabled, images will be extracted from the document.",
        ),
        images_scale: float = Form(
            default=2.0,
            description="Scale factor for images.",
        ),
        md_page_break_placeholder: str = Form(
            default="",
            description="Add this placeholder betweek pages in the markdown output.",
        ),
        do_code_enrichment: bool = Form(
            default=False,
            description="If enabled, perform OCR code enrichment.",
        ),
        do_formula_enrichment: bool = Form(
            default=False,
            description="If enabled, perform formula OCR, return LaTeX code.",
        ),
        do_picture_classification: bool = Form(
            default=False,
            description="If enabled, classify pictures in documents.",
        ),
        do_picture_description: bool = Form(
            default=False,
            description="If enabled, describe pictures in documents.",
        ),
        picture_description_area_threshold: float = Form(
            default=PictureDescriptionBaseOptions().picture_area_threshold,
            description="Minimum percentage of the area for a picture to be processed with the models.",
        ),
        picture_description_local: Optional[dict | str] = Form(
            default=None,
            description="Options for running a local vision-language model in the picture description.",
        ),
        picture_description_api: Optional[dict | str] = Form(
            default=None,
            description="API details for using a vision-language model in the picture description.",
        ),
    ) -> "ConvertDocumentsOptions":
        """Helper function to convert form data to the model."""
        try:
            # Handle empty form values for picutre description params
            if picture_description_api == "" or picture_description_api == {}:
                picture_description_api = None
            if picture_description_api:
                picture_description_api_obj = PictureDescriptionApi.model_validate(
                    picture_description_api
                )
            if picture_description_local == "" or picture_description_local == {}:
                picture_description_local = None
            if picture_description_local:
                picture_description_local_obj = PictureDescriptionLocal.model_validate(
                    picture_description_local
                )

            ocr_lang_value = None if not ocr_lang or ocr_lang == [""] else ocr_lang

            return cls(
                from_formats=from_formats,
                to_formats=to_formats,
                image_export_mode=image_export_mode,
                do_ocr=do_ocr,
                force_ocr=force_ocr,
                ocr_engine=ocr_engine,
                ocr_lang=ocr_lang_value,
                pdf_backend=pdf_backend,
                table_mode=table_mode,
                pipeline=pipeline,
                page_range=page_range,
                document_timeout=document_timeout,
                abort_on_error=abort_on_error,
                return_as_file=return_as_file,
                do_table_structure=do_table_structure,
                include_images=include_images,
                images_scale=images_scale,
                md_page_break_placeholder=md_page_break_placeholder,
                do_code_enrichment=do_code_enrichment,
                do_formula_enrichment=do_formula_enrichment,
                do_picture_classification=do_picture_classification,
                do_picture_description=do_picture_description,
                picture_description_area_threshold=picture_description_area_threshold,
                picture_description_local=picture_description_local_obj,
                picture_description_api=picture_description_api_obj,
            )
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors(),
            )
