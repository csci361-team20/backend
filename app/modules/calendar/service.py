"""Calendar export (SRS 4.11, UC6).

- An iCalendar (.ics) file per event, in the event's own time zone, with a
  stable UID so an updated file replaces the earlier entry. A SEQUENCE
  number rises with every relevant change; a cancelled event's file says
  STATUS:CANCELLED so calendars remove or strike it out.
- One-click links for Google Calendar, Outlook and Yahoo.

Nothing here asks for access to anyone's calendar account.
"""

from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.modules.events.enums import EventStatus
from app.modules.events.models import Event

PRODID = "-//BiletFlow//Event Calendar//EN"


def event_url(event_id: UUID) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/events/{event_id}"


def ics_url(event_id: UUID) -> str:
    return (
        f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/events/{event_id}/calendar.ics"
    )


def _escape(text: str) -> str:
    """RFC 5545 TEXT escaping."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        piece = char.encode("utf-8")
        limit = 75 if not parts else 74
        if len(current) + len(piece) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
        current += piece
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _offset(delta) -> str:
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}{(total % 3600) // 60:02d}"


def _location(event: Event) -> str:
    return ", ".join(
        p for p in (event.venue_name, event.venue_address, event.city) if p
    )


def build_ics(event: Event) -> str:
    zone = ZoneInfo(event.timezone)
    start = event.start_at.astimezone(zone)
    end = event.end_at.astimezone(zone)
    offset = _offset(start.utcoffset())
    cancelled = event.status == EventStatus.CANCELLED
    stamp = (event.updated_at or event.created_at or datetime.now(UTC)).astimezone(UTC)
    description = event.description or event.subtitle or ""
    if cancelled:
        description = f"CANCELLED. {description}".strip()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        f"METHOD:{'CANCEL' if cancelled else 'PUBLISH'}",
        # Kazakhstan has no daylight saving; the offset at the event's start
        # describes the zone for the event's dates
        "BEGIN:VTIMEZONE",
        f"TZID:{event.timezone}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        f"TZOFFSETFROM:{offset}",
        f"TZOFFSETTO:{offset}",
        f"TZNAME:{start.tzname() or offset}",
        "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        # Stable across updates, so calendars replace rather than duplicate
        f"UID:event-{event.id}@biletflow",
        f"SEQUENCE:{event.calendar_sequence}",
        f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}",
        f"DTSTART;TZID={event.timezone}:{start:%Y%m%dT%H%M%S}",
        f"DTEND;TZID={event.timezone}:{end:%Y%m%dT%H%M%S}",
        f"SUMMARY:{_escape(event.title)}",
        f"DESCRIPTION:{_escape(description + chr(10) + event_url(event.id))}",
        f"LOCATION:{_escape(_location(event))}",
        f"URL:{event_url(event.id)}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        "TRANSP:OPAQUE",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def calendar_links(event: Event) -> dict[str, str]:
    """One-click "add to calendar" links; none needs calendar write access."""
    start = event.start_at.astimezone(UTC)
    end = event.end_at.astimezone(UTC)
    details = f"{event.subtitle or ''}\n{event_url(event.id)}".strip()
    location = _location(event)
    google = "https://calendar.google.com/calendar/render?" + urlencode(
        {
            "action": "TEMPLATE",
            "text": event.title,
            "dates": f"{start:%Y%m%dT%H%M%SZ}/{end:%Y%m%dT%H%M%SZ}",
            "details": details,
            "location": location,
            "ctz": event.timezone,
        }
    )
    outlook = "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(
        {
            "path": "/calendar/action/compose",
            "rru": "addevent",
            "subject": event.title,
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
            "body": details,
            "location": location,
        }
    )
    yahoo = "https://calendar.yahoo.com/?" + urlencode(
        {
            "v": "60",
            "title": event.title,
            "st": f"{start:%Y%m%dT%H%M%SZ}",
            "et": f"{end:%Y%m%dT%H%M%SZ}",
            "desc": details,
            "in_loc": location,
        }
    )
    return {
        "ics": ics_url(event.id),
        "google": google,
        "outlook": outlook,
        "yahoo": yahoo,
    }
