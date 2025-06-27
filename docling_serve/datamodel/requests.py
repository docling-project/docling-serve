from typing import Union

from pydantic import BaseModel

from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions


class DocumentsConvertBase(BaseModel):
    options: ConvertDocumentsRequestOptions = ConvertDocumentsRequestOptions()


class ConvertDocumentHttpSourcesRequest(DocumentsConvertBase):
    http_sources: list[HttpSource]


class ConvertDocumentFileSourcesRequest(DocumentsConvertBase):
    file_sources: list[FileSource]


ConvertDocumentsRequest = Union[
    ConvertDocumentFileSourcesRequest, ConvertDocumentHttpSourcesRequest
]
