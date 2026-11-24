"""Issued tickets: the holder's view, PDFs and email delivery (SRS 4.7)."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email
from app.core.i18n import t as tr
from app.core.security import make_ticket_qr_payload
from app.modules.events.models import Event
from app.modules.orders.enums import TicketStatus
from app.modules.orders.models import Attendee, Order, OrderItem, Ticket
from app.modules.orders.schemas import (
    TicketDetailResponse,
    TicketEventInfo,
    TicketSeat,
)
from app.modules.orders.ticket_pdf import TicketPrint, render_tickets_pdf
from app.modules.seating.service import seat_text
from app.modules.users.models import User

USABLE = (TicketStatus.VALID, TicketStatus.CHECKED_IN)

_Row = tuple[Ticket, Attendee, OrderItem, Order, Event]


def _base_query():
    return (
        select(Ticket, Attendee, OrderItem, Order, Event)
        .join(Attendee, Attendee.id == Ticket.attendee_id)
        .join(OrderItem, OrderItem.id == Ticket.order_item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Event, Event.id == Order.event_id)
    )


def _held_by(user: User):
    """Tickets the user bought, or that were issued in their name."""
    return or_(Order.user_id == user.id, func.lower(Attendee.email) == user.email)


def _qr(ticket: Ticket) -> str | None:
    return make_ticket_qr_payload(ticket.qr_secret) if ticket.status in USABLE else None


def _detail(row: _Row) -> TicketDetailResponse:
    ticket, attendee, item, order, event = row
    return TicketDetailResponse(
        id=ticket.id,
        order_id=order.id,
        status=ticket.status,
        event=TicketEventInfo.model_validate(event, from_attributes=True),
        ticket_type_name=item.ticket_type_name,
        attendee_name=attendee.name,
        attendee_email=attendee.email,
        seat=TicketSeat(
            section=ticket.seat_section, row=ticket.seat_row, number=ticket.seat_number
        )
        if ticket.seat_number
        else None,
        qr_payload=_qr(ticket),
        issued_at=ticket.created_at,
    )


def _print(row: _Row) -> TicketPrint:
    ticket, attendee, item, _, event = row
    return TicketPrint(
        ticket_id=str(ticket.id),
        event_title=event.title,
        start_at=event.start_at,
        end_at=event.end_at,
        timezone=event.timezone,
        venue_name=event.venue_name,
        venue_address=event.venue_address,
        city=event.city,
        ticket_type_name=item.ticket_type_name,
        attendee_name=attendee.name,
        status=ticket.status,
        qr_payload=_qr(ticket),
        seat=seat_text(ticket),
    )


async def _get_row(db: AsyncSession, ticket_id: UUID, actor: User) -> _Row:
    query = _base_query().where(Ticket.id == ticket_id)
    if not actor.is_platform_admin:
        query = query.where(_held_by(actor))
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return tuple(row)  # type: ignore[return-value]


async def get_my_tickets(db: AsyncSession, actor: User) -> list[TicketDetailResponse]:
    result = await db.execute(
        _base_query()
        .where(_held_by(actor))
        .order_by(Event.start_at.desc(), Attendee.position)
    )
    return [_detail(tuple(row)) for row in result.all()]  # type: ignore[arg-type]


async def get_ticket(
    db: AsyncSession, ticket_id: UUID, actor: User
) -> TicketDetailResponse:
    return _detail(await _get_row(db, ticket_id, actor))


async def get_ticket_pdf(db: AsyncSession, ticket_id: UUID, actor: User) -> bytes:
    return render_tickets_pdf([_print(await _get_row(db, ticket_id, actor))])


async def _order_rows(db: AsyncSession, order_id: UUID) -> list[_Row]:
    result = await db.execute(
        _base_query().where(Order.id == order_id).order_by(Attendee.position)
    )
    return [tuple(row) for row in result.all()]  # type: ignore[misc]


async def get_order_pdf(db: AsyncSession, order_id: UUID, actor: User) -> bytes:
    """All tickets of an order in one PDF. The buyer or a platform admin."""
    order = await db.get(Order, order_id)
    if order is None or (order.user_id != actor.id and not actor.is_platform_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    rows = await _order_rows(db, order_id)
    if not rows:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Tickets are issued once the order is paid"
        )
    return render_tickets_pdf([_print(row) for row in rows])


# --- Delivery -----------------------------------------------------------------


@dataclass(frozen=True)
class TicketDelivery:
    """What the email task needs; plain data, no database session."""

    buyer_email: str
    buyer_name: str
    # Attendees without an account get the buyer's language
    language: str
    event_title: str
    order_link: str
    summary: str
    tickets: list[tuple[str, str, TicketPrint]]  # (attendee email, name, print)


async def build_delivery(
    db: AsyncSession, order_id: UUID, buyer: User, order_link: str, summary: str
) -> TicketDelivery:
    rows = await _order_rows(db, order_id)
    return TicketDelivery(
        buyer_email=buyer.email,
        buyer_name=buyer.full_name,
        language=buyer.preferred_language,
        event_title=rows[0][4].title if rows else "",
        order_link=order_link,
        summary=summary,
        tickets=[(row[1].email.lower(), row[1].name, _print(row)) for row in rows],
    )


def _filename(title: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    return f"biletflow-{safe[:40] or 'tickets'}.pdf"


def deliver_tickets(delivery: TicketDelivery) -> None:
    """Email the buyer every ticket, and each other attendee their own.

    Runs as a background task after the response is sent.
    """
    prints = [p for _, _, p in delivery.tickets]
    language = delivery.language
    email.send_email(
        delivery.buyer_email,
        tr("order_confirmed.title", language, event=delivery.event_title),
        tr(
            "order_confirmed.body",
            language,
            name=delivery.buyer_name,
            event=delivery.event_title,
            summary=delivery.summary,
            link=delivery.order_link,
        ),
        [
            (
                _filename(delivery.event_title),
                render_tickets_pdf(prints),
                "application/pdf",
            )
        ],
    )
    others: dict[str, list[tuple[str, TicketPrint]]] = {}
    for address, name, ticket in delivery.tickets:
        if address != delivery.buyer_email.lower():
            others.setdefault(address, []).append((name, ticket))
    for address, held in others.items():
        email.send_email(
            address,
            tr("guest_ticket.title", language, event=delivery.event_title),
            tr(
                "guest_ticket.body",
                language,
                name=held[0][0],
                buyer=delivery.buyer_name,
                event=delivery.event_title,
            ),
            [
                (
                    _filename(delivery.event_title),
                    render_tickets_pdf([t for _, t in held]),
                    "application/pdf",
                )
            ],
        )
