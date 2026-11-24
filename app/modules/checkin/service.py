"""Ticket verification and check-in for the event-admin app (SRS 4.8, UC4).

Online only (offline sync is deferred by the SRS): every scan is checked
against the central database and recorded at once. The ticket row is locked
while it is being admitted, so two scanners can never let the same ticket
in twice.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import parse_ticket_qr_payload
from app.core.timezones import format_local
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.checkin.enums import (
    STAFF_UNDO_WINDOW_MINUTES,
    CheckInAction,
    CheckInMethod,
    ScanResult,
)
from app.modules.checkin.models import CheckInRecord
from app.modules.checkin.schemas import (
    CheckInRecordResponse,
    CheckInResult,
    CheckInStats,
    CheckInTicket,
)
from app.modules.events import service as event_service
from app.modules.events.enums import EventStatus, StaffRole
from app.modules.events.models import Event
from app.modules.events.permissions import ALL_STAFF_ROLES, get_staff_role
from app.modules.orders.enums import TicketStatus
from app.modules.orders.models import Attendee, Order, OrderItem, Ticket
from app.modules.seating.service import seat_text
from app.modules.users.models import User

_Row = tuple[Ticket, Attendee, OrderItem, Order]

_BY_STATUS = {
    TicketStatus.VALID: ScanResult.VALID,
    TicketStatus.CHECKED_IN: ScanResult.ALREADY_USED,
    TicketStatus.CANCELLED: ScanResult.CANCELLED,
    TicketStatus.REFUNDED: ScanResult.REFUNDED,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _query(lock: bool):
    query = (
        select(Ticket, Attendee, OrderItem, Order)
        .join(Attendee, Attendee.id == Ticket.attendee_id)
        .join(OrderItem, OrderItem.id == Ticket.order_item_id)
        .join(Order, Order.id == OrderItem.order_id)
    )
    # Lock only the ticket row: concurrent scans of it queue up here
    return query.with_for_update(of=Ticket) if lock else query


def _ticket(row: _Row) -> CheckInTicket:
    ticket, attendee, item, _ = row
    return CheckInTicket(
        id=ticket.id,
        attendee_name=attendee.name,
        ticket_type_name=item.ticket_type_name,
        status=ticket.status,
        checked_in_at=ticket.checked_in_at,
        checked_in_by_name=ticket.checked_in_by_name,
        seat=seat_text(ticket),
    )


def _message(result: ScanResult, row: _Row | None, event: Event) -> str:
    if result == ScanResult.VALID:
        return f"Valid ticket: {row[1].name}" if row else "Valid ticket"
    if result == ScanResult.ALREADY_USED and row:
        ticket = row[0]
        when = (
            format_local(ticket.checked_in_at, event.timezone, "%H:%M")
            if ticket.checked_in_at
            else "earlier"
        )
        by = f" by {ticket.checked_in_by_name}" if ticket.checked_in_by_name else ""
        return f"Already used: checked in at {when}{by}"
    return {
        ScanResult.CANCELLED: "Ticket cancelled: do not admit",
        ScanResult.REFUNDED: "Ticket refunded: do not admit",
        ScanResult.WRONG_EVENT: "This ticket is for a different event",
        ScanResult.INVALID: "Not a valid BiletFlow ticket",
    }.get(result, "Do not admit")


def _outcome(
    result: ScanResult, event: Event, row: _Row | None, admitted: bool = False
) -> CheckInResult:
    show_ticket = row is not None and result != ScanResult.WRONG_EVENT
    return CheckInResult(
        result=result,
        admitted=admitted,
        message=_message(result, row, event),
        ticket=_ticket(row) if show_ticket else None,
    )


async def _event_for_check_in(db: AsyncSession, event_id: UUID, actor: User) -> Event:
    event = await event_service.get_managed_event(
        db, event_id, actor, allowed=ALL_STAFF_ROLES
    )
    if event.status != EventStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Check-in is closed: the event is {event.status}"
        )
    return event


async def _find_by_payload(
    db: AsyncSession, event: Event, payload: str, lock: bool
) -> tuple[ScanResult, _Row | None, str | None]:
    """Classify a scanned code. Returns (result, row, invalid-reason)."""
    secret = parse_ticket_qr_payload(payload)
    if secret is None:
        if payload.strip().lower().startswith(("http://", "https://")):
            # Campaign QR codes open event pages; they never admit anyone
            return ScanResult.INVALID, None, "Promotional code, not a ticket"
        return ScanResult.INVALID, None, None
    row = (
        await db.execute(_query(lock).where(Ticket.qr_secret == secret))
    ).one_or_none()
    if row is None:
        return ScanResult.INVALID, None, None
    row = tuple(row)
    if row[3].event_id != event.id:
        return ScanResult.WRONG_EVENT, row, None  # type: ignore[return-value]
    return _BY_STATUS[TicketStatus(row[0].status)], row, None  # type: ignore[return-value]


async def _find_by_id(db: AsyncSession, event: Event, ticket_id: UUID) -> _Row:
    row = (
        await db.execute(_query(lock=True).where(Ticket.id == ticket_id))
    ).one_or_none()
    if row is None or row[3].event_id != event.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ticket not found for this event"
        )
    return tuple(row)  # type: ignore[return-value]


def _admit(
    db: AsyncSession, event: Event, row: _Row, actor: User, method: CheckInMethod
) -> None:
    ticket, attendee, _, _ = row
    now = _now()
    ticket.status = TicketStatus.CHECKED_IN
    ticket.checked_in_at = now
    ticket.checked_in_by_name = actor.full_name
    db.add(
        CheckInRecord(
            ticket_id=ticket.id,
            event_id=event.id,
            action=CheckInAction.CHECK_IN,
            method=method,
            performed_by_user_id=actor.id,
            performed_by_name=actor.full_name,
        )
    )
    audit.record(
        db,
        actor=actor,
        action=AuditAction.TICKET_CHECKED_IN,
        entity_type=AuditEntity.TICKET,
        entity_id=ticket.id,
        event_id=event.id,
        description=f"Checked in {attendee.name} ({method})",
        details={"method": method},
    )


# --- Scanning ---------------------------------------------------------------------


async def verify(
    db: AsyncSession, event_id: UUID, actor: User, payload: str
) -> CheckInResult:
    """Check a code without admitting anyone."""
    event = await _event_for_check_in(db, event_id, actor)
    result, row, reason = await _find_by_payload(db, event, payload, lock=False)
    outcome = _outcome(result, event, row)
    if reason:
        outcome.message = reason
    return outcome


async def scan(
    db: AsyncSession, event_id: UUID, actor: User, payload: str
) -> CheckInResult:
    """Verify and, if valid, admit in one step."""
    event = await _event_for_check_in(db, event_id, actor)
    result, row, reason = await _find_by_payload(db, event, payload, lock=True)
    if result != ScanResult.VALID or row is None:
        # Build the reply first: rolling back expires the loaded rows
        outcome = _outcome(result, event, row)
        if reason:
            outcome.message = reason
        await db.rollback()  # release the lock; nothing to write
        return outcome
    _admit(db, event, row, actor, CheckInMethod.SCAN)
    await db.commit()
    return _outcome(ScanResult.VALID, event, row, admitted=True)


async def check_in_manually(
    db: AsyncSession, event_id: UUID, ticket_id: UUID, actor: User
) -> CheckInResult:
    """Admit a ticket found through attendee search."""
    event = await _event_for_check_in(db, event_id, actor)
    row = await _find_by_id(db, event, ticket_id)
    result = _BY_STATUS[TicketStatus(row[0].status)]
    if result != ScanResult.VALID:
        outcome = _outcome(result, event, row)
        await db.rollback()
        return outcome
    _admit(db, event, row, actor, CheckInMethod.MANUAL)
    await db.commit()
    return _outcome(ScanResult.VALID, event, row, admitted=True)


async def undo(
    db: AsyncSession, event_id: UUID, ticket_id: UUID, actor: User, reason: str
) -> CheckInResult:
    """Reverse an accidental check-in.

    Owners, managers and platform admins may undo any check-in; check-in
    staff only their own, within ``STAFF_UNDO_WINDOW_MINUTES``.
    """
    event = await _event_for_check_in(db, event_id, actor)
    row = await _find_by_id(db, event, ticket_id)
    ticket, attendee, _, _ = row
    if ticket.status != TicketStatus.CHECKED_IN:
        raise HTTPException(status.HTTP_409_CONFLICT, "This ticket is not checked in")

    role = await get_staff_role(db, event.id, actor.id)
    if role == StaffRole.CHECKIN_STAFF and not actor.is_platform_admin:
        last = await db.scalar(
            select(CheckInRecord)
            .where(
                CheckInRecord.ticket_id == ticket.id,
                CheckInRecord.action == CheckInAction.CHECK_IN,
            )
            .order_by(CheckInRecord.created_at.desc())
            .limit(1)
        )
        window = timedelta(minutes=STAFF_UNDO_WINDOW_MINUTES)
        if (
            last is None
            or last.performed_by_user_id != actor.id
            or last.created_at < _now() - window
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Check-in staff can only undo their own check-ins within "
                f"{STAFF_UNDO_WINDOW_MINUTES} minutes; ask a manager",
            )

    ticket.status = TicketStatus.VALID
    ticket.checked_in_at = None
    ticket.checked_in_by_name = None
    db.add(
        CheckInRecord(
            ticket_id=ticket.id,
            event_id=event.id,
            action=CheckInAction.UNDO,
            method=CheckInMethod.MANUAL,
            performed_by_user_id=actor.id,
            performed_by_name=actor.full_name,
            reason=reason,
        )
    )
    audit.record(
        db,
        actor=actor,
        action=AuditAction.CHECK_IN_UNDONE,
        entity_type=AuditEntity.TICKET,
        entity_id=ticket.id,
        event_id=event.id,
        description=f"Undid check-in of {attendee.name}: {reason}",
        details={"reason": reason},
    )
    await db.commit()
    outcome = _outcome(ScanResult.VALID, event, row)
    outcome.message = f"Check-in undone: {attendee.name} can be admitted again"
    return outcome


# --- Counts and history -------------------------------------------------------------


async def stats(db: AsyncSession, event_id: UUID, actor: User) -> CheckInStats:
    event = await event_service.get_managed_event(
        db, event_id, actor, allowed=ALL_STAFF_ROLES
    )
    rows = await db.execute(
        select(Ticket.status, func.count())
        .join(OrderItem, OrderItem.id == Ticket.order_item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.event_id == event.id,
            Ticket.status.in_((TicketStatus.VALID, TicketStatus.CHECKED_IN)),
        )
        .group_by(Ticket.status)
    )
    counts = {ticket_status: count for ticket_status, count in rows.all()}
    checked_in = counts.get(TicketStatus.CHECKED_IN, 0)
    registered = checked_in + counts.get(TicketStatus.VALID, 0)
    return CheckInStats(
        event_id=event.id,
        registered=registered,
        checked_in=checked_in,
        remaining=registered - checked_in,
        checked_in_percent=round(100 * checked_in / registered, 1)
        if registered
        else 0.0,
    )


async def history(
    db: AsyncSession, event_id: UUID, actor: User, since: datetime | None
) -> list[CheckInRecordResponse]:
    """Recent check-ins and reversals, newest first; ``since`` lets the app
    fetch only what changed (online sync with the central platform)."""
    event = await event_service.get_managed_event(
        db, event_id, actor, allowed=ALL_STAFF_ROLES
    )
    query = (
        select(CheckInRecord, Attendee.name)
        .join(Ticket, Ticket.id == CheckInRecord.ticket_id)
        .join(Attendee, Attendee.id == Ticket.attendee_id)
        .where(CheckInRecord.event_id == event.id)
    )
    if since:
        query = query.where(CheckInRecord.created_at > since)
    rows = await db.execute(query.order_by(CheckInRecord.created_at.desc()).limit(500))
    return [
        CheckInRecordResponse(
            id=record.id,
            ticket_id=record.ticket_id,
            attendee_name=name,
            action=record.action,
            method=record.method,
            performed_by_name=record.performed_by_name,
            reason=record.reason,
            created_at=record.created_at,
        )
        for record, name in rows.all()
    ]
