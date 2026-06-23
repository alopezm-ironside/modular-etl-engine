"""Logging backend adapters for the structlog pipeline.

Each backend implements the LogBackend Protocol, returning a processor chain
that structlog uses to format and emit log records.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Protocol, runtime_checkable

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import (
    EventRenamer,
    JSONRenderer,
    TimeStamper,
    add_log_level,
)
from structlog.types import EventDict, Processor

# Protocol must be imported at runtime for isinstance checks by tests/callers.


@runtime_checkable
class LogBackend(Protocol):
    """Port for structlog processor chain configuration."""

    def processors(self) -> list[Processor]: ...


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


class GcpLogBackend:
    """Processor chain that emits GCP-compatible single-line JSON."""

    def processors(self) -> list[Processor]:
        return [
            structlog.contextvars.merge_contextvars,
            _add_severity,
            TimeStamper(fmt="iso", utc=True),
            EventRenamer("message"),
            JSONRenderer(),
        ]


class ConsoleLogBackend:
    """Processor chain that emits human-readable console output for development."""

    def processors(self) -> list[Processor]:
        return [
            structlog.contextvars.merge_contextvars,
            add_log_level,
            TimeStamper(fmt="iso"),
            ConsoleRenderer(),
        ]
