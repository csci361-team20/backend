from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.enums import EventStatus, EventVisibility, StaffRole
from app.modules.events.models import Event, StaffAssignment


async def get_by_id(db: AsyncSession, id: UUID) -> Event | None:
    result = await db.execute(select(Event).where(Event.id == id))
    return result.scalar_one_or_none()


async def get_all_public(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    city: str | None = None,
    category: str | None = None,
) -> list[Event]:
    query = select(Event).where(
        Event.status == EventStatus.PUBLISHED,
        Event.visibility == EventVisibility.PUBLIC,
    )
    if city:
        query = query.where(Event.city == city)
    if category:
        query = query.where(Event.category == category)
    result = await db.execute(query.order_by(Event.start_at).offset(skip).limit(limit))
    return list(result.scalars().all())


async def create_with_owner(db: AsyncSession, data: dict, owner_user_id: UUID) -> Event:
    event = Event(**data)
    db.add(event)
    await db.flush()
    db.add(
        StaffAssignment(event_id=event.id, user_id=owner_user_id, role=StaffRole.OWNER)
    )
    await db.commit()
    await db.refresh(event)
    return event


async def update(db: AsyncSession, event: Event, data: dict) -> Event:
    for field, value in data.items():
        setattr(event, field, value)
    await db.commit()
    await db.refresh(event)
    return event


async def get_staff_role(db: AsyncSession, event_id: UUID, user_id: UUID) -> str | None:
    result = await db.execute(
        select(StaffAssignment.role).where(
            StaffAssignment.event_id == event_id,
            StaffAssignment.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_managed_by_user(db: AsyncSession, user_id: UUID) -> list[Event]:
    result = await db.execute(
        select(Event)
        .join(StaffAssignment, StaffAssignment.event_id == Event.id)
        .where(
            StaffAssignment.user_id == user_id,
            StaffAssignment.role.in_([StaffRole.OWNER, StaffRole.MANAGER]),
        )
        .order_by(Event.start_at.desc())
    )
    return list(result.scalars().all())
