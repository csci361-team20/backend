from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events import crud
from app.modules.events.enums import EventStatus
from app.modules.events.models import Event
from app.modules.events.schemas import EventCreate, EventUpdate
from app.modules.organizers import crud as organizer_crud


async def create_event(db: AsyncSession, data_in: EventCreate) -> Event:
    profile = await organizer_crud.get_by_id(db, data_in.organizer_profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organizer profile not found")
    return await crud.create_with_owner(db, data_in.model_dump(), profile.user_id)


async def get_event(db: AsyncSession, id: UUID) -> Event:
    event = await crud.get_by_id(db, id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return event


async def get_public_events(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    city: str | None = None,
    category: str | None = None,
) -> list[Event]:
    return await crud.get_all_public(db, skip, limit, city, category)


async def update_event(db: AsyncSession, id: UUID, data_in: EventUpdate) -> Event:
    event = await get_event(db, id)
    if event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cancelled or completed events cannot be edited",
        )
    # exclude_none: explicit nulls must not wipe required columns
    data = data_in.model_dump(exclude_unset=True, exclude_none=True)
    start_at = data.get("start_at", event.start_at)
    end_at = data.get("end_at", event.end_at)
    if end_at <= start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "end_at must be after start_at"
        )
    return await crud.update(db, event, data)


async def publish_event(db: AsyncSession, id: UUID) -> Event:
    event = await get_event(db, id)
    if event.status != EventStatus.DRAFT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only draft events can be published"
        )
    return await crud.update(db, event, {"status": EventStatus.PUBLISHED})


async def cancel_event(db: AsyncSession, id: UUID) -> Event:
    event = await get_event(db, id)
    if event.status not in (EventStatus.DRAFT, EventStatus.PUBLISHED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only draft or published events can be cancelled",
        )
    return await crud.update(db, event, {"status": EventStatus.CANCELLED})
