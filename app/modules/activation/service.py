"""Paid-sales activation (SRS 3.2, 4.5, UC2).

Paid tickets stay off sale until, for that one event, the organizer has:
1. a paid ticket type, 2. verified identity, 3. paid the activation fee,
4. a verified payout account, 5. accepted the paid-event terms, and then
activates. Every step is simulated; no real money moves. Platform admins can
suspend paid sales at any time.
"""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activation.enums import (
    CURRENT_TERMS_VERSION,
    ActivationStatus,
    ChecklistItem,
)
from app.modules.activation.models import EventActivation
from app.modules.activation.schemas import (
    ActivationRecordResponse,
    ActivationResponse,
    ChecklistEntry,
)
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.events import service as event_service
from app.modules.events.enums import EventLifecycle, StaffRole
from app.modules.events.models import Event
from app.modules.events.permissions import MANAGE_ROLES, ensure_event_role
from app.modules.notifications.service import notify
from app.modules.organizers import crud as organizer_crud
from app.modules.organizers.models import OrganizerProfile
from app.modules.organizers.payouts import get_payout_account
from app.modules.organizers.schemas import VerificationStatus
from app.modules.platform.service import get_settings
from app.modules.tickets.models import TicketType
from app.modules.users import crud as users_crud
from app.modules.users.models import User

_LABELS = {
    ChecklistItem.PAID_TICKET_TYPE: "Create at least one paid ticket type",
    ChecklistItem.IDENTITY_VERIFIED: "Verify your identity",
    ChecklistItem.ACTIVATION_FEE_PAID: "Pay the activation fee",
    ChecklistItem.PAYOUT_ACCOUNT: "Add a payout account",
    ChecklistItem.TERMS_ACCEPTED: "Accept the paid-event terms",
}
_HINTS = {
    ChecklistItem.PAID_TICKET_TYPE: "POST /events/{id}/ticket-types with price_kzt > 0",
    ChecklistItem.IDENTITY_VERIFIED: "POST /organizers/me/verification",
    ChecklistItem.ACTIVATION_FEE_PAID: "POST /events/{id}/activation/pay-fee",
    ChecklistItem.PAYOUT_ACCOUNT: "PUT /organizers/me/payout-account",
    ChecklistItem.TERMS_ACCEPTED: "POST /events/{id}/activation/accept-terms",
}


def _now() -> datetime:
    return datetime.now(UTC)


async def _get(db: AsyncSession, event_id: UUID) -> EventActivation | None:
    result = await db.execute(
        select(EventActivation).where(EventActivation.event_id == event_id)
    )
    return result.scalar_one_or_none()


async def _get_or_create(db: AsyncSession, event: Event) -> EventActivation:
    activation = await _get(db, event.id)
    if activation is None:
        settings = await get_settings(db)
        activation = EventActivation(
            event_id=event.id,
            organizer_profile_id=event.organizer_profile_id,
            status=ActivationStatus.PENDING,
            fee_kzt=settings.activation_fee_kzt,
        )
        db.add(activation)
        await db.flush()
    return activation


async def _checklist(
    db: AsyncSession, event: Event, activation: EventActivation | None
) -> list[ChecklistEntry]:
    profile = await organizer_crud.get_by_id(db, event.organizer_profile_id)
    account = await get_payout_account(db, event.organizer_profile_id)
    has_paid_type = await db.scalar(
        select(TicketType.id)
        .where(TicketType.event_id == event.id, TicketType.price_kzt > 0)
        .limit(1)
    )
    done = {
        ChecklistItem.PAID_TICKET_TYPE: has_paid_type is not None,
        ChecklistItem.IDENTITY_VERIFIED: bool(
            profile and profile.verification_status == VerificationStatus.VERIFIED
        ),
        ChecklistItem.ACTIVATION_FEE_PAID: bool(activation and activation.fee_paid_at),
        ChecklistItem.PAYOUT_ACCOUNT: bool(account and account.is_verified),
        ChecklistItem.TERMS_ACCEPTED: bool(
            activation
            and activation.terms_accepted_at
            and activation.terms_version == CURRENT_TERMS_VERSION
        ),
    }
    return [
        ChecklistEntry(
            item=item,
            label=_LABELS[item],
            done=done[item],
            hint=None if done[item] else _HINTS[item],
        )
        for item in ChecklistItem
    ]


