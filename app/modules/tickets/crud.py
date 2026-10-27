from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tickets.models import TicketType


async def get_by_id(db: AsyncSession, id: UUID) -> TicketType | None:
    result = await db.execute(select(TicketType).where(TicketType.id == id))
    return result.scalar_one_or_none()


async def get_by_event(
    db: AsyncSession, event_id: UUID, include_hidden: bool = False
) -> list[TicketType]:
    query = select(TicketType).where(TicketType.event_id == event_id)
    if not include_hidden:
        query = query.where(TicketType.is_hidden.is_(False))
    result = await db.execute(query.order_by(TicketType.price_kzt))
    return list(result.scalars().all())


async def get_total_quantity(
    db: AsyncSession, event_id: UUID, exclude_id: UUID | None = None
) -> int:
    query = select(func.coalesce(func.sum(TicketType.quantity), 0)).where(
        TicketType.event_id == event_id
    )
    if exclude_id:
        query = query.where(TicketType.id != exclude_id)
    result = await db.execute(query)
    return int(result.scalar_one())


async def create(db: AsyncSession, data: dict) -> TicketType:
    ticket_type = TicketType(**data)
    db.add(ticket_type)
    await db.commit()
    await db.refresh(ticket_type)
    return ticket_type


async def update(db: AsyncSession, ticket_type: TicketType, data: dict) -> TicketType:
    for field, value in data.items():
        setattr(ticket_type, field, value)
    await db.commit()
    await db.refresh(ticket_type)
    return ticket_type
