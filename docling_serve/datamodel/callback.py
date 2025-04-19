import enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ProgressKind(str, enum.Enum):
    SET_NUM_DOCS = "set_num_docs"
    UPDATE_PROCESSED = "update_processed"


class BaseProgress(BaseModel):
    kind: ProgressKind


class ProgressSetNumDocs(BaseProgress):
    kind: Literal[ProgressKind.SET_NUM_DOCS] = ProgressKind.SET_NUM_DOCS

    num_docs: int


class SucceededDocsItem(BaseModel):
    source: str


class FailedDocsItem(BaseModel):
    source: str
    error: str


class ProgressUpdateProcessed(BaseProgress):
    kind: Literal[ProgressKind.UPDATE_PROCESSED] = ProgressKind.UPDATE_PROCESSED

    num_processed: int
    num_succeeded: int
    num_failed: int

    docs_succeeded: list[SucceededDocsItem]
    docs_failed: list[FailedDocsItem]


class ProgressCallbackRequest(BaseModel):
    task_id: str
    progress: Annotated[
        ProgressSetNumDocs | ProgressUpdateProcessed, Field(discriminator="kind")
    ]


class ProgressCallbackResponse(BaseModel):
    status: Literal["ack"] = "ack"
