"""Checkout (SRS 4.4, 4.6).

Flow: ``create_order`` locks the ticket types, checks stock and holds the
places in a pending order. Free orders are confirmed and ticketed at once.
Paid orders wait for ``pay_order`` (simulated) before tickets are issued;
an unpaid hold expires after ``CHECKOUT_HOLD_MINUTES`` and the places go
back on sale. Failed or abandoned checkouts never create tickets.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.i18n import t as tr
from app.core.timezones import format_local
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.calendar.service import calendar_links
from app.modules.events import service as event_service
from app.modules.events.enums import EventLifecycle, EventStatus, SeatingType
from app.modules.events.models import Event
from app.modules.events.permissions import (
    ALL_STAFF_ROLES,
    MANAGE_ROLES,
    get_staff_role,
)
from app.modules.notifications.service import notify
from app.modules.orders import crud, tickets
from app.modules.orders import refunds as refunds_service
from app.modules.orders.enums import OrderStatus, PaymentStatus, TicketStatus
from app.modules.orders.models import Attendee, Order, OrderItem, Payment, Ticket
from app.modules.orders.schemas import (
    EventAttendeeResponse,
    EventRefundResponse,
    EventSalesSummary,
    OrderCreate,
    OrderItemResponse,
    OrderResponse,
    PaymentCreate,
    PaymentResponse,
    RefundResponse,
    TicketResponse,
)
from app.modules.platform.service import get_settings
from app.modules.promotions import pricing
from app.modules.promotions.models import PromoRedemption
from app.modules.seating import service as seating_service
from app.modules.seating.service import SeatInfo, seat_text
from app.modules.tickets import crud as tickets_crud
from app.modules.tickets.inventory import compute_sale_status
from app.modules.tickets.schemas import SaleStatus
from app.modules.users.models import User

_SALE_ERRORS = {
    SaleStatus.HIDDEN: "is not available",
    SaleStatus.SCHEDULED: "is not on sale yet",
    SaleStatus.ENDED: "is no longer on sale",
    SaleStatus.SOLD_OUT: "is sold out",
}


def _now() -> datetime:
    return datetime.now(UTC)


def processing_fee(amount_kzt: int) -> int:
    """Simulated processor charge, rounded to whole tenge."""
    return round(amount_kzt * settings.PROCESSING_FEE_PERCENT / 100)


# --- Responses --------------------------------------------------------------


def _order_response(order: Order, event: Event, buyer: User) -> OrderResponse:
    items = sorted(order.items, key=lambda i: i.ticket_type_name)
    names = {item.id: item.ticket_type_name for item in order.items}
    tickets = [ticket for item in order.items for ticket in item.tickets]
    tickets.sort(key=lambda t: (t.attendee.position, t.created_at))
    return OrderResponse(
        id=order.id,
        event_id=order.event_id,
        event_title=event.title,
        event_start_at=event.start_at,
        event_timezone=event.timezone,
        user_id=order.user_id,
        buyer_name=buyer.full_name,
        buyer_email=buyer.email,
        status=_effective_status(order),
        subtotal_kzt=order.subtotal_kzt,
        discount_kzt=order.discount_kzt,
        promo_code=order.promo_code,
        total_kzt=order.total_kzt,
        expires_at=order.expires_at,
        confirmed_at=order.confirmed_at,
        cancelled_at=order.cancelled_at,
        created_at=order.created_at,
        items=[
            OrderItemResponse(
                id=item.id,
                ticket_type_id=item.ticket_type_id,
                ticket_type_name=item.ticket_type_name,
                unit_price_kzt=item.unit_price_kzt,
                quantity=item.quantity,
                subtotal_kzt=item.unit_price_kzt * item.quantity,
                seats=item.seats,
            )
            for item in items
        ],
        tickets=[
            TicketResponse(
                id=ticket.id,
                order_item_id=ticket.order_item_id,
                ticket_type_name=names[ticket.order_item_id],
                attendee_name=ticket.attendee.name,
                attendee_email=ticket.attendee.email,
                status=ticket.status,
                created_at=ticket.created_at,
                seat=seat_text(ticket),
            )
            for ticket in tickets
        ],
        payments=[
            PaymentResponse.model_validate(payment, from_attributes=True)
            for payment in order.payments
        ],
        refund=RefundResponse.model_validate(order.refund) if order.refund else None,
        calendar_links=calendar_links(event),
    )


async def _respond(db: AsyncSession, order_id: UUID) -> OrderResponse:
    order = await _reload(db, order_id)
    event = (await crud.get_events(db, {order.event_id}))[order.event_id]
    buyer = (await crud.get_users(db, {order.user_id}))[order.user_id]
    return _order_response(order, event, buyer)


async def _respond_many(db: AsyncSession, orders: list[Order]) -> list[OrderResponse]:
    events = await crud.get_events(db, {o.event_id for o in orders})
    users = await crud.get_users(db, {o.user_id for o in orders})
    return [_order_response(o, events[o.event_id], users[o.user_id]) for o in orders]


async def _reload(db: AsyncSession, order_id: UUID) -> Order:
    """Fetch the order with its items, tickets and payments freshly loaded."""
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


# --- Expiry -----------------------------------------------------------------


def _is_expired(order: Order) -> bool:
    return (
        order.status == OrderStatus.PENDING
        and order.expires_at is not None
        and order.expires_at <= _now()
    )


def _effective_status(order: Order) -> OrderStatus:
    """Holds are released lazily; a lapsed pending order already reads expired."""
    return OrderStatus.EXPIRED if _is_expired(order) else OrderStatus(order.status)


# --- Checkout ---------------------------------------------------------------


def _ensure_event_on_sale(event: Event) -> None:
    if event.is_suspended:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This event is suspended by the platform"
        )
    if event.status != EventStatus.PUBLISHED or event.lifecycle not in (
        EventLifecycle.UPCOMING,
        EventLifecycle.ACTIVE,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This event is not accepting registrations"
        )


def _ensure_paid_sales_open(event: Event) -> None:
    if event.paid_sales_suspended_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Paid sales for this event are suspended by the platform",
        )
    if event.paid_sales_activated_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Paid tickets for this event are not on sale yet",
        )


async def create_order(
    db: AsyncSession,
    event_id: UUID,
    actor: User,
    data_in: OrderCreate,
    background: BackgroundTasks,
) -> OrderResponse:
    event = await event_service.get_visible_event(db, event_id, actor)
    _ensure_event_on_sale(event)
    if not (await get_settings(db)).bookings_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "New bookings are paused across BiletFlow; please try again later",
        )
    await crud.lock_checkout(db, event.id, actor.id)
    if await crud.has_active_hold(db, event.id, actor.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You already have a checkout in progress for this event; "
            "pay for it or cancel it first",
        )

    # One slot per ticket: (ticket type id, seat or None), in request order
    seats: list[SeatInfo] = []
    if event.seating_type == SeatingType.ASSIGNED:
        if not data_in.seat_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Choose seats on the seat map (seat_ids)"
            )
        seats = await seating_service.resolve_seats(db, event, data_in.seat_ids)
        by_category = {
            t.seat_category: t.id
            for t in await tickets_crud.get_by_event(db, event.id, include_hidden=True)
            if t.seat_category
        }
        if any(seat.category not in by_category for seat in seats):
            raise HTTPException(status.HTTP_409_CONFLICT, "That seat is not on sale")
        slots = [(by_category[seat.category], seat) for seat in seats]
    else:
        if data_in.seat_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This event has general admission, not seats",
            )
        slots = [
            (item.ticket_type_id, None)
            for item in data_in.items
            for _ in range(item.quantity)
        ]
    requested: dict[UUID, int] = {}
    for ticket_type_id, _ in slots:
        requested[ticket_type_id] = requested.get(ticket_type_id, 0) + 1
    locked = await crud.lock_ticket_types(db, event.id, list(requested))
    if len(locked) != len(requested):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ticket type not found for this event"
        )

    # Counted after the lock, so no other checkout can change them meanwhile
    inventory = await tickets_crud.get_inventory(db, list(requested))
    now = _now()
    for ticket_type in locked:
        quantity = requested[ticket_type.id]
        available = inventory[ticket_type.id].available(ticket_type.quantity)
        sale = compute_sale_status(ticket_type, event, available, now)
        if sale != SaleStatus.ON_SALE:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{ticket_type.name} {_SALE_ERRORS[sale]}"
            )
        if quantity > ticket_type.max_per_order:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"At most {ticket_type.max_per_order} × {ticket_type.name} per order",
            )
        if quantity > available:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Only {available} × {ticket_type.name} left",
            )

    subtotal = sum(t.price_kzt * requested[t.id] for t in locked)
    if subtotal > 0:
        # Paid tickets need activated sales, even when a code makes them free
        _ensure_paid_sales_open(event)

    promo = None
    if data_in.promo_code:
        try:
            promo = await pricing.apply_code(
                db,
                event.id,
                pricing.lines_for(locked, requested),
                data_in.promo_code,
                lock=True,
            )
        except pricing.PromoError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    discount = promo.discount_kzt if promo else 0
    total = subtotal - discount

    order = Order(
        user_id=actor.id,
        event_id=event.id,
        status=OrderStatus.PENDING,
        subtotal_kzt=subtotal,
        discount_kzt=discount,
        total_kzt=total,
        campaign_id=promo.campaign.id if promo else None,
        promo_code=promo.code.code if promo else None,
        expires_at=now + timedelta(minutes=settings.CHECKOUT_HOLD_MINUTES),
    )
    db.add(order)
    await db.flush()
    if promo:
        # Counts toward the limit while the order holds places or is paid
        db.add(
            PromoRedemption(
                campaign_id=promo.campaign.id,
                promo_code_id=promo.code.id,
                order_id=order.id,
                user_id=actor.id,
                discount_kzt=discount,
            )
        )

    if seats:
        # All or nothing; a seat another live order holds gives 409
        await seating_service.hold_seats(db, event.id, order.id, seats)

    # One order line per ticket type, one attendee per ticket (slot order)
    people = data_in.attendees
    by_id = {t.id: t for t in locked}
    items: dict[UUID, OrderItem] = {}
    for ticket_type_id in requested:
        ticket_type = by_id[ticket_type_id]
        line_seats = [s.label for t, s in slots if t == ticket_type_id and s]
        items[ticket_type_id] = OrderItem(
            order_id=order.id,
            ticket_type_id=ticket_type.id,
            ticket_type_name=ticket_type.name,
            unit_price_kzt=ticket_type.price_kzt,
            quantity=requested[ticket_type_id],
            seats=line_seats or None,
        )
        db.add(items[ticket_type_id])
    await db.flush()
    position = 0
    for ticket_type_id, seat in slots:
        person = people[position] if people else None
        db.add(
            Attendee(
                order_id=order.id,
                order_item_id=items[ticket_type_id].id,
                position=position,
                name=person.name if person else actor.full_name,
                email=str(person.email) if person else actor.email,
                phone=person.phone if person else None,
                seat_id=seat.id if seat else None,
            )
        )
        position += 1
    await db.flush()

    if total == 0:
        # Free registration: no payment step (SRS 4.4)
        await _confirm(db, order)
        _log_order(
            db,
            actor,
            AuditAction.ORDER_CONFIRMED,
            order,
            f"Free registration for {position} ticket(s)",
        )
    await db.commit()

    response = await _respond(db, order.id)
    if response.status == OrderStatus.CONFIRMED:
        await _queue_confirmation(db, response, background)
    return response


async def _confirm(db: AsyncSession, order: Order) -> None:
    """Mark the order paid and issue one ticket per attendee. No commit."""
    attendees = (
        await db.execute(
            select(Attendee)
            .where(Attendee.order_id == order.id)
            .order_by(Attendee.position)
        )
    ).scalars()
    attendees = list(attendees)
    labels = await seating_service.seat_labels(
        db, [a.seat_id for a in attendees if a.seat_id]
    )
    for attendee in attendees:
        seat = labels.get(attendee.seat_id) if attendee.seat_id else None
        db.add(
            Ticket(
                order_item_id=attendee.order_item_id,
                attendee_id=attendee.id,
                status=TicketStatus.VALID,
                # Copied, so the ticket shows its seat on its own (SRS 4.3.1)
                seat_id=seat.id if seat else None,
                seat_section=seat.section if seat else None,
                seat_row=seat.row if seat else None,
                seat_number=seat.number if seat else None,
            )
        )
    order.status = OrderStatus.CONFIRMED
    order.confirmed_at = _now()
    order.expires_at = None


async def _get_own_pending_order(
    db: AsyncSession, order_id: UUID, actor: User
) -> Order:
    order = await crud.lock_order(db, order_id)
    if order is None or order.user_id != actor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if _is_expired(order):
        order.status = OrderStatus.EXPIRED
        await db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Your hold expired and the places were released; start again",
        )
    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"This order is already {order.status}"
        )
    return order


async def pay_order(
    db: AsyncSession,
    order_id: UUID,
    actor: User,
    data_in: PaymentCreate,
    background: BackgroundTasks,
) -> OrderResponse:
    """Simulated payment. Success confirms and tickets the order; failure
    records the attempt and keeps the hold so the buyer can retry."""
    order = await _get_own_pending_order(db, order_id, actor)
    event = (await crud.get_events(db, {order.event_id}))[order.event_id]
    _ensure_event_on_sale(event)
    # A suspension between checkout and payment stops the payment too
    _ensure_paid_sales_open(event)
    if data_in.outcome == "failure":
        reason = data_in.failure_reason or "Payment declined (simulated)"
        db.add(
            Payment(
                order_id=order.id,
                status=PaymentStatus.FAILED,
                amount_kzt=order.total_kzt,
                processing_fee_kzt=0,
                failure_reason=reason,
            )
        )
        _log_order(
            db,
            actor,
            AuditAction.PAYMENT_FAILED,
            order,
            f"Payment of {order.total_kzt} KZT failed (simulated): {reason}",
            AuditEntity.PAYMENT,
        )
        await db.commit()
        response = await _respond(db, order.id)
        await _queue_payment_failed(db, response, background)
        return response

    db.add(
        Payment(
            order_id=order.id,
            status=PaymentStatus.SUCCEEDED,
            amount_kzt=order.total_kzt,
            processing_fee_kzt=processing_fee(order.total_kzt),
        )
    )
    _log_order(
        db,
        actor,
        AuditAction.PAYMENT_SUCCEEDED,
        order,
        f"Paid {order.total_kzt} KZT (simulated)",
        AuditEntity.PAYMENT,
    )
    await _confirm(db, order)
    _log_order(db, actor, AuditAction.ORDER_CONFIRMED, order, "Order confirmed")
    await db.commit()
    response = await _respond(db, order.id)
    await _queue_confirmation(db, response, background)
    return response


async def cancel_pending_order(
    db: AsyncSession, order_id: UUID, actor: User
) -> OrderResponse:
    """Abandon checkout and release the held places."""
    order = await _get_own_pending_order(db, order_id, actor)
    order.status = OrderStatus.CANCELLED
    order.cancelled_at = _now()
    order.expires_at = None
    _log_order(db, actor, AuditAction.ORDER_CANCELLED, order, "Checkout abandoned")
    await db.commit()
    return await _respond(db, order.id)


# --- Reading orders ---------------------------------------------------------


async def get_order(db: AsyncSession, order_id: UUID, actor: User) -> OrderResponse:
    order = await crud.get_by_id(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.user_id != actor.id and not actor.is_platform_admin:
        role = await get_staff_role(db, order.event_id, actor.id)
        if role not in MANAGE_ROLES:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return await _respond(db, order.id)


async def get_my_orders(db: AsyncSession, actor: User) -> list[OrderResponse]:
    return await _respond_many(db, await crud.get_for_user(db, actor.id))


async def get_event_orders(
    db: AsyncSession, event_id: UUID, actor: User, order_status: OrderStatus | None
) -> list[OrderResponse]:
    await event_service.get_managed_event(db, event_id, actor)
    if order_status == OrderStatus.EXPIRED:
        # Lapsed holds are still stored as pending until someone touches them
        pending = await crud.get_for_event(db, event_id, OrderStatus.PENDING)
        stored = await crud.get_for_event(db, event_id, OrderStatus.EXPIRED)
        orders = [o for o in pending if _is_expired(o)] + stored
    elif order_status == OrderStatus.PENDING:
        pending = await crud.get_for_event(db, event_id, OrderStatus.PENDING)
        orders = [o for o in pending if not _is_expired(o)]
    else:
        orders = await crud.get_for_event(db, event_id, order_status)
    return await _respond_many(db, orders)


async def get_event_attendees(
    db: AsyncSession, event_id: UUID, actor: User, q: str | None
) -> list[EventAttendeeResponse]:
    await event_service.get_managed_event(db, event_id, actor, allowed=ALL_STAFF_ROLES)
    rows = await crud.get_event_attendees(db, event_id, q)
    return [
        EventAttendeeResponse(
            ticket_id=ticket.id,
            order_id=item.order_id,
            attendee_name=attendee.name,
            attendee_email=attendee.email,
            ticket_type_name=item.ticket_type_name,
            status=ticket.status,
            issued_at=ticket.created_at,
            checked_in_at=ticket.checked_in_at,
            seat=seat_text(ticket),
        )
        for ticket, attendee, item in rows
    ]


async def get_event_sales(
    db: AsyncSession, event_id: UUID, actor: User
) -> EventSalesSummary:
    await event_service.get_managed_event(db, event_id, actor)
    figures = await crud.get_sales_figures(db, event_id)
    refunds = await refunds_service.total_refunded(db, event_id)
    return EventSalesSummary(
        event_id=event_id,
        confirmed_orders=figures["confirmed_orders"],
        tickets_sold=figures["tickets_sold"],
        gross_sales_kzt=figures["gross"],
        processing_fees_kzt=figures["fees"],
        refunds_kzt=refunds,
        estimated_payout_kzt=figures["gross"] - figures["fees"] - refunds,
    )


# --- Emails -----------------------------------------------------------------


def _hold_until(order: OrderResponse) -> str:
    if order.expires_at is None:
        return "the hold ends"
    return format_local(order.expires_at, order.event_timezone, "%H:%M")


def _order_link(order_id: UUID) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/orders/{order_id}"


async def _queue_confirmation(
    db: AsyncSession, order: OrderResponse, background: BackgroundTasks
) -> None:
    """Confirmation with the PDF tickets attached (SRS 4.4, 4.7, 4.10), in the
    buyer's language, plus an in-app notification. Runs after the commit."""
    buyer = (await crud.get_users(db, {order.user_id}))[order.user_id]
    language = buyer.preferred_language
    lines = "\n".join(
        f"- {ticket.ticket_type_name}: {ticket.attendee_name}"
        for ticket in order.tickets
    )
    if order.total_kzt == 0:
        total = tr("ticket_summary.free", language)
    else:
        total = tr("ticket_summary.paid", language, amount=order.total_kzt)
    if order.discount_kzt:
        total += tr(
            "ticket_summary.discount",
            language,
            discount=order.discount_kzt,
            code=order.promo_code,
        )
    delivery = await tickets.build_delivery(
        db,
        order.id,
        buyer,
        _order_link(order.id),
        tr("ticket_summary.body", language, lines=lines, total=total),
    )
    background.add_task(tickets.deliver_tickets, delivery)
    # The email above carries the PDFs; this is the in-app copy
    notify(
        db,
        background,
        [buyer],
        "order_confirmed",
        link=f"/orders/{order.id}",
        event_id=order.event_id,
        send_email=False,
        event=order.event_title,
    )
    await db.commit()


