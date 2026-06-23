import http.client
import logging
import random
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
INITIAL_BACKOFF = 2
MAX_BACKOFF = 60

_RETRYABLE = (
    http.client.ResponseNotReady,
    http.client.HTTPException,
    ConnectionError,
    BrokenPipeError,
    TimeoutError,
)


def execute_with_retry(
    func: Callable[..., Any],
    *args: Any,
    operation_name: str = "Operation",
    **kwargs: Any,
) -> Any:
    """Exponential-backoff retry for transient network errors."""
    retry_count = 0
    backoff_time = INITIAL_BACKOFF

    while retry_count <= MAX_RETRIES:
        try:
            return func(*args, **kwargs)
        except _RETRYABLE as e:
            retry_count += 1

            if retry_count > MAX_RETRIES:
                logger.error(
                    f"{operation_name} failed after {MAX_RETRIES} retries: {e}"
                )
                raise

            jitter = random.uniform(0, 0.1 * backoff_time)
            wait_time = backoff_time + jitter

            logger.warning(
                f"{operation_name} failed (attempt {retry_count}/{MAX_RETRIES}): "
                f"{type(e).__name__}"
            )
            logger.warning(f"   Retrying in {wait_time:.2f} seconds...")

            time.sleep(wait_time)

            backoff_time = min(backoff_time * 2, MAX_BACKOFF)
        except Exception as e:
            logger.error(
                f"{operation_name} failed with non-retryable error: "
                f"{type(e).__name__}: {e}"
            )
            raise
