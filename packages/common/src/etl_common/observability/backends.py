"""Logging backend adapters for the structlog pipeline.

Each backend implements the LogBackend Protocol, returning a processor chain
that structlog uses to format and emit log records.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import structlog
import structlog_gcp
from structlog.dev import ConsoleRenderer
from structlog.processors import TimeStamper, add_log_level
from structlog.types import Processor


@runtime_checkable
class LogBackend(Protocol):
    """Port for structlog processor chain configuration."""

    def processors(self) -> list[Processor]: ...


class GcpLogBackend:
    """Cloud Logging JSON via structlog-gcp.

    Emits the GCP-native format: severity, message, time, sourceLocation, and
    bound context, and routes exceptions to Error Reporting (stack_trace +
    @type). Using the library avoids hand-maintaining the GCP field mapping.
    """

    def processors(self) -> list[Processor]:
        return structlog_gcp.build_processors()


class ConsoleLogBackend:
    """Processor chain that emits human-readable console output for development."""

    def processors(self) -> list[Processor]:
        return [
            structlog.contextvars.merge_contextvars,
            add_log_level,
            TimeStamper(fmt="iso"),
            ConsoleRenderer(),
        ]
