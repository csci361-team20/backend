from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.enums import EventStatus, EventVisibility, StaffRole
from app.modules.events.models import Event, StaffAssignment
from app.modules.events.schemas import EventSort
from app.modules.orders.enums import OrderStatus, TicketStatus
from app.modules.orders.models import Order, OrderItem, Ticket
from app.modules.organizers.models import OrganizerProfile
from app.modules.tickets.crud import active_hold
from app.modules.tickets.models import TicketType
from app.modules.users.models import User


async def get_by_id(db: AsyncSession, id: UUID) -> Event | None:
    result = await db.execute(select(Event).where(Event.id == id))
    return result.scalar_one_or_none()


async def get_visible_ticket_types(
    db: AsyncSession, event_ids: list[UUID]
) -> dict[UUID, list[TicketType]]:
    result = await db.execute(
        select(TicketType)
        .where(TicketType.event_id.in_(event_ids), TicketType.is_hidden.is_(False))
        .order_by(TicketType.price_kzt)
    )
    grouped: dict[UUID, list[TicketType]] = {}
    for ticket_type in result.scalars().all():
        grouped.setdefault(ticket_type.event_id, []).append(ticket_type)
    return grouped


async def get_organizer_names(
    db: AsyncSession, profile_ids: set[UUID]
) -> dict[UUID, str]:
    result = await db.execute(
        select(OrganizerProfile.id, OrganizerProfile.display_name).where(
            OrganizerProfile.id.in_(profile_ids)
        )
    )
    return {row.id: row.display_name for row in result}


async def get_all_public(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    city: str | None = None,
    category: str | None = None,
    q: str | None = None,
    starts_from: datetime | None = None,
    starts_to: datetime | None = None,
    include_past: bool = False,
    sort: EventSort = EventSort.START_ASC,
) -> list[Event]:
    suspended_organizers = (
        select(OrganizerProfile.id)
        .join(User, User.id == OrganizerProfile.user_id)
        .where(User.is_suspended.is_(True))
    )
    query = select(Event).where(
        Event.status == EventStatus.PUBLISHED,
        Event.visibility == EventVisibility.PUBLIC,
        Event.is_suspended.is_(False),
        Event.organizer_profile_id.not_in(suspended_organizers),
    )
    if city:
        query = query.where(func.lower(Event.city) == city.strip().lower())
    if category:
        query = query.where(func.lower(Event.category) == category.strip().lower())
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                Event.title.ilike(pattern),
                Event.subtitle.ilike(pattern),
                Event.venue_name.ilike(pattern),
            )
        )
    if starts_from:
        query = query.where(Event.start_at >= starts_from)
    if starts_to:
        query = query.where(Event.start_at < starts_to)
    if not include_past:
        query = query.where(Event.end_at > func.now())
    order = Event.start_at.desc() if sort == EventSort.START_DESC else Event.start_at
    result = await db.execute(query.order_by(order).offset(skip).limit(limit))
    return list(result.scalars().all())


async def has_live_orders(db: AsyncSession, event_id: UUID) -> bool:
    """Confirmed orders or holds still running (expired/cancelled ones don't count)."""
    result = await db.execute(
        select(
            exists().where(
                Order.event_id == event_id,
                or_(Order.status == OrderStatus.CONFIRMED, active_hold()),
            )
        )
    )
    return bool(result.scalar())


async def cancel_event_orders(db: AsyncSession, event_id: UUID) -> list[UUID]:
    """Void every unused ticket and close every open order. No commit.

    Returns the buyers of the confirmed orders that were cancelled. Only
    call once paid orders are refunded or ruled out (refunds: phase 7).
    """
    now = func.now()
    confirmed = select(Order.id).where(
        Order.event_id == event_id, Order.status == OrderStatus.CONFIRMED
    )
    buyers = await db.execute(
        select(Order.user_id)
        .where(Order.event_id == event_id, Order.status == OrderStatus.CONFIRMED)
        .distinct()
    )
    buyer_ids = list(buyers.scalars().all())
    items = select(OrderItem.id).where(OrderItem.order_id.in_(confirmed))
    await db.execute(
        sql_update(Ticket)
        .where(Ticket.order_item_id.in_(items), Ticket.status == TicketStatus.VALID)
        .values(status=TicketStatus.CANCELLED)
    )
    await db.execute(
        sql_update(Order)
        .where(
            Order.event_id == event_id,
            Order.status.in_((OrderStatus.CONFIRMED, OrderStatus.PENDING)),
        )
        .values(status=OrderStatus.CANCELLED, cancelled_at=now, expires_at=None)
    )
    return buyer_ids


async def create_copy(
    db: AsyncSession,
    data: dict,
    owner_user_id: UUID,
    ticket_types: list[dict],
) -> Event:
    """Create an event, its owner assignment and ticket types in one commit."""
    event = Event(**data)
    db.add(event)
    await db.flush()
    db.add(
        StaffAssignment(event_id=event.id, user_id=owner_user_id, role=StaffRole.OWNER)
    )
    for ticket_type in ticket_types:
        db.add(TicketType(**ticket_type, event_id=event.id))
    await db.commit()
    await db.refresh(event)
    return event


async def get_for_staff_user(
    db: AsyncSession, user_id: UUID, roles: tuple[StaffRole, ...] | None = None
) -> list[tuple[Event, str]]:
    query = (
        select(Event, StaffAssignment.role)
        .join(StaffAssignment, StaffAssignment.event_id == Event.id)
        .where(StaffAssignment.user_id == user_id)
    )
    if roles:
        query = query.where(StaffAssignment.role.in_(roles))
    result = await db.execute(query.order_by(Event.start_at.desc()))
    return [(event, role) for event, role in result.all()]


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


async def get_staff(
    db: AsyncSession, event_id: UUID
) -> list[tuple[StaffAssignment, User]]:
    result = await db.execute(
        select(StaffAssignment, User)
        .join(User, User.id == StaffAssignment.user_id)
        .where(StaffAssignment.event_id == event_id)
        .order_by(StaffAssignment.role, User.full_name)
    )
    return [(assignment, user) for assignment, user in result.all()]


async def get_staff_assignment(
    db: AsyncSession, event_id: UUID, user_id: UUID
) -> StaffAssignment | None:
    result = await db.execute(
        select(StaffAssignment).where(
            StaffAssignment.event_id == event_id, StaffAssignment.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def create_staff_assignment(
    db: AsyncSession, event_id: UUID, user_id: UUID, role: StaffRole
) -> StaffAssignment:
    assignment = StaffAssignment(event_id=event_id, user_id=user_id, role=role)
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def delete_staff_assignment(
    db: AsyncSession, assignment: StaffAssignment
) -> None:
    await db.delete(assignment)
    await db.commit()


async def get_ticket_holder_ids(db: AsyncSession, event_id: UUID) -> list[UUID]:
    """Buyers with a confirmed order for the event."""
    result = await db.execute(
        select(Order.user_id)
        .where(Order.event_id == event_id, Order.status == OrderStatus.CONFIRMED)
        .distinct()
    )
    return list(result.scalars().all())