async def _queue_payment_failed(
    db: AsyncSession, order: OrderResponse, background: BackgroundTasks
) -> None:
    buyer = (await crud.get_users(db, {order.user_id}))[order.user_id]
    reason = order.payments[-1].failure_reason if order.payments else None
    notify(
        db,
        background,
        [buyer],
        "payment_failed",
        link=f"/orders/{order.id}",
        event_id=order.event_id,
        event=order.event_title,
        reason=reason or "—",
        until=_hold_until(order),
    )
    await db.commit()


def _log_order(
    db: AsyncSession,
    actor: User,
    action: AuditAction,
    order: Order,
    description: str,
    entity_type: AuditEntity = AuditEntity.ORDER,
) -> None:
    audit.record(
        db,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=order.id,
        event_id=order.event_id,
        description=description,
        details={"order_id": order.id, "total_kzt": order.total_kzt},
    )


async def respond(db: AsyncSession, order_id: UUID) -> OrderResponse:
    """Public wrapper used by the refund routes."""
    return await _respond(db, order_id)


async def get_event_refunds(
    db: AsyncSession, event_id: UUID, actor: User
) -> list[EventRefundResponse]:
    await event_service.get_managed_event(db, event_id, actor)
    return [
        EventRefundResponse.model_validate(
            {**RefundResponse.model_validate(refund).model_dump(), "buyer_name": name}
        )
        for refund, name in await refunds_service.get_event_refunds(db, event_id)
    ]