async def _response(
    db: AsyncSession, event: Event, activation: EventActivation | None
) -> ActivationResponse:
    checklist = await _checklist(db, event, activation)
    fee = (
        activation.fee_kzt
        if activation
        else (await get_settings(db)).activation_fee_kzt
    )
    activation_status = (
        ActivationStatus(activation.status) if activation else ActivationStatus.PENDING
    )
    return ActivationResponse(
        event_id=event.id,
        status=activation_status,
        fee_kzt=fee,
        fee_paid_at=activation.fee_paid_at if activation else None,
        terms_version=CURRENT_TERMS_VERSION,
        terms_accepted_at=activation.terms_accepted_at if activation else None,
        activated_at=activation.activated_at if activation else None,
        suspended_at=activation.suspended_at if activation else None,
        suspension_reason=activation.suspension_reason if activation else None,
        checklist=checklist,
        can_activate=activation_status == ActivationStatus.PENDING
        and all(entry.done for entry in checklist),
    )


def _log(
    db: AsyncSession,
    actor: User,
    action: AuditAction,
    event: Event,
    activation: EventActivation,
    description: str,
    details: dict | None = None,
) -> None:
    audit.record(
        db,
        actor=actor,
        action=action,
        entity_type=AuditEntity.EVENT_ACTIVATION,
        entity_id=activation.id,
        event_id=event.id,
        description=description,
        details=details,
    )


async def _owned_event(db: AsyncSession, event_id: UUID, actor: User) -> Event:
    """Money and legal terms are the owner's call alone, not a manager's or an
    admin's (they cannot act for the organizer)."""
    event = await event_service.get_event(db, event_id)
    await ensure_event_role(
        db, event, actor, (StaffRole.OWNER,), allow_platform_admin=False
    )
    if event.lifecycle in (EventLifecycle.CANCELLED, EventLifecycle.COMPLETED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This event can no longer sell tickets"
        )
    return event


def _ensure_pending(activation: EventActivation) -> None:
    if activation.status != ActivationStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Paid sales are already {activation.status}"
        )


# --- Organizer actions ----------------------------------------------------------


async def get_activation(
    db: AsyncSession, event_id: UUID, actor: User
) -> ActivationResponse:
    event = await event_service.get_event(db, event_id)
    await ensure_event_role(db, event, actor, MANAGE_ROLES)
    return await _response(db, event, await _get(db, event.id))


async def pay_fee(
    db: AsyncSession, event_id: UUID, actor: User, outcome: str
) -> ActivationResponse:
    event = await _owned_event(db, event_id, actor)
    activation = await _get_or_create(db, event)
    _ensure_pending(activation)
    if activation.fee_paid_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The fee is already paid")
    if outcome == "failure":
        _log(
            db,
            actor,
            AuditAction.ACTIVATION_FEE_FAILED,
            event,
            activation,
            f"Activation fee of {activation.fee_kzt} KZT declined (simulated)",
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "The activation fee payment was declined (simulated); try again",
        )
    activation.fee_paid_at = _now()
    activation.fee_payment_reference = f"SIM-{secrets.token_hex(8).upper()}"
    _log(
        db,
        actor,
        AuditAction.ACTIVATION_FEE_PAID,
        event,
        activation,
        f"Paid the activation fee of {activation.fee_kzt} KZT (simulated)",
        {"reference": activation.fee_payment_reference},
    )
    await db.commit()
    return await _response(db, event, activation)


async def accept_terms(
    db: AsyncSession, event_id: UUID, actor: User, terms_version: str
) -> ActivationResponse:
    event = await _owned_event(db, event_id, actor)
    if terms_version != CURRENT_TERMS_VERSION:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The current terms are version {CURRENT_TERMS_VERSION}; "
            "review and accept that version",
        )
    activation = await _get_or_create(db, event)
    _ensure_pending(activation)
    activation.terms_version = terms_version
    activation.terms_accepted_at = _now()
    _log(
        db,
        actor,
        AuditAction.ACTIVATION_TERMS_ACCEPTED,
        event,
        activation,
        f"Accepted the paid-event terms (version {terms_version})",
    )
    await db.commit()
    return await _response(db, event, activation)


