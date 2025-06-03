# Define the input options for the API
from typing import Annotated, Any, Optional

from pydantic import AnyUrl, BaseModel, Field, model_validator
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
        ocr_engines_enum,
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
            description="Options for running a local vision-language model in the picture description. The parameters refer to a model hosted on Hugging Face. This parameter is mutually exclusive with picture_description_api.",
            examples=[
                PictureDescriptionLocal(repo_id="ibm-granite/granite-vision-3.2-2b"),
                PictureDescriptionLocal(repo_id="HuggingFaceTB/SmolVLM-256M-Instruct"),
            ],
        ),
    ] = None

    picture_description_api: Annotated[
        Optional[PictureDescriptionApi],
        Field(
            description="API details for using a vision-language model in the picture description. This parameter is mutually exclusive with picture_description_local.",
            examples=[
                PictureDescriptionApi(
                    url="http://localhost:11434/v1/chat/completions",
                    params={"model": "granite3.2-vision:2b"},
                )
            ],
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
