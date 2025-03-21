
import enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ProgressKind(str, enum.Enum):
    SET_NUM_DOCS = "set_num_docs"
    UPDATE_PROCESSED = "update_processed"


class BaseProgress(BaseModel):
    kind: ProgressKind


class ProgressSetNumDocs(BaseProgress):
    kind: Literal[ProgressKind.SET_NUM_DOCS]

    num_docs: int


class ProgressUpdateProcessed(BaseProgress):
    kind: Literal[ProgressKind.UPDATE_PROCESSED]

    num_processed: int
    num_success: int
    num_failed: int


# ProgressCallbackRequest = TypeAdapter(Annotated[ProgressSetNumDocs | ProgressUpdateProcessed, Field(discriminator="kind")])
ProgressCallbackRequest = Annotated[ProgressSetNumDocs | ProgressUpdateProcessed, Field(discriminator="kind")]

class ProgressCallbackResponse(BaseModel):
    status: Literal["ack"] = "ack"
