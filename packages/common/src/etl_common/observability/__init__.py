"""Observability package — structured logging with pluggable backends."""

from __future__ import annotations

import structlog
from structlog import PrintLoggerFactory, make_filtering_bound_logger

from etl_common.observability.backends import (
    ConsoleLogBackend,
    GcpLogBackend,
    LogBackend,
)
from etl_common.observability.logging import get_logger

_configured: bool = False


def configure_logging(backend: LogBackend) -> None:
    """Configure structlog with the given backend. Idempotent."""
    global _configured
    if _configured:
        return

    structlog.configure(
        processors=backend.processors(),
        wrapper_class=make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def resolve_backend(name: str) -> LogBackend:
    """Return a LogBackend instance for the given name.

    Raises:
        ValueError: when ``name`` does not map to a known backend.
    """
    if name == "gcp":
        return GcpLogBackend()
    if name == "console":
        return ConsoleLogBackend()
    raise ValueError(f"Unknown log backend {name!r}. Valid options: 'gcp', 'console'.")


__all__ = [
    "ConsoleLogBackend",
    "GcpLogBackend",
    "LogBackend",
    "configure_logging",
    "get_logger",
    "resolve_backend",
]
