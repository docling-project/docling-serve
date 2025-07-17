import enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource
from docling_jobkit.datamodel.task_targets import InBodyTarget, TaskTarget, ZipTarget

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions

## Sources


class FileSourceRequest(FileSource):
    kind: Literal["file"] = "file"


class HttpSourceRequest(HttpSource):
    kind: Literal["http"] = "http"


## Multipart targets
class TargetName(str, enum.Enum):
    INBODY = InBodyTarget().kind
    ZIP = ZipTarget().kind


## Aliases
SourceRequestItem = Annotated[
    FileSourceRequest | HttpSourceRequest, Field(discriminator="kind")
]


## Complete Source request
class ConvertDocumentsRequest(BaseModel):
    options: ConvertDocumentsRequestOptions = ConvertDocumentsRequestOptions()
    sources: list[SourceRequestItem]
    target: TaskTarget = InBodyTarget()
