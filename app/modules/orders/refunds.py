"""Refunds and cancellations (SRS 4.9, UC5).

- Organizers (the event owner) and platform admins can fully refund a paid
  order. Refunds are simulated and complete at once.
- Organizers (owner or manager) can cancel a free registration; the attendee
  who booked it can cancel it too.
- Cancelling an event refunds every paid order first.

Refunded and cancelled tickets become invalid and their places free up.
Every refund and cancellation is written to the audit log.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.events.enums import StaffRole
from app.modules.events.models import Event
from app.modules.events.permissions import MANAGE_ROLES, get_staff_role
from app.modules.notifications.service import notify
from app.modules.orders.enums import (
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    TicketStatus,
)
from app.modules.orders.models import Order, OrderItem, Refund, Ticket
from app.modules.users.models import User

USABLE = (TicketStatus.VALID, TicketStatus.CHECKED_IN)


@dataclass(frozen=True)
class RefundNotice:
    """Who to tell about a refund; sent with ``notify_refund``."""

    buyer: User
    order_id: UUID
    event_id: UUID
    event_title: str
    amount_kzt: int
    reason: str


async def _tickets(db: AsyncSession, order_id: UUID) -> list[Ticket]:
    result = await db.execute(
        select(Ticket)
        .join(OrderItem, OrderItem.id == Ticket.order_item_id)
        .where(OrderItem.order_id == order_id)
        .with_for_update(of=Ticket)
    )
    return list(result.scalars().all())


def _succeeded_payment_id(order: Order) -> UUID | None:
    paid = [p for p in order.payments if p.status == PaymentStatus.SUCCEEDED]
    return paid[-1].id if paid else None


async def refund_order_locked(
    db: AsyncSession,
    order: Order,
    actor: User,
    reason: str,
    *,
    allow_checked_in: bool = False,
) -> Refund:
    """Refund a locked, confirmed paid order. Adds rows; the caller commits."""
    if order.status != OrderStatus.CONFIRMED or order.total_kzt <= 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only confirmed paid orders can be refunded"
        )
    tickets = await _tickets(db, order.id)
    if not allow_checked_in and any(
        t.status == TicketStatus.CHECKED_IN for t in tickets
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Some tickets in this order were already used; undo the check-in first",
        )
    for ticket in tickets:
        if ticket.status in USABLE:
            ticket.status = TicketStatus.REFUNDED
    order.status = OrderStatus.REFUNDED
    refund = Refund(
        order_id=order.id,
        payment_id=_succeeded_payment_id(order),
        event_id=order.event_id,
        amount_kzt=order.total_kzt,
        status=RefundStatus.COMPLETED,
        reason=reason,
        initiated_by_user_id=actor.id,
        initiated_by_name=actor.full_name,
    )
    db.add(refund)
    audit.record(
        db,
        actor=actor,
        action=AuditAction.ORDER_REFUNDED,
        entity_type=AuditEntity.ORDER,
        entity_id=order.id,
        event_id=order.event_id,
        description=f"Refunded {order.total_kzt} KZT (simulated): {reason}",
        details={"order_id": order.id, "amount_kzt": order.total_kzt},
    )
    return refund


async def _lock_order(db: AsyncSession, order_id: UUID) -> Order:
    order = (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update(of=Order)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


async def _event(db: AsyncSession, event_id: UUID) -> Event:
    event = await db.get(Event, event_id)
    assert event is not None
    return event


async def _buyer(db: AsyncSession, order: Order) -> User:
    buyer = await db.get(User, order.user_id)
    assert buyer is not None
    return buyer


def notify_refund(
    db: AsyncSession, background: BackgroundTasks, notice: RefundNotice
) -> None:
    """In-app and email "refund completed" (SRS 4.10). Before the commit."""
    notify(
        db,
        background,
        [notice.buyer],
        "refund_completed",
        link=f"/orders/{notice.order_id}",
        event_id=notice.event_id,
        event=notice.event_title,
        amount=notice.amount_kzt,
        reason=notice.reason,
    )


async def refund_order(
    db: AsyncSession,
    order_id: UUID,
    actor: User,
    reason: str,
    background: BackgroundTasks,
) -> Order:
    """Full refund, initiated by the event owner or a platform admin (money
    decisions are not delegated to managers)."""
    order = await _lock_order(db, order_id)
    role = await get_staff_role(db, order.event_id, actor.id)
    if role != StaffRole.OWNER and not actor.is_platform_admin:
        if order.user_id == actor.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Refunds are issued by the organizer; open a support request",
            )
        if role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the event owner can issue refunds"
        )
    await refund_order_locked(db, order, actor, reason)
    event = await _event(db, order.event_id)
    buyer = await _buyer(db, order)
    notify_refund(
        db,
        background,
        RefundNotice(buyer, order.id, event.id, event.title, order.total_kzt, reason),
    )
    await db.commit()
    return order


async def cancel_registration(
    db: AsyncSession,
    order_id: UUID,
    actor: User,
    reason: str | None,
    background: BackgroundTasks,
) -> Order:
    """Cancel a free registration: by its attendee, or the event's owner or
    a manager (SRS 4.9). Paid orders go through ``refund_order`` instead."""
    order = await _lock_order(db, order_id)
    is_buyer = order.user_id == actor.id
    role = await get_staff_role(db, order.event_id, actor.id)
    if not (is_buyer or role in MANAGE_ROLES or actor.is_platform_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.status != OrderStatus.CONFIRMED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"This order is already {order.status}"
        )
    if order.total_kzt > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Paid orders are cancelled through a refund"
        )
    tickets = await _tickets(db, order.id)
    if any(t.status == TicketStatus.CHECKED_IN for t in tickets):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A ticket in this registration was already used; undo the check-in first",
        )
    for ticket in tickets:
        if ticket.status == TicketStatus.VALID:
            ticket.status = TicketStatus.CANCELLED
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
    who = "the attendee" if is_buyer else actor.full_name
    reason_text = reason or "No reason given"
    audit.record(
        db,
        actor=actor,
        action=AuditAction.REGISTRATION_CANCELLED,
        entity_type=AuditEntity.ORDER,
        entity_id=order.id,
        event_id=order.event_id,
        description=f"Free registration cancelled by {who}: {reason_text}",
        details={"order_id": order.id, "tickets": len(tickets)},
    )
    event = await _event(db, order.event_id)
    buyer = await _buyer(db, order)
    if not is_buyer:
        notify(
            db,
            background,
            [buyer],
            "registration_cancelled",
            link=f"/orders/{order.id}",
            event_id=event.id,
            event=event.title,
            reason=reason_text,
        )
    await db.commit()
    await db.refresh(order)
    return order


async def refund_all_for_event(
    db: AsyncSession, event: Event, actor: User, reason: str
) -> list[RefundNotice]:
    """Refund every paid order of an event being cancelled. The caller commits.

    Used tickets are refunded too: the event itself is not happening.
    """
    orders = (
        (
            await db.execute(
                select(Order)
                .where(
                    Order.event_id == event.id,
                    Order.status == OrderStatus.CONFIRMED,
                    Order.total_kzt > 0,
                )
                .with_for_update(of=Order)
            )
        )
        .scalars()
        .all()
    )
    notices = []
    for order in orders:
        await refund_order_locked(db, order, actor, reason, allow_checked_in=True)
        buyer = await _buyer(db, order)
        notices.append(
            RefundNotice(
                buyer, order.id, event.id, event.title, order.total_kzt, reason
            )
        )
    return notices


async def get_event_refunds(
    db: AsyncSession, event_id: UUID
) -> list[tuple[Refund, str]]:
    """Refunds with the buyer's name, newest first. Callers authorize."""
    result = await db.execute(
        select(Refund, User.full_name)
        .join(Order, Order.id == Refund.order_id)
        .join(User, User.id == Order.user_id)
        .where(Refund.event_id == event_id)
        .order_by(Refund.created_at.desc())
    )
    return [(refund, name) for refund, name in result.all()]


async def total_refunded(db: AsyncSession, event_id: UUID) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(Refund.amount_kzt), 0)).where(
            Refund.event_id == event_id
        )
    )
    return int(total or 0)
