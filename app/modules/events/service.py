from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events import crud
from app.modules.events.enums import EventStatus, EventVisibility, StaffRole
from app.modules.events.models import Event
from app.modules.events.schemas import EventCreate, EventUpdate
from app.modules.organizers import service as organizer_service
from app.modules.users.models import User


async def ensure_event_role(
    db: AsyncSession,
    event: Event,
    user: User,
    allowed: tuple[StaffRole, ...] = (StaffRole.OWNER, StaffRole.MANAGER),
    allow_admin: bool = False,
) -> None:
    """Raise 403 unless the user holds one of the allowed roles on this event."""
    if allow_admin and user.is_platform_admin:
        return
    role = await crud.get_staff_role(db, event.id, user.id)
    if role not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission for this event"
        )


async def create_event(db: AsyncSession, user: User, data_in: EventCreate) -> Event:
    profile = await organizer_service.get_or_create_profile(db, user)
    data = {**data_in.model_dump(), "organizer_profile_id": profile.id}
    return await crud.create_with_owner(db, data, user.id)


async def get_event(db: AsyncSession, id: UUID) -> Event:
    event = await crud.get_by_id(db, id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return event


async def get_event_for_viewer(db: AsyncSession, id: UUID, user: User | None) -> Event:
    """Drafts and private events are visible to staff only (404 for everyone else)."""
    event = await get_event(db, id)
    is_public = (
        event.status != EventStatus.DRAFT
        and event.visibility != EventVisibility.PRIVATE
    )
    if is_public:
        return event
    if user is not None and (
        user.is_platform_admin or await crud.get_staff_role(db, event.id, user.id)
    ):
        return event
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")


async def get_public_events(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    city: str | None = None,
    category: str | None = None,
) -> list[Event]:
    return await crud.get_all_public(db, skip, limit, city, category)


async def get_managed_events(db: AsyncSession, user: User) -> list[Event]:
    return await crud.get_managed_by_user(db, user.id)


async def update_event(
    db: AsyncSession, user: User, id: UUID, data_in: EventUpdate
) -> Event:
    event = await get_event(db, id)
    await ensure_event_role(db, event, user)
    if event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cancelled or completed events cannot be edited",
        )
    data = data_in.model_dump(exclude_unset=True, exclude_none=True)
    start_at = data.get("start_at", event.start_at)
    end_at = data.get("end_at", event.end_at)
    if end_at <= start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "end_at must be after start_at"
        )
    return await crud.update(db, event, data)


async def publish_event(db: AsyncSession, user: User, id: UUID) -> Event:
    event = await get_event(db, id)
    await ensure_event_role(db, event, user)
    if event.status != EventStatus.DRAFT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only draft events can be published"
        )
    return await crud.update(db, event, {"status": EventStatus.PUBLISHED})


async def cancel_event(db: AsyncSession, user: User, id: UUID) -> Event:
    event = await get_event(db, id)
    await ensure_event_role(
        db, event, user, allowed=(StaffRole.OWNER,), allow_admin=True
    )
    if event.status not in (EventStatus.DRAFT, EventStatus.PUBLISHED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only draft or published events can be cancelled",
        )
    return await crud.update(db, event, {"status": EventStatus.CANCELLED})
