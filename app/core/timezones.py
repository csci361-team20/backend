"""Event time zones. Times are stored in UTC and shown in the event's zone."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import AfterValidator

# Kazakhstan has used one zone (UTC+5) since March 2024
DEFAULT_TIMEZONE = "Asia/Almaty"


def _validate_timezone(name: str) -> str:
    if name not in available_timezones():
        raise ValueError(
            f"Unknown time zone {name!r}; use an IANA name like Asia/Almaty"
        )
    return name


TimeZoneName = Annotated[str, AfterValidator(_validate_timezone)]


def format_local(
    moment: datetime, timezone: str, pattern: str = "%d %B %Y, %H:%M"
) -> str:
    """``moment`` in the given zone, e.g. for emails."""
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return moment.astimezone(zone).strftime(pattern)
