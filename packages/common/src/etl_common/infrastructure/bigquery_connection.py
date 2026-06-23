import structlog
from google.cloud import bigquery
from sqlalchemy import create_engine

from ..core.base import Base
from ..core.singleton_meta import SingletonMeta

_log = structlog.get_logger(__name__)


class BigQueryConnection(metaclass=SingletonMeta):
    """Pure connection and DDL helper — no control-plane logic."""

    def __init__(self, credentials: str, project_id: str, location: str) -> None:
        self.credentials = credentials
        self.project_id = project_id
        self.location = location
        self.bq_client = bigquery.Client(
            project=self.project_id, location=self.location
        )
        self.engine = create_engine(
            f"bigquery://{self.project_id}",
            connect_args={"client": self.bq_client},
            credentials_path=self.credentials,
        )
        self.connection = self.engine.connect()

    def create_dataset_if_not_exists(
        self, dataset_id: str, description: str = ""
    ) -> None:
        """Create the BigQuery dataset if it does not already exist."""
        dataset_ref = f"{self.project_id}.{dataset_id}"
        try:
            self.bq_client.get_dataset(dataset_ref)
        except Exception:
            dataset = bigquery.Dataset(dataset_ref)
            dataset.description = description
            self.bq_client.create_dataset(dataset, timeout=30)
            _log.info("dataset_created", dataset_id=dataset_id)

    def create_tables(self) -> None:
        """Create all ORM-mapped tables that do not yet exist."""
        try:
            Base.metadata.create_all(self.engine, checkfirst=True)
        except Exception as exc:
            _log.error("create_tables_failed", error=str(exc))
            raise
