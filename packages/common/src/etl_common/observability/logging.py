"""Backend-agnostic logger factory.

All application code imports get_logger from here (or from the package root),
never from the backend-specific modules.
"""

from __future__ import annotations

from typing import Any

import structlog


def get_logger(name: str) -> Any:
    """Return a bound structlog logger for ``name`` (typically ``__name__``).

    Any return: structlog's BoundLogger generics trip strict mypy; callers duck-type.
    """
    return structlog.get_logger(name)
