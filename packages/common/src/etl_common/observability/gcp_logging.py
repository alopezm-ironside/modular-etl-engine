"""GCP structured logging: configures structlog to emit single-line JSON on
stdout with the ``severity`` key Cloud Logging recognises, so Cloud Run ingests
logs without an agent or sink config."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.types import EventDict

_configured: bool = False

_LEVEL_TO_SEVERITY: dict[str, str] = {
    "debug": "DEBUG",
    "info": "INFO",
    "warning": "WARNING",
    "warn": "WARNING",
    "error": "ERROR",
    "critical": "CRITICAL",
}


def _add_severity(
    _: Any,
    method: str,
    event_dict: MutableMapping[str, Any],
) -> EventDict:
    """Set the GCP-recognised ``severity`` key from the log method name."""
    event_dict["severity"] = _LEVEL_TO_SEVERITY.get(method.lower(), method.upper())
    return event_dict


def configure_gcp_logging() -> None:
    """Wire the structlog GCP-JSON pipeline. Idempotent; call once at the
    composition root before any log call or context binding."""
    global _configured
    if _configured:
        return

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_severity,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str) -> Any:
    """Return a bound structlog logger for ``name`` (typically ``__name__``)."""
    # Any return: structlog's BoundLogger generics trip strict mypy; callers duck-type.
    return structlog.get_logger(name)
