from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.enums import OrderStatus, TicketStatus
from app.modules.orders.models import Order, OrderItem, Ticket
from app.modules.tickets.models import TicketType


def active_hold() -> ColumnElement[bool]:
    """A pending order whose hold has not run out (no expiry = still holding)."""
    return and_(
        Order.status == OrderStatus.PENDING,
        or_(Order.expires_at.is_(None), Order.expires_at > func.now()),
    )


@dataclass
class Inventory:
    sold: int = 0
    reserved: int = 0
    refunded: int = 0
    checked_in: int = 0

    def available(self, quantity: int) -> int:
        return max(quantity - self.sold - self.reserved, 0)


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


async def count_by_event(db: AsyncSession, event_id: UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(TicketType)
        .where(TicketType.event_id == event_id)
    )
    return int(result.scalar_one())


async def has_order_items(db: AsyncSession, ticket_type_id: UUID) -> bool:
    result = await db.execute(
        select(exists().where(OrderItem.ticket_type_id == ticket_type_id))
    )
    return bool(result.scalar())


async def get_inventory(
    db: AsyncSession, ticket_type_ids: list[UUID]
) -> dict[UUID, Inventory]:
    """Ticket counts per type, from orders and issued tickets.

    ``reserved`` = quantity in pending orders whose hold has not expired.
    Cancelled tickets free their place again.
    """
    counts = {tid: Inventory() for tid in ticket_type_ids}
    if not ticket_type_ids:
        return counts

    issued = await db.execute(
        select(OrderItem.ticket_type_id, Ticket.status, func.count())
        .join(Ticket, Ticket.order_item_id == OrderItem.id)
        .where(OrderItem.ticket_type_id.in_(ticket_type_ids))
        .group_by(OrderItem.ticket_type_id, Ticket.status)
    )
    for ticket_type_id, ticket_status, count in issued.all():
        inventory = counts[ticket_type_id]
        if ticket_status in (TicketStatus.VALID, TicketStatus.CHECKED_IN):
            inventory.sold += count
        if ticket_status == TicketStatus.CHECKED_IN:
            inventory.checked_in += count
        elif ticket_status == TicketStatus.REFUNDED:
            inventory.refunded += count

    reserved = await db.execute(
        select(OrderItem.ticket_type_id, func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.ticket_type_id.in_(ticket_type_ids),
            active_hold(),
        )
        .group_by(OrderItem.ticket_type_id)
    )
    for ticket_type_id, quantity in reserved.all():
        counts[ticket_type_id].reserved = int(quantity)
    return counts


async def delete(db: AsyncSession, ticket_type: TicketType) -> None:
    await db.delete(ticket_type)
    await db.commit()
