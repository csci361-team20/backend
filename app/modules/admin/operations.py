"""Platform administration (SRS 4.12): search, suspensions, reports,
monitors, disputes, promo activity, the platform audit log and CSV exports.

Every function here is for platform admins; the router enforces that.
"""

import csv
import io
from datetime import UTC, datetime
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import Select, String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.kz_ids import mask
from app.modules.activation.models import EventActivation
from app.modules.admin.models import Dispute, EventReport
from app.modules.admin.schemas import (
    AdminEventRow,
    AdminOrderRow,
    AdminOrganizerRow,
    AdminPaymentRow,
    AdminRefundRow,
    AdminUserRow,
    PromoActivityRow,
    ReportResponse,
    ReportReview,
    SearchResults,
)
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.audit.models import AuditLog
from app.modules.events import service as event_service
from app.modules.events.models import Event
from app.modules.notifications.service import notify
from app.modules.orders.enums import PaymentStatus
from app.modules.orders.models import Order, Payment, Refund
from app.modules.organizers.models import OrganizerProfile
from app.modules.promotions.models import (
    PromoCode,
    PromoRedemption,
    PromotionalCampaign,
)
from app.modules.support.models import SupportCase
from app.modules.users.models import User


def _now() -> datetime:
    return datetime.now(UTC)


def _like(q: str) -> str:
    return f"%{q.strip()}%"


def _uuid(q: str) -> UUID | None:
    try:
        return UUID(q.strip())
    except ValueError:
        return None


# --- Lists ----------------------------------------------------------------------


def _user_row(user: User) -> AdminUserRow:
    return AdminUserRow.model_validate(user, from_attributes=True)


async def list_users(
    db: AsyncSession, q: str | None, suspended: bool | None, limit: int, offset: int
) -> list[AdminUserRow]:
    query = select(User)
    if q:
        query = query.where(
            or_(User.email.ilike(_like(q)), User.full_name.ilike(_like(q)))
        )
    if suspended is not None:
        query = query.where(User.is_suspended.is_(suspended))
    rows = await db.execute(
        query.order_by(User.created_at.desc()).offset(offset).limit(limit)
    )
    return [_user_row(u) for u in rows.scalars()]


async def list_organizers(
    db: AsyncSession,
    q: str | None,
    verification_status: str | None,
    limit: int,
    offset: int,
) -> list[AdminOrganizerRow]:
    """Organizers for the verification queue, latest submissions first."""
    query = select(OrganizerProfile, User).join(
        User, User.id == OrganizerProfile.user_id
    )
    if q:
        query = query.where(
            or_(
                OrganizerProfile.display_name.ilike(_like(q)),
                OrganizerProfile.legal_name.ilike(_like(q)),
                User.email.ilike(_like(q)),
            )
        )
    if verification_status:
        query = query.where(OrganizerProfile.verification_status == verification_status)
    rows = await db.execute(
        query.order_by(
            OrganizerProfile.verification_submitted_at.desc().nulls_last(),
            OrganizerProfile.display_name,
        )
        .offset(offset)
        .limit(limit)
    )
    return [
        AdminOrganizerRow(
            id=profile.id,
            user_id=profile.user_id,
            display_name=profile.display_name,
            email=user.email,
            verification_status=profile.verification_status,
            legal_name=profile.legal_name,
            tax_id_masked=mask(profile.tax_id) if profile.tax_id else None,
            verification_submitted_at=profile.verification_submitted_at,
            verified_at=profile.verified_at,
            is_suspended=user.is_suspended,
        )
        for profile, user in rows.all()
    ]


def _event_query() -> Select:
    return select(Event, OrganizerProfile.display_name).join(
        OrganizerProfile, OrganizerProfile.id == Event.organizer_profile_id
    )


def _event_row(event: Event, organizer: str) -> AdminEventRow:
    return AdminEventRow(
        id=event.id,
        title=event.title,
        organizer_name=organizer,
        status=event.status,
        lifecycle=event.lifecycle,
        visibility=event.visibility,
        start_at=event.start_at,
        city=event.city,
        is_suspended=event.is_suspended,
        suspension_reason=event.suspension_reason,
        paid_sales_open=event.paid_sales_open,
        created_at=event.created_at,
    )


