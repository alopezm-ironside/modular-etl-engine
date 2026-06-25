import structlog
from google.cloud import bigquery
from sqlalchemy import create_engine

from ..core.base import Base
from ..core.singleton_meta import SingletonMeta

_log = structlog.get_logger(__name__)


class BigQueryConnection(metaclass=SingletonMeta):
    """Pure connection and DDL helper — no control-plane logic."""

    def __init__(
        self,
        *,
        project_id: str,
        credentials: str,
        location: str,
        raw_dataset: str,
        control_dataset: str,
    ) -> None:
        self.credentials = credentials
        self.project_id = project_id
        self.location = location
        self.raw_dataset = raw_dataset
        self.control_dataset = control_dataset
        self.bq_client = bigquery.Client(
            project=self.project_id, location=self.location
        )
        engine = create_engine(
            f"bigquery://{self.project_id}",
            connect_args={"client": self.bq_client},
            credentials_path=self.credentials,
        )
        self.engine = engine.execution_options(
            schema_translate_map={"raw": raw_dataset, "control": control_dataset}
        )
        self.connection = self.engine.connect()

    def create_tables(self) -> None:
        """Create all ORM-mapped tables that do not yet exist."""
        try:
            Base.metadata.create_all(self.engine, checkfirst=True)
        except Exception as exc:
            _log.error("create_tables_failed", error=str(exc))
            raise
