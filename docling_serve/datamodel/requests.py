import enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError
from typing_extensions import Self

from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource
from docling_jobkit.datamodel.s3_coords import S3Coordinates
from docling_jobkit.datamodel.task_targets import (
    InBodyTarget,
    S3Target,
    TaskTarget,
    ZipTarget,
)

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions
from docling_serve.settings import AsyncEngine, docling_serve_settings

## Sources


class FileSourceRequest(FileSource):
    kind: Literal["file"] = "file"


class HttpSourceRequest(HttpSource):
    kind: Literal["http"] = "http"


class S3SourceRequest(S3Coordinates):
    kind: Literal["s3"] = "s3"


## Multipart targets
class TargetName(str, enum.Enum):
    INBODY = InBodyTarget().kind
    ZIP = ZipTarget().kind


## Aliases
SourceRequestItem = Annotated[
    FileSourceRequest | HttpSourceRequest | S3SourceRequest, Field(discriminator="kind")
]


## Complete Source request
class ConvertDocumentsRequest(BaseModel):
    options: ConvertDocumentsRequestOptions = ConvertDocumentsRequestOptions()
    sources: list[SourceRequestItem]
    target: TaskTarget = InBodyTarget()

    @model_validator(mode="after")
    def validate_s3_source_and_target(self) -> Self:
        for source in self.sources:
            if isinstance(source, S3SourceRequest):
                if docling_serve_settings.eng_kind != AsyncEngine.KFP:
                    raise PydanticCustomError(
                        "error source", 'source kind "s3" requires engine kind "KFP"'
                    )
                if self.target.kind != "s3":
                    raise PydanticCustomError(
                        "error source", 'source kind "s3" requires target kind "s3"'
                    )
        if isinstance(self.target, S3Target):
            for source in self.sources:
                if isinstance(source, S3SourceRequest):
                    return self
            raise PydanticCustomError(
                "error target", 'target kind "s3" requires source kind "s3"'
            )
        return self