async def list_events(
    db: AsyncSession,
    q: str | None,
    event_status: str | None,
    suspended: bool | None,
    limit: int,
    offset: int,
) -> list[AdminEventRow]:
    query = _event_query()
    if q:
        event_id = _uuid(q)
        query = query.where(
            Event.id == event_id
            if event_id
            else or_(
                Event.title.ilike(_like(q)),
                OrganizerProfile.display_name.ilike(_like(q)),
            )
        )
    if event_status:
        query = query.where(Event.status == event_status)
    if suspended is not None:
        query = query.where(Event.is_suspended.is_(suspended))
    rows = await db.execute(
        query.order_by(Event.created_at.desc()).offset(offset).limit(limit)
    )
    return [_event_row(event, name) for event, name in rows.all()]


async def list_orders(
    db: AsyncSession,
    q: str | None,
    order_status: str | None,
    event_id: UUID | None,
    limit: int,
    offset: int,
) -> list[AdminOrderRow]:
    query = (
        select(Order, Event.title, User.email)
        .join(Event, Event.id == Order.event_id)
        .join(User, User.id == Order.user_id)
    )
    if q:
        order_id = _uuid(q)
        query = query.where(
            Order.id == order_id
            if order_id
            else or_(
                User.email.ilike(_like(q)),
                cast(Order.id, String).ilike(f"{q.strip()}%"),
            )
        )
    if order_status:
        query = query.where(Order.status == order_status)
    if event_id:
        query = query.where(Order.event_id == event_id)
    rows = await db.execute(
        query.order_by(Order.created_at.desc()).offset(offset).limit(limit)
    )
    return [
        AdminOrderRow(
            id=order.id,
            event_id=order.event_id,
            event_title=title,
            buyer_email=buyer,
            status=order.status,
            total_kzt=order.total_kzt,
            discount_kzt=order.discount_kzt,
            promo_code=order.promo_code,
            created_at=order.created_at,
        )
        for order, title, buyer in rows.all()
    ]


async def list_payments(
    db: AsyncSession,
    q: str | None,
    payment_status: PaymentStatus | None,
    limit: int,
    offset: int,
) -> list[AdminPaymentRow]:
    query = (
        select(Payment, Event.title, User.email)
        .join(Order, Order.id == Payment.order_id)
        .join(Event, Event.id == Order.event_id)
        .join(User, User.id == Order.user_id)
    )
    if q:
        some_id = _uuid(q)
        query = query.where(
            or_(Payment.id == some_id, Payment.order_id == some_id)
            if some_id
            else User.email.ilike(_like(q))
        )
    if payment_status:
        query = query.where(Payment.status == payment_status)
    rows = await db.execute(
        query.order_by(Payment.created_at.desc()).offset(offset).limit(limit)
    )
    return [
        AdminPaymentRow(
            id=payment.id,
            order_id=payment.order_id,
            event_title=title,
            buyer_email=buyer,
            status=payment.status,
            amount_kzt=payment.amount_kzt,
            processing_fee_kzt=payment.processing_fee_kzt,
            failure_reason=payment.failure_reason,
            is_simulated=payment.is_simulated,
            created_at=payment.created_at,
        )
        for payment, title, buyer in rows.all()
    ]


