"""
Logging configuration module for docling-serve.

Provides JSON logging formatter and request context management for
propagating HTTP headers into log records.
"""

import contextvars
import json
import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable to store request-scoped log data
_log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "log_context", default={}
)


class ColoredLogFormatter(logging.Formatter):
    """Colored formatter for text log output."""

    COLOR_CODES = {
        logging.DEBUG: "\033[94m",  # Blue
        logging.INFO: "\033[92m",  # Green
        logging.WARNING: "\033[93m",  # Yellow
        logging.ERROR: "\033[91m",  # Red
        logging.CRITICAL: "\033[95m",  # Magenta
    }
    RESET_CODE = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLOR_CODES.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname}{self.RESET_CODE}"
        return super().format(record)


def get_log_context() -> dict[str, Any]:
    """Get the current log context."""
    return _log_context.get()


def set_log_context(context: dict[str, Any]) -> None:
    """Set the log context."""
    _log_context.set(context)


def clear_log_context() -> None:
    """Clear the log context."""
    _log_context.set({})


class JSONLogFormatter(logging.Formatter):
    """
    JSON log formatter that includes context data from request headers.

    Outputs structured JSON logs with timestamp, level, logger name, message,
    and any additional context fields from request headers.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        # Build base log entry
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add stack info if present
        if record.stack_info:
            log_entry["stack_info"] = self.formatStack(record.stack_info)

        # Add context data from request headers
        context = get_log_context()
        if context:
            log_entry.update(context)

        # Add any extra fields from the log record
        # (fields added via logger.info("msg", extra={"key": "value"}))
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "taskName",
            ]:
                log_entry[key] = value

        return json.dumps(log_entry, default=str)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Format timestamp in ISO 8601 format."""
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            # ISO 8601 format with milliseconds
            s = time.strftime("%Y-%m-%dT%H:%M:%S", ct)
            s = f"{s}.{int(record.msecs):03d}Z"
        return s


class LogContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract request headers and store them in log context.

    Headers matching the configured prefix are extracted and made available
    to all loggers during the request lifecycle.
    """

    def __init__(self, app, header_prefix: str = "X-Docling-Log-"):
        """
        Initialize the middleware.

        Args:
            app: The ASGI application
            header_prefix: Prefix for headers to extract (case-insensitive)
        """
        super().__init__(app)
        self.header_prefix = header_prefix.lower()

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request and extract headers into log context."""
        # Extract headers matching the prefix
        context: dict[str, Any] = {}

        for header_name, header_value in request.headers.items():
            if header_name.lower().startswith(self.header_prefix):
                # Remove prefix from header name for cleaner log field names
                # e.g., "X-Docling-Log-RequestID" -> "RequestID"
                field_name = header_name[len(self.header_prefix) :]
                context[field_name] = header_value

        # Set the context for this request. The contextvar lives only in
        # this task, so it dies with the task when the request finishes —
        # we deliberately do NOT clear it here, so that uvicorn.access logs
        # (which fire after the middleware stack returns) still see it.
        set_log_context(context)

        return await call_next(request)


def setup_logging(
    log_format: str = "text",
    log_level: str = "INFO",
    header_prefix: str = "X-Docling-Log-",
) -> None:
    """
    Configure logging for the application.

    Args:
        log_format: "text" or "json"
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        header_prefix: Prefix for request headers to include in logs
    """
    # Get the root logger
    root_logger = logging.getLogger()

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create new handler
    handler = logging.StreamHandler()

    # Set formatter based on format type
    formatter: logging.Formatter
    if log_format.lower() == "json":
        formatter = JSONLogFormatter()
    else:
        formatter = ColoredLogFormatter(
            "%(levelname)s:\t%(asctime)s - %(name)s - %(message)s",
            datefmt="%H:%M:%S",
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Configure uvicorn loggers to use the same formatter
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, log_level.upper()))
        logger.propagate = False
