"""Tests for etl_common.utils.dates — parse_naive_utc and convert_utc_to_chile."""

from datetime import datetime, timezone

from etl_common.utils.dates import convert_utc_to_chile, parse_naive_utc

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# parse_naive_utc — new helper
# ---------------------------------------------------------------------------


def test_parse_naive_utc_returns_aware_utc_datetime() -> None:
    """Valid "%Y-%m-%d %H:%M:%S" string is parsed to an aware UTC datetime."""
    result = parse_naive_utc("2024-03-15 10:30:00")
    assert result == datetime(2024, 3, 15, 10, 30, 0, tzinfo=_UTC)
    assert result is not None
    assert result.tzinfo is not None


def test_parse_naive_utc_strips_microseconds() -> None:
    """Strings longer than 19 chars (microseconds) are sliced before parsing."""
    result = parse_naive_utc("2024-03-15 10:30:00.123456")
    assert result == datetime(2024, 3, 15, 10, 30, 0, tzinfo=_UTC)


def test_parse_naive_utc_returns_none_for_none() -> None:
    """None input returns None — no TypeError."""
    assert parse_naive_utc(None) is None


def test_parse_naive_utc_returns_none_for_empty_string() -> None:
    """Empty string input returns None."""
    assert parse_naive_utc("") is None


def test_parse_naive_utc_timezone_is_utc() -> None:
    """The returned datetime has UTC timezone info (not naive)."""
    result = parse_naive_utc("2024-01-01 00:00:00")
    assert result is not None
    assert result.utcoffset() is not None
    assert result.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_parse_naive_utc_midnight() -> None:
    """Midnight parses correctly."""
    result = parse_naive_utc("2024-06-01 00:00:00")
    assert result == datetime(2024, 6, 1, 0, 0, 0, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# convert_utc_to_chile — must keep working unchanged after refactor
# ---------------------------------------------------------------------------


def test_convert_utc_to_chile_datetime_string() -> None:
    """Datetime string is converted to Chile local date string."""
    result = convert_utc_to_chile("2024-03-15 10:00:00")
    # Chile is UTC-3 (or UTC-4 in winter); result must be a date-only string.
    assert len(result) == 10
    assert result[4] == "-" and result[7] == "-"


def test_convert_utc_to_chile_date_only_passthrough() -> None:
    """10-char date-only string is returned unchanged (short-circuit path)."""
    assert convert_utc_to_chile("2024-03-15") == "2024-03-15"


def test_convert_utc_to_chile_empty_returns_empty() -> None:
    """Empty string returns empty string."""
    assert convert_utc_to_chile("") == ""


def test_convert_utc_to_chile_malformed_returns_fallback() -> None:
    """Malformed string returns the first 10 chars (warn+fallback path)."""
    result = convert_utc_to_chile("not-a-date-at-all")
    assert result == "not-a-date"