async def list_refunds(
    db: AsyncSession, limit: int, offset: int
) -> list[AdminRefundRow]:
    rows = await db.execute(
        select(Refund, Event.title, User.email)
        .join(Order, Order.id == Refund.order_id)
        .join(Event, Event.id == Refund.event_id)
        .join(User, User.id == Order.user_id)
        .order_by(Refund.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        AdminRefundRow(
            id=refund.id,
            order_id=refund.order_id,
            event_title=title,
            buyer_email=buyer,
            amount_kzt=refund.amount_kzt,
            reason=refund.reason,
            initiated_by_name=refund.initiated_by_name,
            created_at=refund.created_at,
        )
        for refund, title, buyer in rows.all()
    ]


async def search(db: AsyncSession, q: str) -> SearchResults:
    """One box for users, events, orders and payments (SRS 4.12)."""
    return SearchResults(
        users=await list_users(db, q, None, 10, 0),
        events=await list_events(db, q, None, None, 10, 0),
        orders=await list_orders(db, q, None, None, 10, 0),
        payments=await list_payments(db, q, None, 10, 0),
    )


# --- Suspensions ------------------------------------------------------------------


async def suspend_user(
    db: AsyncSession, admin: User, user_id: UUID, reason: str
) -> User:
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot suspend yourself")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.is_suspended:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This account is already suspended"
        )
    user.is_suspended = True
    user.suspension_reason = reason
    # Signs them out everywhere at once
    user.token_version += 1
    audit.record(
        db,
        actor=admin,
        action=AuditAction.USER_SUSPENDED,
        entity_type=AuditEntity.USER,
        entity_id=user.id,
        description=f"Suspended {user.email}: {reason}",
        details={"reason": reason},
    )
    await db.commit()
    await db.refresh(user)
    return user


async def restore_user(db: AsyncSession, admin: User, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not user.is_suspended:
        raise HTTPException(status.HTTP_409_CONFLICT, "This account is not suspended")
    user.is_suspended = False
    user.suspension_reason = None
    audit.record(
        db,
        actor=admin,
        action=AuditAction.USER_RESTORED,
        entity_type=AuditEntity.USER,
        entity_id=user.id,
        description=f"Restored {user.email}",
    )
    await db.commit()
    await db.refresh(user)
    return user


async def _owner(db: AsyncSession, event: Event) -> User | None:
    return await db.scalar(
        select(User)
        .join(OrganizerProfile, OrganizerProfile.user_id == User.id)
        .where(OrganizerProfile.id == event.organizer_profile_id)
    )


async def suspend_event(
    db: AsyncSession,
    admin: User,
    event_id: UUID,
    reason: str,
    background: BackgroundTasks,
    *,
    commit: bool = True,
) -> Event:
    """Hide the event and stop all new orders. Tickets already issued stay
    valid; the organizer is told why (SRS 4.12, success criterion 12)."""
    event = await event_service.get_event(db, event_id)
    if event.is_suspended:
        raise HTTPException(status.HTTP_409_CONFLICT, "This event is already suspended")
    event.is_suspended = True
    event.suspended_at = _now()
    event.suspension_reason = reason
    audit.record(
        db,
        actor=admin,
        action=AuditAction.EVENT_SUSPENDED,
        entity_type=AuditEntity.EVENT,
        entity_id=event.id,
        event_id=event.id,
        description=f"Event suspended by the platform: {reason}",
        details={"reason": reason},
    )
    owner = await _owner(db, event)
    if owner:
        notify(
            db,
            background,
            [owner],
            "event_suspended",
            link=f"/events/{event.id}",
            event_id=event.id,
            event=event.title,
            reason=reason,
        )
    if commit:
        await db.commit()
        await db.refresh(event)
    return event


async def restore_event(
    db: AsyncSession, admin: User, event_id: UUID, background: BackgroundTasks
) -> Event:
    event = await event_service.get_event(db, event_id)
    if not event.is_suspended:
        raise HTTPException(status.HTTP_409_CONFLICT, "This event is not suspended")
    event.is_suspended = False
    event.suspended_at = None
    event.suspension_reason = None
    audit.record(
        db,
        actor=admin,
        action=AuditAction.EVENT_RESTORED,
        entity_type=AuditEntity.EVENT,
        entity_id=event.id,
        event_id=event.id,
        description="Event suspension lifted",
    )
    owner = await _owner(db, event)
    if owner:
        notify(
            db,
            background,
            [owner],
            "event_restored",
            link=f"/events/{event.id}",
            event_id=event.id,
            event=event.title,
        )
    await db.commit()
    await db.refresh(event)
    return event


# --- Event reports ------------------------------------------------------------------


async def _report_response(db: AsyncSession, report: EventReport) -> ReportResponse:
    title = await db.scalar(select(Event.title).where(Event.id == report.event_id))
    return ReportResponse(
        id=report.id,
        event_id=report.event_id,
        event_title=title or "",
        reporter_user_id=report.reporter_user_id,
        reason=report.reason,
        status=report.status,
        review_note=report.review_note,
        reviewed_at=report.reviewed_at,
        created_at=report.created_at,
    )


async def report_event(
    db: AsyncSession, user: User, event_id: UUID, reason: str
) -> ReportResponse:
    """Any signed-in user who can see the event may report it, once while a
    report from them is pending."""
    event = await event_service.get_visible_event(db, event_id, user)
    pending = await db.scalar(
        select(EventReport.id).where(
            EventReport.event_id == event.id,
            EventReport.reporter_user_id == user.id,
            EventReport.status == "pending",
        )
    )
    if pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You already reported this event; it is under review",
        )
    report = EventReport(event_id=event.id, reporter_user_id=user.id, reason=reason)
    db.add(report)
    await db.flush()
    audit.record(
        db,
        actor=user,
        action=AuditAction.EVENT_REPORTED,
        entity_type=AuditEntity.EVENT_REPORT,
        entity_id=report.id,
        event_id=event.id,
        description="Event reported to the platform team",
    )
    await db.commit()
    await db.refresh(report)
    return await _report_response(db, report)


