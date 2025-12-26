"""Logging utilities for FDB Record Layer.

Provides structured logging with context propagation and
configurable log levels for production debugging.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar, cast

# Package logger hierarchy
LOGGER_NAME = "fdb_record_layer"

# Create package root logger
_root_logger = logging.getLogger(LOGGER_NAME)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a submodule.

    Args:
        name: The submodule name (e.g., "core.store").

    Returns:
        A logger with the full hierarchical name.

    Example:
        >>> logger = get_logger("core.store")
        >>> logger.info("Saving record", extra={"primary_key": pk})
    """
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


@dataclass
class LogContext:
    """Context for structured logging.

    Provides a way to attach contextual information to log messages
    that will be included as extra fields.

    Example:
        >>> ctx = LogContext(database="mydb", operation="query")
        >>> ctx.log(logger, "info", "Starting query")
    """

    fields: dict[str, Any] = field(default_factory=dict)

    def with_field(self, key: str, value: Any) -> LogContext:
        """Create a new context with an additional field."""
        new_fields = self.fields.copy()
        new_fields[key] = value
        return LogContext(fields=new_fields)

    def with_fields(self, **kwargs: Any) -> LogContext:
        """Create a new context with additional fields."""
        new_fields = self.fields.copy()
        new_fields.update(kwargs)
        return LogContext(fields=new_fields)

    def log(
        self,
        logger: logging.Logger,
        level: str,
        message: str,
        **extra: Any,
    ) -> None:
        """Log a message with context fields."""
        all_extra = {**self.fields, **extra}
        log_method = getattr(logger, level)
        log_method(message, extra=all_extra)


class StructuredFormatter(logging.Formatter):
    """Formatter that includes structured fields in log output.

    Formats log records with extra fields in a key=value format
    suitable for log aggregation systems.
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        include_extra: bool = True,
    ) -> None:
        """Initialize the formatter.

        Args:
            fmt: Log format string.
            datefmt: Date format string.
            include_extra: Whether to include extra fields.
        """
        if fmt is None:
            fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        super().__init__(fmt, datefmt)
        self._include_extra = include_extra
        # Standard LogRecord attributes to exclude from extra
        self._standard_attrs = {
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
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "message",
            "asctime",
            "taskName",
        }

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with extra fields."""
        message = super().format(record)

        if self._include_extra:
            extra_fields = {
                k: v for k, v in record.__dict__.items() if k not in self._standard_attrs
            }
            if extra_fields:
                extra_str = " ".join(f"{k}={v}" for k, v in extra_fields.items())
                message = f"{message} | {extra_str}"

        return message


def configure_logging(
    level: int = logging.INFO,
    handler: logging.Handler | None = None,
    structured: bool = True,
) -> None:
    """Configure logging for the FDB Record Layer package.

    Args:
        level: Log level (default INFO).
        handler: Custom log handler (default stdout).
        structured: Use structured log format.

    Example:
        >>> import logging
        >>> configure_logging(level=logging.DEBUG)
    """
    if handler is None:
        handler = logging.StreamHandler()

    formatter: logging.Formatter
    if structured:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    handler.setFormatter(formatter)
    _root_logger.addHandler(handler)
    _root_logger.setLevel(level)


F = TypeVar("F", bound=Callable[..., Any])


def log_operation(
    logger: logging.Logger,
    operation: str,
    log_args: bool = False,
    log_result: bool = False,
) -> Callable[[F], F]:
    """Decorator to log function entry/exit with timing.

    Args:
        logger: The logger to use.
        operation: Name of the operation for logging.
        log_args: Whether to log function arguments.
        log_result: Whether to log the result.

    Example:
        >>> @log_operation(logger, "save_record")
        ... async def save_record(self, record):
        ...     ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            extra: dict[str, Any] = {"operation": operation}

            if log_args:
                extra["args"] = str(args[1:])  # Skip self
                extra["kwargs"] = str(kwargs)

            logger.debug(f"Starting {operation}", extra=extra)

            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000

                extra["duration_ms"] = round(duration_ms, 2)
                if log_result:
                    extra["result"] = str(result)[:100]  # Truncate

                logger.debug(f"Completed {operation}", extra=extra)
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                extra["duration_ms"] = round(duration_ms, 2)
                extra["error"] = str(e)
                extra["error_type"] = type(e).__name__

                logger.warning(f"Failed {operation}", extra=extra)
                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            extra: dict[str, Any] = {"operation": operation}

            if log_args:
                extra["args"] = str(args[1:])
                extra["kwargs"] = str(kwargs)

            logger.debug(f"Starting {operation}", extra=extra)

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000

                extra["duration_ms"] = round(duration_ms, 2)
                if log_result:
                    extra["result"] = str(result)[:100]

                logger.debug(f"Completed {operation}", extra=extra)
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                extra["duration_ms"] = round(duration_ms, 2)
                extra["error"] = str(e)
                extra["error_type"] = type(e).__name__

                logger.warning(f"Failed {operation}", extra=extra)
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return cast(F, async_wrapper)
        return cast(F, sync_wrapper)

    return decorator


@contextmanager
def log_timing(
    logger: logging.Logger,
    operation: str,
    level: int = logging.DEBUG,
    **extra: Any,
):
    """Context manager to log operation timing.

    Args:
        logger: The logger to use.
        operation: Name of the operation.
        level: Log level for timing message.
        **extra: Additional fields to include.

    Example:
        >>> with log_timing(logger, "batch_insert", batch_size=100):
        ...     await insert_records(records)
    """
    start = time.perf_counter()
    try:
        yield
        duration_ms = (time.perf_counter() - start) * 1000
        logger.log(
            level,
            f"{operation} completed",
            extra={"duration_ms": round(duration_ms, 2), **extra},
        )
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.warning(
            f"{operation} failed",
            extra={
                "duration_ms": round(duration_ms, 2),
                "error": str(e),
                "error_type": type(e).__name__,
                **extra,
            },
        )
        raise


# Convenience loggers for common modules
core_logger = get_logger("core")
store_logger = get_logger("core.store")
context_logger = get_logger("core.context")
query_logger = get_logger("query")
planner_logger = get_logger("planner")
index_logger = get_logger("indexes")
sql_logger = get_logger("sql")
