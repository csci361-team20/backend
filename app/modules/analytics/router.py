from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.analytics import service as analytics_service
from app.modules.analytics.schemas import EventAnalytics, EventOverviewRow

router = APIRouter(tags=["Analytics"])


@router.get("/analytics/events", response_model=list[EventOverviewRow])
async def analytics_overview(db: DatabaseSession, actor: CurrentUser):
    """Capacity, sales, attendance and net revenue for each event you own or
    manage, newest first."""
    return await analytics_service.overview(db, actor)


@router.get("/events/{event_id}/analytics", response_model=EventAnalytics)
async def event_analytics(
    event_id: UUID,
    db: DatabaseSession,
    actor: CurrentUser,
    date_from: Annotated[
        datetime | None, Query(description="Orders confirmed at or after")
    ] = None,
    date_to: Annotated[
        datetime | None, Query(description="Orders confirmed before")
    ] = None,
    ticket_type_id: UUID | None = None,
):
    """The organizer dashboard (SRS 4.15): capacity and percent sold; gross
    sales, discounts, refunds and net revenue in KZT; sales over time by day
    in the event's time zone; results per ticket type and per campaign; and
    checked-in versus absent ticket holders. Owner, manager or admin."""
    date_from = analytics_service.as_utc(date_from)
    date_to = analytics_service.as_utc(date_to)
    if date_from and date_to and date_to <= date_from:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "date_to must be after date_from"
        )
    return await analytics_service.event_analytics(
        db, event_id, actor, date_from, date_to, ticket_type_id
    )