async def list_reports(
    db: AsyncSession, report_status: str | None, limit: int, offset: int
) -> list[ReportResponse]:
    query = select(EventReport)
    if report_status:
        query = query.where(EventReport.status == report_status)
    rows = await db.execute(
        query.order_by(EventReport.created_at.desc()).offset(offset).limit(limit)
    )
    return [await _report_response(db, r) for r in rows.scalars()]


async def review_report(
    db: AsyncSession,
    admin: User,
    report_id: UUID,
    data_in: ReportReview,
    background: BackgroundTasks,
) -> ReportResponse:
    report = await db.get(EventReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    if report.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already {report.status}")
    if data_in.suspend_event and data_in.decision != "actioned":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Suspending the event means acting on the report",
        )
    report.status = data_in.decision
    report.review_note = data_in.note
    report.reviewed_by_user_id = admin.id
    report.reviewed_at = _now()
    audit.record(
        db,
        actor=admin,
        action=AuditAction.REPORT_REVIEWED,
        entity_type=AuditEntity.EVENT_REPORT,
        entity_id=report.id,
        event_id=report.event_id,
        description=f"Report {data_in.decision}"
        + (f": {data_in.note}" if data_in.note else ""),
    )
    if data_in.suspend_event:
        await suspend_event(
            db,
            admin,
            report.event_id,
            data_in.note or "Suspended after a report review",
            background,
            commit=False,
        )
    await db.commit()
    await db.refresh(report)
    return await _report_response(db, report)


# --- Disputes ---------------------------------------------------------------------


async def open_dispute(
    db: AsyncSession, admin: User, payment_id: UUID, reason: str
) -> Dispute:
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if payment.status != PaymentStatus.SUCCEEDED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only successful payments can be disputed"
        )
    dispute = Dispute(
        payment_id=payment.id,
        order_id=payment.order_id,
        amount_kzt=payment.amount_kzt,
        reason=reason,
        opened_by_user_id=admin.id,
    )
    db.add(dispute)
    await db.flush()
    event_id = await db.scalar(
        select(Order.event_id).where(Order.id == payment.order_id)
    )
    audit.record(
        db,
        actor=admin,
        action=AuditAction.DISPUTE_OPENED,
        entity_type=AuditEntity.DISPUTE,
        entity_id=dispute.id,
        event_id=event_id,
        description=f"Dispute opened on a {payment.amount_kzt} KZT payment: {reason}",
    )
    await db.commit()
    await db.refresh(dispute)
    return dispute


