# SPDX-License-Identifier: MIT

"""Serve-owned cancelled-capable wire schema.

The installed docling SDK rejects ``cancelled``: ``TaskStatusResponse.task_status``
is ``ConversionStatus`` (pending/started/failure/success/partial_success/skipped)
and ``WebsocketMessage.task`` nests that model. This module extends the wire
schema without touching the SDK by subclassing and overriding only the status
field as a union with ``Literal["cancelled"]``. All other fields, types, and
defaults are inherited unchanged so existing values serialize exactly as before.
"""

from typing import Literal

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.service.responses import (
    TaskStatusResponse as SdkTaskStatusResponse,
    WebsocketMessage as SdkWebsocketMessage,
)

__all__ = [
    "ServeTaskStatusResponse",
    "ServeWebsocketMessage",
    "to_serve_task_status",
]


class ServeTaskStatusResponse(SdkTaskStatusResponse):
    """SDK task response that also accepts terminal ``cancelled``."""

    # Intentional wire widening: the Serve API must accept the Jobkit terminal
    # ``cancelled`` value that the pinned SDK enum omits. Pydantic field
    # narrowing cannot express this wider union type-safely without duplicating
    # every inherited field, so this single assignment-level exception is scoped
    # to this line only.
    task_status: ConversionStatus | Literal["cancelled"]  # type: ignore[assignment]


class ServeWebsocketMessage(SdkWebsocketMessage):
    """SDK WS envelope carrying the cancelled-capable response."""

    task: ServeTaskStatusResponse | None = None


def to_serve_task_status(
    status: ConversionStatus | str,
) -> ConversionStatus | Literal["cancelled"]:
    """Map a task status to the Serve wire value.

    Passes every existing SDK status through untouched and maps the Jobkit
    ``cancelled`` value (string or enum) to the literal ``"cancelled"``. The
    Serve response model already coerces Jobkit enums directly, so this helper
    is documentation-grade explicitness for callers rather than a requirement.
    """
    if str(getattr(status, "value", status)) == "cancelled":
        return "cancelled"
    if isinstance(status, ConversionStatus):
        return status
    return ConversionStatus(str(getattr(status, "value", status)))
