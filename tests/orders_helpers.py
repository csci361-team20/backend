"""Insert orders straight into the database.

Orders have no API until phase 3; these helpers let inventory tests set up
pending, paid and checked-in tickets directly.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.modules.events.models import Event
from app.modules.orders.enums import OrderStatus, TicketStatus
from app.modules.orders.models import Attendee, Order, OrderItem, Ticket


async def insert_order(
    event_id: str | UUID,
    user_id: UUID,
    ticket_type_id: str | UUID,
    *,
    quantity: int,
    status: OrderStatus = OrderStatus.PENDING,
    ticket_statuses: list[TicketStatus] | None = None,
    unit_price_kzt: int = 0,
) -> UUID:
    """One order with one item. ``ticket_statuses`` issues one ticket each."""
    async with AsyncSessionLocal() as session:
        order = Order(
            user_id=user_id,
            event_id=UUID(str(event_id)),
            status=status,
            total_kzt=unit_price_kzt * quantity,
        )
        session.add(order)
        await session.flush()
        item = OrderItem(
            order_id=order.id,
            ticket_type_id=UUID(str(ticket_type_id)),
            unit_price_kzt=unit_price_kzt,
            quantity=quantity,
        )
        attendee = Attendee(order_id=order.id, name="Dana Sarsen", email="d@x.kz")
        session.add_all([item, attendee])
        await session.flush()
        for ticket_status in ticket_statuses or []:
            session.add(
                Ticket(
                    order_item_id=item.id, attendee_id=attendee.id, status=ticket_status
                )
            )
        await session.commit()
        return order.id


async def activate_paid_sales(event_id: str | UUID) -> None:
    """Stand-in for the phase 5 activation flow."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Event)
            .where(Event.id == UUID(str(event_id)))
            .values(paid_sales_activated_at=datetime.now(UTC))
        )
        await session.commit()


async def expire_hold(order_id: str | UUID) -> None:
    """Move a pending order's hold into the past."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Order)
            .where(Order.id == UUID(str(order_id)))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