async def resolve_dispute(
    db: AsyncSession, admin: User, dispute_id: UUID, outcome: str, note: str | None
) -> Dispute:
    dispute = await db.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispute not found")
    if dispute.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already {dispute.status}")
    dispute.status = outcome
    dispute.resolution_note = note
    dispute.resolved_at = _now()
    event_id = await db.scalar(
        select(Order.event_id).where(Order.id == dispute.order_id)
    )
    audit.record(
        db,
        actor=admin,
        action=AuditAction.DISPUTE_RESOLVED,
        entity_type=AuditEntity.DISPUTE,
        entity_id=dispute.id,
        event_id=event_id,
        description=f"Dispute {outcome}" + (f": {note}" if note else ""),
    )
    await db.commit()
    await db.refresh(dispute)
    return dispute


async def list_disputes(
    db: AsyncSession, dispute_status: str | None, limit: int, offset: int
) -> list[Dispute]:
    query = select(Dispute)
    if dispute_status:
        query = query.where(Dispute.status == dispute_status)
    rows = await db.execute(
        query.order_by(Dispute.created_at.desc()).offset(offset).limit(limit)
    )
    return list(rows.scalars())


# --- Promo activity and audit ------------------------------------------------


async def promo_activity(
    db: AsyncSession, limit: int, offset: int
) -> list[PromoActivityRow]:
    rows = await db.execute(
        select(
            PromoRedemption,
            PromoCode.code,
            PromotionalCampaign,
            Event.title,
            Order.status,
            User.email,
        )
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_code_id)
        .join(
            PromotionalCampaign, PromotionalCampaign.id == PromoRedemption.campaign_id
        )
        .join(Event, Event.id == PromotionalCampaign.event_id)
        .join(Order, Order.id == PromoRedemption.order_id)
        .join(User, User.id == PromoRedemption.user_id)
        .order_by(PromoRedemption.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        PromoActivityRow(
            redemption_id=redemption.id,
            code=code,
            campaign_name=campaign.name,
            event_id=campaign.event_id,
            event_title=title,
            order_id=redemption.order_id,
            order_status=order_status,
            buyer_email=buyer,
            discount_kzt=redemption.discount_kzt,
            created_at=redemption.created_at,
        )
        for redemption, code, campaign, title, order_status, buyer in rows.all()
    ]


async def audit_log(
    db: AsyncSession,
    action_prefix: str | None,
    since: datetime | None,
    limit: int,
    offset: int,
) -> list[AuditLog]:
    """The whole platform's audit trail, newest first. Read-only."""
    query = select(AuditLog)
    if action_prefix:
        query = query.where(AuditLog.action.startswith(action_prefix))
    if since:
        query = query.where(AuditLog.created_at >= since)
    rows = await db.execute(
        query.order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset(offset)
        .limit(limit)
    )
    return list(rows.scalars())


# --- CSV exports ------------------------------------------------------------------


