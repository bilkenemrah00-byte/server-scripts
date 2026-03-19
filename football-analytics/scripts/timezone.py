"""
Timezone utilities — UTC <-> Europe/Istanbul conversions.

All API calls use UTC. All output timestamps use Europe/Istanbul.
This module is the single source of truth for timezone handling.

Reference: KESTRA-AGENT-IMPLEMENTATION-BRIEF.md Section II.2.1
"""

from datetime import datetime, date, timedelta
import pytz

ISTANBUL = pytz.timezone("Europe/Istanbul")
UTC = pytz.UTC


def now_istanbul() -> datetime:
    """Current time in Istanbul timezone."""
    return datetime.now(ISTANBUL)


def now_utc() -> datetime:
    """Current time in UTC."""
    return datetime.now(UTC)


def today_istanbul() -> date:
    """Today's date in Istanbul timezone."""
    return now_istanbul().date()


def tomorrow_istanbul() -> date:
    """Tomorrow's date in Istanbul timezone."""
    return today_istanbul() + timedelta(days=1)


def to_istanbul(dt: datetime) -> datetime:
    """Convert any datetime to Istanbul timezone."""
    if dt.tzinfo is None:
        dt = UTC.localize(dt)
    return dt.astimezone(ISTANBUL)


def to_utc(dt: datetime) -> datetime:
    """Convert any datetime to UTC."""
    if dt.tzinfo is None:
        dt = ISTANBUL.localize(dt)
    return dt.astimezone(UTC)


def timestamp_to_istanbul(timestamp: int) -> datetime:
    """Convert Unix timestamp (UTC) to Istanbul datetime."""
    dt_utc = datetime.fromtimestamp(timestamp, tz=UTC)
    return dt_utc.astimezone(ISTANBUL)


def format_istanbul(dt: datetime) -> str:
    """Format datetime as ISO 8601 with Istanbul offset (+03:00).

    Example output: '2026-03-19T21:00:00+03:00'
    """
    return to_istanbul(dt).isoformat()


def api_date_param(d: date) -> str:
    """Format date for API-Football date parameter (YYYY-MM-DD)."""
    return d.strftime("%Y-%m-%d")


def analysis_timestamp() -> str:
    """Formatted current Istanbul time for report headers."""
    now = now_istanbul()
    return now.strftime("%d %B %Y, %A %H:%M (İstanbul)")


def output_filename_suffix() -> str:
    """Timestamp suffix for output filenames.

    Example: '20260319_0815_istanbul'
    """
    now = now_istanbul()
    return now.strftime("%Y%m%d_%H%M_istanbul")
