"""Composition root for the account ETL Cloud Run Job.

Exposed as the `account-job` console script (see pyproject.toml) and invoked
directly by the container ENTRYPOINT.
"""

from etl_common.conf.settings import Settings
from etl_common.infrastructure.bigquery_connection import BigQueryConnection
from etl_common.infrastructure.odoo_manager import OdooManager
from etl_common.observability.gcp_logging import configure_gcp_logging
from etl_common.sync_pipeline import SyncPipeline

from account.persistence.repositories.bigquery_account_move_repository import (
    BigQueryAccountMoveRepository,
)
from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState
from account.services.extractors.odoo_account_move_extractor import (
    OdooAccountMoveExtractor,
)
from account.services.transformers.account_move_transformer import (
    AccountMoveTransformer,
)


def main() -> None:
    configure_gcp_logging()

    settings = Settings()

    odoo = OdooManager(
        url=settings.ODOO_URL,
        db=settings.ODOO_DB,
        user=settings.ODOO_USER,
        password=settings.ODOO_PASSWORD,
    )
    odoo.connect()

    connection = BigQueryConnection(
        project_id=settings.GOOGLE_PROJECT_ID,
        credentials=settings.GOOGLE_CREDENTIAL_SERVICE_FILE,
        location=settings.GOOGLE_LOCATION,
    )
    connection.create_dataset_if_not_exists(
        settings.BQ_DATASET_RAW, description="Raw data from Odoo ERP"
    )
    connection.create_dataset_if_not_exists(
        settings.BQ_DATASET_CONTROL, description="Sync control and metadata"
    )
    connection.create_tables()

    extractor = OdooAccountMoveExtractor(odoo)
    transformer = AccountMoveTransformer(extractor)
    repository = BigQueryAccountMoveRepository(connection)
    sync_state = BigQuerySyncState(connection, settings.BQ_DATASET_CONTROL)

    SyncPipeline(
        module_name="accounting",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=settings.BATCH_SIZE,
    ).run()


if __name__ == "__main__":
    main()
