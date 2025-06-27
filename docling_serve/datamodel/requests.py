from typing import Annotated, Literal

from pydantic import BaseModel, Field

from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions

## Sources


class FileSourceRequest(FileSource):
    kind: Literal["file"] = "file"


class HttpSourceRequest(HttpSource):
    kind: Literal["http"] = "http"


## Targets


class InBodyTargetRequest(BaseModel):
    kind: Literal["inbody"] = "inbody"


class ZipTargetRequest(BaseModel):
    kind: Literal["zip"] = "zip"


## Aliases
SourceRequestItem = Annotated[
    FileSourceRequest | HttpSourceRequest, Field(discriminator="kind")
]
TargetRequest = Annotated[
    InBodyTargetRequest | ZipTargetRequest, Field(discriminator="kind")
]


## Complete request
class ConvertDocumentsRequest(BaseModel):
    options: ConvertDocumentsRequestOptions = ConvertDocumentsRequestOptions()
    sources: list[SourceRequestItem]
    target: TargetRequest = InBodyTargetRequest()
