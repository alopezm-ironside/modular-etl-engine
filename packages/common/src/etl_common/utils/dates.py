from datetime import datetime
from zoneinfo import ZoneInfo

from etl_common.observability import get_logger

_log = get_logger(__name__)

_UTC = ZoneInfo("UTC")
_CHILE = ZoneInfo("America/Santiago")

_NAIVE_UTC_FMT = "%Y-%m-%d %H:%M:%S"


def parse_naive_utc(date_string: str | None) -> datetime | None:
    """Parse a naive UTC timestamp string into a timezone-aware UTC datetime.

    Accepts strings in "%Y-%m-%d %H:%M:%S" format. Longer strings (e.g. with
    microseconds) are truncated to 19 chars before parsing. Returns None for
    None or empty input.
    """
    if not date_string:
        return None
    return datetime.strptime(date_string[:19], _NAIVE_UTC_FMT).replace(tzinfo=_UTC)


def convert_utc_to_chile(date_string: str) -> str:
    """Convierte fechas UTC a zona horaria de Chile."""
    if not date_string:
        return ""

    try:
        date_str = str(date_string)

        if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
            return date_str

        dt = parse_naive_utc(date_str)
        if dt is None:
            return date_string[:10] if date_string else ""
        return dt.astimezone(_CHILE).strftime("%Y-%m-%d")
    except Exception as e:
        _log.warning(
            "date_conversion_failed",
            date_string=date_string,
            error=type(e).__name__,
        )
        return date_string[:10] if date_string else ""
