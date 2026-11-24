"""Platform administration (SRS 4.12). Every route needs a platform admin.

Phase 5 covers settings and paid-sales activation records; search,
suspensions, reports, disputes and exports follow in phase 11.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Response, status

from app.api.deps import CurrentUser, DatabaseSession, PlatformAdmin
from app.modules.activation import service as activation_service
from app.modules.activation.enums import ActivationStatus
from app.modules.activation.schemas import (
    ActivationRecordResponse,
    ActivationResponse,
    SuspensionCreate,
)
from app.modules.admin import operations
from app.modules.admin import service as admin_service
from app.modules.admin.schemas import (
    AdminEventRow,
    AdminOrderRow,
    AdminOrganizerRow,
    AdminPaymentRow,
    AdminRefundRow,
    AdminUserRow,
    AuditRow,
    DisputeCreate,
    DisputeResolve,
    DisputeResponse,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    PromoActivityRow,
    ReportCreate,
    ReportResponse,
    ReportReview,
    SearchResults,
    SuspensionRequest,
)
from app.modules.orders.enums import PaymentStatus
from app.modules.organizers.schemas import VerificationStatus

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/settings", response_model=PlatformSettingsResponse)
async def get_settings(db: DatabaseSession, _admin: PlatformAdmin):
    return await admin_service.get_settings(db)


@router.patch("/settings", response_model=PlatformSettingsResponse)
async def update_settings(
    data_in: PlatformSettingsUpdate, db: DatabaseSession, admin: PlatformAdmin
):
    """A new activation fee applies to activation records created afterwards;
    existing records keep the fee they were created with."""
    return await admin_service.update_settings(db, admin, data_in)


@router.get("/activations", response_model=list[ActivationRecordResponse])
async def list_activations(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    record_status: Annotated[ActivationStatus | None, Query(alias="status")] = None,
):
    """Paid-sales activation records, newest first."""
    return await activation_service.list_records(db, record_status)


@router.post("/events/{event_id}/paid-sales/suspend", response_model=ActivationResponse)
async def suspend_paid_sales(
    event_id: UUID,
    data_in: SuspensionCreate,
    db: DatabaseSession,
    admin: PlatformAdmin,
    background: BackgroundTasks,
):
    """Stop paid sales (fraud or policy). Free tickets and sold tickets are not
    affected; unpaid checkouts can no longer be paid. The organizer is emailed."""
    return await activation_service.suspend(
        db, event_id, admin, data_in.reason, background
    )


@router.post("/events/{event_id}/paid-sales/resume", response_model=ActivationResponse)
async def resume_paid_sales(
    event_id: UUID,
    db: DatabaseSession,
    admin: PlatformAdmin,
    background: BackgroundTasks,
):
    """Lift a suspension; the organizer is told that payouts are no longer held."""
    return await activation_service.resume(db, event_id, admin, background)


# --- Search and lists --------------------------------------------------------------

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/search", response_model=SearchResults)
async def search(
    q: Annotated[str, Query(min_length=2, max_length=100)],
    db: DatabaseSession,
    _admin: PlatformAdmin,
):
    """Users, events, orders and payments matching ``q`` (name, email, title
    or an id), up to 10 of each."""
    return await operations.search(db, q)


@router.get("/users", response_model=list[AdminUserRow])
async def list_users(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    q: str | None = None,
    suspended: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return await operations.list_users(db, q, suspended, limit, offset)


@router.post("/users/{user_id}/suspend", response_model=AdminUserRow)
async def suspend_user(
    user_id: UUID, data_in: SuspensionRequest, db: DatabaseSession, admin: PlatformAdmin
):
    """Blocks sign-in and signs the account out everywhere. Their events
    leave public view and stop taking orders."""
    return operations._user_row(
        await operations.suspend_user(db, admin, user_id, data_in.reason)
    )


@router.post("/users/{user_id}/restore", response_model=AdminUserRow)
async def restore_user(user_id: UUID, db: DatabaseSession, admin: PlatformAdmin):
    return operations._user_row(await operations.restore_user(db, admin, user_id))


@router.get("/organizers", response_model=list[AdminOrganizerRow])
async def list_organizers(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    q: str | None = None,
    verification_status: VerificationStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    """Organizers with their identity-check state. Decide with
    ``PATCH /organizers/{id}/verification``."""
    return await operations.list_organizers(db, q, verification_status, limit, offset)


@router.get("/events", response_model=list[AdminEventRow])
async def list_events(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    q: str | None = None,
    event_status: Annotated[str | None, Query(alias="status")] = None,
    suspended: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return await operations.list_events(db, q, event_status, suspended, limit, offset)


@router.post("/events/{event_id}/suspend", response_model=AdminEventRow)
async def suspend_event(
    event_id: UUID,
    data_in: SuspensionRequest,
    db: DatabaseSession,
    admin: PlatformAdmin,
    background: BackgroundTasks,
):
    """Hides the event from attendees and stops all new orders; issued
    tickets stay valid. The organizer is notified."""
    event = await operations.suspend_event(
        db, admin, event_id, data_in.reason, background
    )
    return (await operations.list_events(db, str(event.id), None, None, 1, 0))[0]


@router.post("/events/{event_id}/restore", response_model=AdminEventRow)
async def restore_event(
    event_id: UUID,
    db: DatabaseSession,
    admin: PlatformAdmin,
    background: BackgroundTasks,
):
    event = await operations.restore_event(db, admin, event_id, background)
    return (await operations.list_events(db, str(event.id), None, None, 1, 0))[0]


@router.get("/orders", response_model=list[AdminOrderRow])
async def list_orders(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    q: str | None = None,
    order_status: Annotated[str | None, Query(alias="status")] = None,
    event_id: UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return await operations.list_orders(db, q, order_status, event_id, limit, offset)


@router.get("/payments", response_model=list[AdminPaymentRow])
async def list_payments(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    q: str | None = None,
    payment_status: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    """``status=failed`` is the payment-failure monitor."""
    return await operations.list_payments(db, q, payment_status, limit, offset)


@router.get("/refunds", response_model=list[AdminRefundRow])
async def list_refunds(
    db: DatabaseSession, _admin: PlatformAdmin, limit: Limit = 50, offset: Offset = 0
):
    return await operations.list_refunds(db, limit, offset)


# --- Reports, disputes, promo activity, audit ---------------------------------------


@router.get("/reports", response_model=list[ReportResponse])
async def list_reports(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    report_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return await operations.list_reports(db, report_status, limit, offset)


@router.post("/reports/{report_id}/review", response_model=ReportResponse)
async def review_report(
    report_id: UUID,
    data_in: ReportReview,
    db: DatabaseSession,
    admin: PlatformAdmin,
    background: BackgroundTasks,
):
    return await operations.review_report(db, admin, report_id, data_in, background)


@router.post(
    "/payments/{payment_id}/disputes",
    response_model=DisputeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_dispute(
    payment_id: UUID, data_in: DisputeCreate, db: DatabaseSession, admin: PlatformAdmin
):
    return await operations.open_dispute(db, admin, payment_id, data_in.reason)


@router.get("/disputes", response_model=list[DisputeResponse])
async def list_disputes(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    dispute_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return await operations.list_disputes(db, dispute_status, limit, offset)


@router.patch("/disputes/{dispute_id}", response_model=DisputeResponse)
async def resolve_dispute(
    dispute_id: UUID, data_in: DisputeResolve, db: DatabaseSession, admin: PlatformAdmin
):
    return await operations.resolve_dispute(
        db, admin, dispute_id, data_in.status, data_in.note
    )


@router.get("/promo-activity", response_model=list[PromoActivityRow])
async def promo_activity(
    db: DatabaseSession, _admin: PlatformAdmin, limit: Limit = 50, offset: Offset = 0
):
    """Promo-code redemptions across all events, newest first."""
    return await operations.promo_activity(db, limit, offset)


@router.get("/audit", response_model=list[AuditRow])
async def audit_log(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    action: Annotated[
        str | None, Query(description="Action prefix, e.g. platform. or event.")
    ] = None,
    since: datetime | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
):
    """Every recorded action on the platform, newest first. Read-only."""
    return await operations.audit_log(db, action, since, limit, offset)


@router.get(
    "/exports/{kind}.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_csv(kind: str, db: DatabaseSession, _admin: PlatformAdmin):
    """CSV report: users, events, orders, payments, refunds, activations,
    disputes, promotions or support. Cells that start like a spreadsheet
    formula are prefixed with an apostrophe so they are never executed."""
    content = await operations.export_csv(db, kind)
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="biletflow-{kind}.csv"'},
    )


# --- Reporting an event (any signed-in attendee) ----------------------------------

reports_router = APIRouter(tags=["Event reports"])


@reports_router.post(
    "/events/{event_id}/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_event(
    event_id: UUID, data_in: ReportCreate, db: DatabaseSession, actor: CurrentUser
):
    """Flag an event for the platform team (misleading, fraudulent, unsafe)."""
    return await operations.report_event(db, actor, event_id, data_in.reason)
