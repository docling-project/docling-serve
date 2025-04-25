import base64
from io import BytesIO
from typing import Annotated, Any, Union

from pydantic import AnyHttpUrl, BaseModel, Field

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.convert import ConvertDocumentsOptions


class DocumentsConvertBase(BaseModel):
    options: ConvertDocumentsOptions = ConvertDocumentsOptions()


class HttpSource(BaseModel):
    url: Annotated[
        AnyHttpUrl,
        Field(
            description="HTTP url to process",
            examples=["https://arxiv.org/pdf/2206.01062"],
        ),
    ]
    headers: Annotated[
        dict[str, Any],
        Field(
            description="Additional headers used to fetch the urls, "
            "e.g. authorization, agent, etc"
        ),
    ] = {}


class FileSource(BaseModel):
    base64_string: Annotated[
        str,
        Field(
            description="Content of the file serialized in base64. "
            "For example it can be obtained via "
            "`base64 -w 0 /path/to/file/pdf-to-convert.pdf`."
        ),
    ]
    filename: Annotated[
        str,
        Field(description="Filename of the uploaded document", examples=["file.pdf"]),
    ]

    def to_document_stream(self) -> DocumentStream:
        buf = BytesIO(base64.b64decode(self.base64_string))
        return DocumentStream(stream=buf, name=self.filename)


class ConvertDocumentHttpSourcesRequest(DocumentsConvertBase):
    http_sources: list[HttpSource]


class ConvertDocumentFileSourcesRequest(DocumentsConvertBase):
    file_sources: list[FileSource]


ConvertDocumentsRequest = Union[
    ConvertDocumentFileSourcesRequest, ConvertDocumentHttpSourcesRequest
]
