from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.api.deps import DatabaseSession, OptionalUser
from app.modules.calendar import service as calendar_service
from app.modules.events import service as event_service

router = APIRouter(tags=["Calendar"])


class CalendarLinks(BaseModel):
    ics: str
    google: str
    outlook: str
    yahoo: str


@router.get(
    "/events/{event_id}/calendar.ics",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
async def event_calendar_file(event_id: UUID, db: DatabaseSession, actor: OptionalUser):
    """Download the event as an iCalendar file (SRS 4.11), in the event's time
    zone. After a change or a cancellation, downloading it again replaces the
    earlier calendar entry."""
    event = await event_service.get_visible_event(db, event_id, actor)
    return Response(
        calendar_service.build_ics(event),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="biletflow-{event_id}.ics"'
        },
    )


@router.get("/events/{event_id}/calendar-links", response_model=CalendarLinks)
async def event_calendar_links(
    event_id: UUID, db: DatabaseSession, actor: OptionalUser
):
    """One-click links for Google Calendar, Outlook and Yahoo, plus the .ics
    file. None of them asks for access to the attendee's calendar."""
    event = await event_service.get_visible_event(db, event_id, actor)
    return calendar_service.calendar_links(event)