EXPORT_KINDS = (
    "users",
    "events",
    "orders",
    "payments",
    "refunds",
    "activations",
    "disputes",
    "promotions",
    "support",
)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """Text for one CSV cell; a leading formula character is neutralised so a
    spreadsheet never runs it (CSV injection)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


async def _export_rows(
    db: AsyncSession, kind: str
) -> tuple[list[str], list[list[object]]]:
    big = 100_000
    if kind == "users":
        rows = await list_users(db, None, None, big, 0)
        return (
            [
                "id",
                "email",
                "full_name",
                "is_platform_admin",
                "is_suspended",
                "created_at",
            ],
            [
                [
                    r.id,
                    r.email,
                    r.full_name,
                    r.is_platform_admin,
                    r.is_suspended,
                    r.created_at,
                ]
                for r in rows
            ],
        )
    if kind == "events":
        rows = await list_events(db, None, None, None, big, 0)
        return (
            ["id", "title", "organizer", "status", "start_at", "city", "is_suspended"],
            [
                [
                    r.id,
                    r.title,
                    r.organizer_name,
                    r.status,
                    r.start_at,
                    r.city,
                    r.is_suspended,
                ]
                for r in rows
            ],
        )
    if kind == "orders":
        rows = await list_orders(db, None, None, None, big, 0)
        return (
            [
                "id",
                "event",
                "buyer_email",
                "status",
                "total_kzt",
                "discount_kzt",
                "promo_code",
                "created_at",
            ],
            [
                [
                    r.id,
                    r.event_title,
                    r.buyer_email,
                    r.status,
                    r.total_kzt,
                    r.discount_kzt,
                    r.promo_code,
                    r.created_at,
                ]
                for r in rows
            ],
        )
    if kind == "payments":
        rows = await list_payments(db, None, None, big, 0)
        return (
            [
                "id",
                "order_id",
                "event",
                "buyer_email",
                "status",
                "amount_kzt",
                "fee_kzt",
                "failure_reason",
                "simulated",
                "created_at",
            ],
            [
                [
                    r.id,
                    r.order_id,
                    r.event_title,
                    r.buyer_email,
                    r.status,
                    r.amount_kzt,
                    r.processing_fee_kzt,
                    r.failure_reason,
                    r.is_simulated,
                    r.created_at,
                ]
                for r in rows
            ],
        )
    if kind == "refunds":
        rows = await list_refunds(db, big, 0)
        return (
            [
                "id",
                "order_id",
                "event",
                "buyer_email",
                "amount_kzt",
                "reason",
                "initiated_by",
                "created_at",
            ],
            [
                [
                    r.id,
                    r.order_id,
                    r.event_title,
                    r.buyer_email,
                    r.amount_kzt,
                    r.reason,
                    r.initiated_by_name,
                    r.created_at,
                ]
                for r in rows
            ],
        )
    if kind == "activations":
        result = await db.execute(
            select(EventActivation).order_by(EventActivation.created_at.desc())
        )
        return (
            [
                "id",
                "event_id",
                "status",
                "fee_kzt",
                "fee_paid_at",
                "activated_at",
                "suspended_at",
                "suspension_reason",
            ],
            [
                [
                    a.id,
                    a.event_id,
                    a.status,
                    a.fee_kzt,
                    a.fee_paid_at,
                    a.activated_at,
                    a.suspended_at,
                    a.suspension_reason,
                ]
                for a in result.scalars()
            ],
        )
    if kind == "disputes":
        rows = await list_disputes(db, None, big, 0)
        return (
            [
                "id",
                "payment_id",
                "order_id",
                "amount_kzt",
                "status",
                "reason",
                "created_at",
                "resolved_at",
            ],
            [
                [
                    d.id,
                    d.payment_id,
                    d.order_id,
                    d.amount_kzt,
                    d.status,
                    d.reason,
                    d.created_at,
                    d.resolved_at,
                ]
                for d in rows
            ],
        )
    if kind == "promotions":
        rows = await promo_activity(db, big, 0)
        return (
            [
                "redemption_id",
                "code",
                "campaign",
                "event",
                "order_id",
                "order_status",
                "buyer_email",
                "discount_kzt",
                "created_at",
            ],
            [
                [
                    r.redemption_id,
                    r.code,
                    r.campaign_name,
                    r.event_title,
                    r.order_id,
                    r.order_status,
                    r.buyer_email,
                    r.discount_kzt,
                    r.created_at,
                ]
                for r in rows
            ],
        )
    if kind == "support":
        result = await db.execute(
            select(SupportCase).order_by(SupportCase.created_at.desc())
        )
        return (
            [
                "id",
                "audience",
                "category",
                "subject",
                "status",
                "event_id",
                "is_escalated",
                "created_at",
            ],
            [
                [
                    c.id,
                    c.audience,
                    c.category,
                    c.subject,
                    c.status,
                    c.event_id,
                    c.is_escalated,
                    c.created_at,
                ]
                for c in result.scalars()
            ],
        )
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown export '{kind}'")


async def export_csv(db: AsyncSession, kind: str) -> str:
    header, rows = await _export_rows(db, kind)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return buffer.getvalue()