async def activate(
    db: AsyncSession, event_id: UUID, actor: User, background: BackgroundTasks
) -> ActivationResponse:
    event = await _owned_event(db, event_id, actor)
    activation = await _get_or_create(db, event)
    _ensure_pending(activation)
    checklist = await _checklist(db, event, activation)
    missing = [entry.label for entry in checklist if not entry.done]
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Finish the checklist first: " + "; ".join(missing),
        )
    now = _now()
    activation.status = ActivationStatus.ACTIVE
    activation.activated_at = now
    event.paid_sales_activated_at = now
    _log(
        db,
        actor,
        AuditAction.PAID_SALES_ACTIVATED,
        event,
        activation,
        "Activated paid ticket sales",
    )
    notify(
        db,
        background,
        [actor],
        "paid_sales_activated",
        link=f"/events/{event.id}",
        event_id=event.id,
        event=event.title,
    )
    await db.commit()
    return await _response(db, event, activation)


# --- Platform admin -------------------------------------------------------------


async def _owner_of(db: AsyncSession, event: Event) -> User | None:
    profile = await organizer_crud.get_by_id(db, event.organizer_profile_id)
    return await users_crud.get_by_id(db, profile.user_id) if profile else None


async def suspend(
    db: AsyncSession,
    event_id: UUID,
    admin: User,
    reason: str,
    background: BackgroundTasks,
) -> ActivationResponse:
    """Stop paid sales for fraud or policy reasons (SRS 4.5). Free tickets and
    tickets already sold are untouched."""
    event = await event_service.get_event(db, event_id)
    activation = await _get_or_create(db, event)
    if activation.status == ActivationStatus.SUSPENDED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Paid sales are already suspended"
        )
    now = _now()
    activation.status = ActivationStatus.SUSPENDED
    activation.suspended_at = now
    activation.suspension_reason = reason
    event.paid_sales_suspended_at = now
    _log(
        db,
        admin,
        AuditAction.PAID_SALES_SUSPENDED,
        event,
        activation,
        f"Paid sales suspended by the platform: {reason}",
        {"reason": reason},
    )
    owner = await _owner_of(db, event)
    if owner:
        notify(
            db,
            background,
            [owner],
            "paid_sales_suspended",
            link=f"/events/{event.id}",
            event_id=event.id,
            event=event.title,
            reason=reason,
        )
    await db.commit()
    return await _response(db, event, activation)


async def resume(
    db: AsyncSession, event_id: UUID, admin: User, background: BackgroundTasks
) -> ActivationResponse:
    event = await event_service.get_event(db, event_id)
    activation = await _get(db, event.id)
    if activation is None or activation.status != ActivationStatus.SUSPENDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Paid sales are not suspended")
    # Back to where it was before the suspension
    activation.status = (
        ActivationStatus.ACTIVE if activation.activated_at else ActivationStatus.PENDING
    )
    activation.suspended_at = None
    activation.suspension_reason = None
    event.paid_sales_suspended_at = None
    _log(
        db,
        admin,
        AuditAction.PAID_SALES_RESUMED,
        event,
        activation,
        "Paid sales resumed",
    )
    owner = await _owner_of(db, event)
    if owner:
        notify(
            db,
            background,
            [owner],
            "paid_sales_resumed",
            link=f"/events/{event.id}",
            event_id=event.id,
            event=event.title,
        )
    await db.commit()
    return await _response(db, event, activation)


async def list_records(
    db: AsyncSession, record_status: ActivationStatus | None
) -> list[ActivationRecordResponse]:
    query = (
        select(EventActivation, Event.title, OrganizerProfile.display_name)
        .join(Event, Event.id == EventActivation.event_id)
        .join(
            OrganizerProfile,
            OrganizerProfile.id == EventActivation.organizer_profile_id,
        )
        .order_by(EventActivation.created_at.desc())
    )
    if record_status:
        query = query.where(EventActivation.status == record_status)
    rows = (await db.execute(query)).all()
    return [
        ActivationRecordResponse(
            id=activation.id,
            event_id=activation.event_id,
            event_title=title,
            organizer_profile_id=activation.organizer_profile_id,
            organizer_name=organizer_name,
            status=activation.status,
            fee_kzt=activation.fee_kzt,
            fee_paid_at=activation.fee_paid_at,
            fee_payment_reference=activation.fee_payment_reference,
            terms_version=activation.terms_version,
            terms_accepted_at=activation.terms_accepted_at,
            activated_at=activation.activated_at,
            suspended_at=activation.suspended_at,
            suspension_reason=activation.suspension_reason,
            created_at=activation.created_at,
        )
        for activation, title, organizer_name in rows
    ]
