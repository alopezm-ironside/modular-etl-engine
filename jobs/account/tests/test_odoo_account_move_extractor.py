"""OdooAccountMoveExtractor — write_date cursor behavior and limit handling."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from account.services.extractors.odoo_account_move_extractor import (
    OdooAccountMoveExtractor,
)

_UTC = timezone.utc


def _make_extractor(limit: int = 0) -> tuple[OdooAccountMoveExtractor, MagicMock]:
    odoo = MagicMock()
    odoo.search.return_value = []
    return OdooAccountMoveExtractor(odoo, extract_limit=limit), odoo


# ---------------------------------------------------------------------------
# S4 — incremental fetch passes write_date >= domain and write_date asc order
# ---------------------------------------------------------------------------


def test_fetch_new_ids_incremental_uses_write_date_gte_domain() -> None:
    """fetch_new_ids(watermark=dt) must pass write_date >= domain and correct order."""
    extractor, odoo = _make_extractor()
    watermark = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)

    extractor.fetch_new_ids(watermark=watermark)

    _, kwargs = odoo.search.call_args
    domain = odoo.search.call_args[0][1]
    assert ("write_date", ">=", "2024-03-15 10:00:00") in domain
    assert ("line_ids", "!=", False) in domain
    assert ("id", ">", watermark) not in domain
    assert kwargs["order"] == "write_date asc, id asc"


# ---------------------------------------------------------------------------
# S7 — cold start: watermark=None omits write_date predicate
# ---------------------------------------------------------------------------


def test_fetch_new_ids_cold_start_omits_write_date_predicate() -> None:
    """fetch_new_ids(watermark=None) must NOT add a write_date filter."""
    extractor, odoo = _make_extractor()

    extractor.fetch_new_ids(watermark=None)

    domain = odoo.search.call_args[0][1]
    assert ("line_ids", "!=", False) in domain
    assert not any("write_date" in str(t) for t in domain), (
        f"Cold start domain must not filter write_date; got {domain}"
    )
    _, kwargs = odoo.search.call_args
    assert kwargs["order"] == "id asc"


# ---------------------------------------------------------------------------
# S12 — boundary: >= includes record at exact watermark ts
# ---------------------------------------------------------------------------


def test_fetch_new_ids_uses_gte_operator_for_boundary_overlap() -> None:
    """Domain operator must be >= so records at exact watermark are re-fetched."""
    extractor, odoo = _make_extractor()
    watermark = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)

    extractor.fetch_new_ids(watermark=watermark)

    domain = odoo.search.call_args[0][1]
    write_date_filter = next(
        (t for t in domain if isinstance(t, tuple) and t[0] == "write_date"), None
    )
    assert write_date_filter is not None
    assert write_date_filter[1] == ">=", (
        f"Expected '>=' operator for write_date filter; got {write_date_filter[1]}"
    )


# ---------------------------------------------------------------------------
# S5 — max_cursor returns max write_date from raw batch
# ---------------------------------------------------------------------------


def test_max_cursor_returns_maximum_write_date_from_batch() -> None:
    """max_cursor must return the highest write_date across the batch."""
    extractor, _ = _make_extractor()
    raw_batch = [
        {"write_date": "2024-03-15 09:00:00"},
        {"write_date": "2024-03-15 10:30:00"},
        {"write_date": "2024-03-15 10:00:00"},
    ]

    result = extractor.max_cursor(raw_batch)

    expected = datetime(2024, 3, 15, 10, 30, 0, tzinfo=_UTC)
    assert result == expected, f"Expected {expected}, got {result}"


def test_max_cursor_skips_none_write_date_entries() -> None:
    """max_cursor must not crash when some records have None write_date."""
    extractor, _ = _make_extractor()
    raw_batch = [
        {"write_date": None},
        {"write_date": "2024-03-15 10:00:00"},
    ]

    result = extractor.max_cursor(raw_batch)
    assert result == datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# cold_start_cursor returns None
# ---------------------------------------------------------------------------


def test_cold_start_cursor_returns_none() -> None:
    """cold_start_cursor must return None (full-pull sentinel)."""
    extractor, _ = _make_extractor()
    assert extractor.cold_start_cursor() is None


# ---------------------------------------------------------------------------
# Decision 5 crash-safety / ordering invariant
# ---------------------------------------------------------------------------


def test_cursor_ordering_invariant_crash_safety() -> None:
    """Decision 5: cursor-ordered extraction ensures no records are lost on crash.

    Simulate two batches ordered write_date asc. After batch 1 is checkpointed,
    batch 2 still has write_date >= checkpoint. This verifies the invariant.
    """
    batch1_ts = "2024-03-15 09:00:00"
    batch2_ts = "2024-03-15 10:00:00"

    batch1 = [{"id": 1, "write_date": batch1_ts}]
    batch2 = [{"id": 2, "write_date": batch2_ts}]

    extractor, _ = _make_extractor()

    # After batch 1, watermark = max(batch1)
    checkpoint = extractor.max_cursor(batch1)
    assert checkpoint == datetime(2024, 3, 15, 9, 0, 0, tzinfo=_UTC)

    # On next run from checkpoint, batch2 records must satisfy write_date >= checkpoint
    batch2_dt = datetime.strptime(batch2[0]["write_date"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=_UTC
    )
    assert batch2_dt >= checkpoint, (
        "Batch 2 write_date must be >= checkpoint; ordering invariant violated"
    )

    # Advancing cursor from batch2 should yield a strictly later cursor
    new_cursor = extractor.max_cursor(batch2)
    assert new_cursor > checkpoint, "Cursor must advance monotonically"


# ---------------------------------------------------------------------------
# Original limit tests — preserved with new fetch signature
# ---------------------------------------------------------------------------


def test_fetch_new_ids_passes_configured_limit_to_search() -> None:
    extractor, odoo = _make_extractor(limit=2000)

    extractor.fetch_new_ids(watermark=None)

    _, kwargs = odoo.search.call_args
    assert kwargs["limit"] == 2000


def test_fetch_new_ids_without_limit_passes_none() -> None:
    extractor, odoo = _make_extractor()

    extractor.fetch_new_ids(watermark=None)

    _, kwargs = odoo.search.call_args
    assert kwargs["limit"] is None


# ---------------------------------------------------------------------------
# LINE_FIELDS includes write_date (FR-0, S-11)
# ---------------------------------------------------------------------------


def test_line_fields_includes_write_date() -> None:
    """LINE_FIELDS must request write_date from Odoo for Bronze line dedup symmetry."""
    extractor, _ = _make_extractor()
    assert "write_date" in extractor.LINE_FIELDS, (
        "LINE_FIELDS must include write_date for Bronze line dedup symmetry"
    )
