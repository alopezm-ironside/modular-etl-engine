"""ORM schema: write_date on AccountMoveORM, last_processed_ts on SyncMetadata."""


def test_account_move_orm_has_write_date_column() -> None:
    """AccountMoveORM must declare write_date as a DateTime column."""
    from account.persistence.models.account_move import AccountMoveORM
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(AccountMoveORM)
    col_names = {c.key for c in mapper.columns}
    assert "write_date" in col_names, "AccountMoveORM is missing write_date column"


def test_account_move_orm_write_date_is_datetime_and_nullable() -> None:
    """write_date must be DateTime type and nullable with no default."""
    from account.persistence.models.account_move import AccountMoveORM
    from sqlalchemy import DateTime
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(AccountMoveORM)
    col = mapper.columns["write_date"]
    assert isinstance(col.type, DateTime), f"Expected DateTime, got {type(col.type)}"
    assert col.nullable, "write_date must be nullable"
    assert col.default is None, "write_date must have no default"


def test_account_move_line_orm_has_write_date_column() -> None:
    """AccountMoveLineORM must declare write_date as a DateTime column."""
    from account.persistence.models.account_move_line import AccountMoveLineORM
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(AccountMoveLineORM)
    col_names = {c.key for c in mapper.columns}
    assert "write_date" in col_names, "AccountMoveLineORM is missing write_date column"


def test_account_move_line_orm_write_date_is_datetime_and_nullable() -> None:
    """write_date on AccountMoveLineORM must be DateTime, nullable, with no default."""
    from account.persistence.models.account_move_line import AccountMoveLineORM
    from sqlalchemy import DateTime
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(AccountMoveLineORM)
    col = mapper.columns["write_date"]
    assert isinstance(col.type, DateTime), f"Expected DateTime, got {type(col.type)}"
    assert col.nullable, "write_date must be nullable"
    assert col.default is None, "write_date must have no default"


def test_sync_metadata_has_last_processed_ts_column() -> None:
    """SyncMetadata must declare last_processed_ts as a DateTime column."""
    from etl_common.models.sync_metadata import SyncMetadata
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(SyncMetadata)
    col_names = {c.key for c in mapper.columns}
    assert "last_processed_ts" in col_names, (
        "SyncMetadata is missing last_processed_ts column"
    )


def test_sync_metadata_does_not_have_last_processed_id_column() -> None:
    """SyncMetadata must NOT have last_processed_id (id-watermark is removed)."""
    from etl_common.models.sync_metadata import SyncMetadata
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(SyncMetadata)
    col_names = {c.key for c in mapper.columns}
    assert "last_processed_id" not in col_names, (
        "SyncMetadata still has last_processed_id; it must be removed"
    )
