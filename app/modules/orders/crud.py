"""Order queries. Functions here never commit; the service owns the transaction."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event
from app.modules.orders.enums import OrderStatus, PaymentStatus, TicketStatus
from app.modules.orders.models import Attendee, Order, OrderItem, Payment, Ticket
from app.modules.tickets.crud import active_hold
from app.modules.tickets.models import TicketType
from app.modules.users.models import User


async def lock_ticket_types(
    db: AsyncSession, event_id: UUID, ids: list[UUID]
) -> list[TicketType]:
    """Lock the rows until commit so concurrent checkouts queue up.

    Rows are locked in id order so two orders for the same types can never
    deadlock each other.
    """
    result = await db.execute(
        select(TicketType)
        .where(TicketType.id.in_(ids), TicketType.event_id == event_id)
        .order_by(TicketType.id)
        .with_for_update()
    )
    return list(result.scalars().all())


async def lock_order(db: AsyncSession, order_id: UUID) -> Order | None:
    result = await db.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, order_id: UUID) -> Order | None:
    result = await db.execute(select(Order).where(Order.id == order_id))
    return result.scalar_one_or_none()


async def lock_checkout(db: AsyncSession, event_id: UUID, user_id: UUID) -> None:
    """Serialize one person's checkouts for one event until commit, so two
    fast clicks cannot both pass the "checkout in progress" check."""
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"checkout:{event_id}:{user_id}", 0)
            )
        )
    )


async def has_active_hold(db: AsyncSession, event_id: UUID, user_id: UUID) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(Order)
        .where(Order.event_id == event_id, Order.user_id == user_id, active_hold())
    )
    return int(result.scalar_one()) > 0


async def get_for_user(db: AsyncSession, user_id: UUID) -> list[Order]:
    result = await db.execute(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())


async def get_for_event(
    db: AsyncSession, event_id: UUID, status: OrderStatus | None = None
) -> list[Order]:
    query = select(Order).where(Order.event_id == event_id)
    if status:
        query = query.where(Order.status == status)
    result = await db.execute(query.order_by(Order.created_at.desc()))
    return list(result.scalars().all())


async def get_events(db: AsyncSession, ids: set[UUID]) -> dict[UUID, Event]:
    if not ids:
        return {}
    result = await db.execute(select(Event).where(Event.id.in_(ids)))
    return {event.id: event for event in result.scalars().all()}


async def get_users(db: AsyncSession, ids: set[UUID]) -> dict[UUID, User]:
    if not ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(ids)))
    return {user.id: user for user in result.scalars().all()}


async def get_event_attendees(
    db: AsyncSession, event_id: UUID, q: str | None = None
) -> list[tuple[Ticket, Attendee, OrderItem]]:
    query = (
        select(Ticket, Attendee, OrderItem)
        .join(Attendee, Attendee.id == Ticket.attendee_id)
        .join(OrderItem, OrderItem.id == Ticket.order_item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.event_id == event_id)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(Attendee.name.ilike(pattern), Attendee.email.ilike(pattern))
        )
    result = await db.execute(query.order_by(Attendee.name, Ticket.created_at))
    return [(ticket, attendee, item) for ticket, attendee, item in result.all()]


async def get_sales_figures(db: AsyncSession, event_id: UUID) -> dict[str, int]:
    paid = await db.execute(
        select(
            func.coalesce(func.sum(Payment.amount_kzt), 0),
            func.coalesce(func.sum(Payment.processing_fee_kzt), 0),
        )
        .join(Order, Order.id == Payment.order_id)
        .where(Order.event_id == event_id, Payment.status == PaymentStatus.SUCCEEDED)
    )
    gross, fees = paid.one()
    confirmed = await db.execute(
        select(func.count())
        .select_from(Order)
        .where(Order.event_id == event_id, Order.status == OrderStatus.CONFIRMED)
    )
    sold = await db.execute(
        select(func.count())
        .select_from(Ticket)
        .join(OrderItem, OrderItem.id == Ticket.order_item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.event_id == event_id,
            Ticket.status.in_((TicketStatus.VALID, TicketStatus.CHECKED_IN)),
        )
    )
    return {
        "gross": int(gross),
        "fees": int(fees),
        "confirmed_orders": int(confirmed.scalar_one()),
        "tickets_sold": int(sold.scalar_one()),
    }
