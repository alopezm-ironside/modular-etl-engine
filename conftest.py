import etl_common.observability as observability
import pytest
import structlog
from etl_common.core.singleton_meta import SingletonMeta
from structlog.contextvars import clear_contextvars


@pytest.fixture(autouse=True)
def _isolate_global_state():
    """Reset process-global state between tests so random ordering is safe."""
    clear_contextvars()
    structlog.reset_defaults()
    observability._configured = False
    SingletonMeta._instances.clear()
    yield
    clear_contextvars()
