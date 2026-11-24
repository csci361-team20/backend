"""Support cases (SRS 4.13, UC9).

Who handles a case:
- attendee cases: the event's owner, managers and support staff; platform
  admins once the case is escalated;
- organizer cases: platform admins.

The requester and the handlers exchange messages. Handlers assign the case
and move it between Open, In Progress, Waiting for Customer and Resolved; a
reply on a resolved case reopens it. Nobody else can see a case.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.events import service as event_service
from app.modules.events.enums import StaffRole
from app.modules.events.models import Event, StaffAssignment
from app.modules.events.permissions import get_staff_role
from app.modules.notifications.service import notify
from app.modules.orders.models import Attendee, Order, OrderItem, Ticket
from app.modules.support.enums import (
    CATEGORIES_BY_AUDIENCE,
    STATUS_LABELS,
    CaseAudience,
    CaseScope,
    CaseStatus,
)
from app.modules.support.models import SupportCase, SupportCaseHistory, SupportMessage
from app.modules.support.schemas import (
    AssigneeOption,
    CaseCreate,
    CaseDetail,
    CaseSummary,
    CaseUpdate,
    HistoryResponse,
    MessageResponse,
)
from app.modules.users.models import User

EVENT_SUPPORT_ROLES = (StaffRole.OWNER, StaffRole.MANAGER, StaffRole.SUPPORT_STAFF)


def _now() -> datetime:
    return datetime.now(UTC)


# --- Who may do what ---------------------------------------------------------------


async def _is_handler(db: AsyncSession, case: SupportCase, user: User) -> bool:
    if case.audience == CaseAudience.ORGANIZER:
        return user.is_platform_admin
    if user.is_platform_admin and case.is_escalated:
        return True
    if case.event_id is None:
        return False
    return await get_staff_role(db, case.event_id, user.id) in EVENT_SUPPORT_ROLES


async def _get_visible(
    db: AsyncSession, case_id: UUID, user: User
) -> tuple[SupportCase, bool]:
    """The case and whether ``user`` handles it. 404 for anyone else."""
    case = await db.get(SupportCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Support case not found")
    handler = await _is_handler(db, case, user)
    if not handler and case.requester_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Support case not found")
    return case, handler


async def _handler_ids(db: AsyncSession, case: SupportCase) -> dict[UUID, str]:
    """Everyone who can answer the case: {user_id: role}."""
    handlers: dict[UUID, str] = {}
    if case.audience == CaseAudience.ATTENDEE and case.event_id:
        rows = await db.execute(
            select(StaffAssignment.user_id, StaffAssignment.role).where(
                StaffAssignment.event_id == case.event_id,
                StaffAssignment.role.in_(EVENT_SUPPORT_ROLES),
            )
        )
        handlers.update({user_id: role for user_id, role in rows.all()})
    if case.audience == CaseAudience.ORGANIZER or case.is_escalated:
        admins = await db.execute(
            select(User.id).where(User.is_platform_admin.is_(True))
        )
        for (admin_id,) in admins.all():
            handlers.setdefault(admin_id, "platform_admin")
    return handlers


# --- Context ------------------------------------------------------------------------


async def _resolve_context(
    db: AsyncSession, user: User, data_in: CaseCreate
) -> tuple[UUID | None, UUID | None, UUID | None]:
    """Fill in event and order from the most specific reference given, and
    check the requester is entitled to that context."""
    event_id, order_id, ticket_id = (
        data_in.event_id,
        data_in.order_id,
        data_in.ticket_id,
    )

    if ticket_id:
        row = (
            await db.execute(
                select(Ticket, Attendee, Order)
                .join(Attendee, Attendee.id == Ticket.attendee_id)
                .join(OrderItem, OrderItem.id == Ticket.order_item_id)
                .join(Order, Order.id == OrderItem.order_id)
                .where(Ticket.id == ticket_id)
            )
        ).one_or_none()
        if row is None or (
            row[2].user_id != user.id and row[1].email.lower() != user.email
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        if order_id and order_id != row[2].id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "The ticket is not part of that order"
            )
        order_id = row[2].id

    if order_id:
        order = await db.get(Order, order_id)
        if order is None or (order.user_id != user.id and ticket_id is None):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        if event_id and event_id != order.event_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "The order is not for that event"
            )
        event_id = order.event_id

    if event_id:
        if data_in.audience == CaseAudience.ORGANIZER:
            # Organizers may only cite events they manage
            await event_service.get_managed_event(db, event_id, user)
        else:
            await event_service.get_visible_event(db, event_id, user)
    return event_id, order_id, ticket_id


# --- Responses ----------------------------------------------------------------------


async def _names(db: AsyncSession, ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return dict(rows.all())


async def _summaries(
    db: AsyncSession, cases: list[SupportCase], user: User
) -> list[CaseSummary]:
    names = await _names(
        db,
        {c.requester_user_id for c in cases} | {c.assignee_user_id for c in cases},
    )
    event_ids = {c.event_id for c in cases if c.event_id}
    titles = {}
    if event_ids:
        rows = await db.execute(
            select(Event.id, Event.title).where(Event.id.in_(event_ids))
        )
        titles = dict(rows.all())
    result = []
    for case in cases:
        result.append(
            CaseSummary(
                id=case.id,
                audience=case.audience,
                category=case.category,
                subject=case.subject,
                status=case.status,
                status_label=STATUS_LABELS[CaseStatus(case.status)],
                requester_user_id=case.requester_user_id,
                requester_name=names.get(case.requester_user_id, ""),
                event_id=case.event_id,
                event_title=titles.get(case.event_id) if case.event_id else None,
                order_id=case.order_id,
                ticket_id=case.ticket_id,
                assignee_user_id=case.assignee_user_id,
                assignee_name=names.get(case.assignee_user_id)
                if case.assignee_user_id
                else None,
                is_escalated=case.is_escalated,
                can_manage=await _is_handler(db, case, user),
                created_at=case.created_at,
                updated_at=case.updated_at,
                message_count=len(case.messages),
                last_message_at=case.messages[-1].created_at if case.messages else None,
            )
        )
    return result


async def _detail(db: AsyncSession, case_id: UUID, user: User) -> CaseDetail:
    case = (
        await db.execute(
            select(SupportCase)
            .where(SupportCase.id == case_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    [summary] = await _summaries(db, [case], user)
    return CaseDetail(
        **summary.model_dump(),
        messages=[
            MessageResponse.model_validate(m, from_attributes=True)
            for m in case.messages
        ],
        history=[
            HistoryResponse.model_validate(h, from_attributes=True)
            for h in case.history
        ],
    )


# --- Helpers that write ---------------------------------------------------------


def _history(db: AsyncSession, case: SupportCase, actor: User, action: str) -> None:
    db.add(
        SupportCaseHistory(
            case_id=case.id,
            actor_user_id=actor.id,
            actor_name=actor.full_name,
            action=action,
        )
    )


def _audit(
    db: AsyncSession, case: SupportCase, actor: User, action: AuditAction, text: str
) -> None:
    """Event-linked cases also show on the event timeline (SRS 4.16)."""
    audit.record(
        db,
        actor=actor,
        action=action,
        entity_type=AuditEntity.SUPPORT_CASE,
        entity_id=case.id,
        event_id=case.event_id,
        description=text,
        details={"case_id": case.id, "status": case.status},
    )


async def _notify(
    db: AsyncSession,
    background: BackgroundTasks,
    recipients: list[User],
    kind: str,
    case: SupportCase,
    **params: object,
) -> None:
    """In-app and email, in each recipient's language (SRS 4.10, 4.13)."""
    if not recipients:
        return
    notify(
        db,
        background,
        recipients,
        kind,
        link=f"/support/{case.id}",
        event_id=case.event_id,
        subject=case.subject,
        **params,
    )
    await db.commit()


async def _users(db: AsyncSession, ids: set[UUID]) -> list[User]:
    if not ids:
        return []
    rows = await db.execute(select(User).where(User.id.in_(ids)))
    return list(rows.scalars().all())


# --- Public operations ---------------------------------------------------------


async def open_case(
    db: AsyncSession, user: User, data_in: CaseCreate, background: BackgroundTasks
) -> CaseDetail:
    if data_in.category not in CATEGORIES_BY_AUDIENCE[data_in.audience]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{data_in.category}' is not a category for {data_in.audience} cases",
        )
    event_id, order_id, ticket_id = await _resolve_context(db, user, data_in)
    if data_in.audience == CaseAudience.ATTENDEE and event_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Open attendee support from an event, order or ticket page",
        )
    case = SupportCase(
        audience=data_in.audience,
        category=data_in.category,
        subject=data_in.subject,
        status=CaseStatus.OPEN,
        requester_user_id=user.id,
        event_id=event_id,
        order_id=order_id,
        ticket_id=ticket_id,
    )
    db.add(case)
    await db.flush()
    db.add(
        SupportMessage(
            case_id=case.id,
            sender_user_id=user.id,
            sender_name=user.full_name,
            from_staff=False,
            body=data_in.message,
        )
    )
    _history(db, case, user, "Opened the case")
    _audit(
        db,
        case,
        user,
        AuditAction.SUPPORT_CASE_OPENED,
        f"Support case opened: {case.subject}",
    )
    handlers = await _handler_ids(db, case)
    await db.commit()
    await _notify(
        db,
        background,
        await _users(db, set(handlers) - {user.id}),
        "support_new",
        case,
        actor=user.full_name,
        message=data_in.message,
    )
    return await _detail(db, case.id, user)


async def list_cases(
    db: AsyncSession,
    user: User,
    scope: CaseScope,
    case_status: CaseStatus | None,
    event_id: UUID | None,
) -> list[CaseSummary]:
    conditions = []
    if scope in (CaseScope.REQUESTED, CaseScope.ALL):
        conditions.append(SupportCase.requester_user_id == user.id)
    if scope in (CaseScope.HANDLING, CaseScope.ALL):
        staffed = select(StaffAssignment.event_id).where(
            StaffAssignment.user_id == user.id,
            StaffAssignment.role.in_(EVENT_SUPPORT_ROLES),
        )
        conditions.append(
            (SupportCase.audience == CaseAudience.ATTENDEE)
            & SupportCase.event_id.in_(staffed)
        )
        if user.is_platform_admin:
            conditions.append(SupportCase.audience == CaseAudience.ORGANIZER)
            conditions.append(SupportCase.is_escalated.is_(True))
    query = select(SupportCase).where(or_(*conditions))
    if case_status:
        query = query.where(SupportCase.status == case_status)
    if event_id:
        query = query.where(SupportCase.event_id == event_id)
    cases = (await db.execute(query.order_by(SupportCase.updated_at.desc()))).scalars()
    return await _summaries(db, list(cases), user)


async def get_case(db: AsyncSession, case_id: UUID, user: User) -> CaseDetail:
    await _get_visible(db, case_id, user)
    return await _detail(db, case_id, user)


async def get_messages(
    db: AsyncSession, case_id: UUID, user: User, since: datetime | None
) -> list[MessageResponse]:
    """For lightweight polling (SRS 9): only messages newer than ``since``."""
    await _get_visible(db, case_id, user)
    query = select(SupportMessage).where(SupportMessage.case_id == case_id)
    if since:
        query = query.where(SupportMessage.created_at > since)
    rows = await db.execute(query.order_by(SupportMessage.created_at))
    return [
        MessageResponse.model_validate(m, from_attributes=True) for m in rows.scalars()
    ]


async def post_message(
    db: AsyncSession,
    case_id: UUID,
    user: User,
    body: str,
    background: BackgroundTasks,
) -> CaseDetail:
    case, handler = await _get_visible(db, case_id, user)
    db.add(
        SupportMessage(
            case_id=case.id,
            sender_user_id=user.id,
            sender_name=user.full_name,
            from_staff=handler and case.requester_user_id != user.id,
            body=body,
        )
    )
    if case.status == CaseStatus.RESOLVED:
        # A reply reopens the case; the history is kept
        case.status = CaseStatus.OPEN
        _history(db, case, user, "Reopened the case by replying")
    case.updated_at = _now()
    # Tell the other side: the requester hears from staff and vice versa
    if user.id == case.requester_user_id:
        targets = (
            {case.assignee_user_id}
            if case.assignee_user_id
            else set(await _handler_ids(db, case))
        )
    else:
        targets = {case.requester_user_id}
    targets.discard(user.id)
    targets.discard(None)
    await db.commit()
    await _notify(
        db,
        background,
        await _users(db, targets),  # type: ignore[arg-type]
        "support_reply",
        case,
        actor=user.full_name,
        message=body,
    )
    return await _detail(db, case.id, user)


async def update_case(
    db: AsyncSession,
    case_id: UUID,
    user: User,
    data_in: CaseUpdate,
    background: BackgroundTasks,
) -> CaseDetail:
    case, handler = await _get_visible(db, case_id, user)
    if not handler:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the support team can change this case"
        )
    data = data_in.model_dump(exclude_unset=True)
    pending: list[tuple[set[UUID], str]] = []

    if "assignee_user_id" in data and data["assignee_user_id"] != case.assignee_user_id:
        assignee_id = data["assignee_user_id"]
        if assignee_id is not None:
            handlers = await _handler_ids(db, case)
            if assignee_id not in handlers:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Assign the case to someone on its support team",
                )
            name = (await _names(db, {assignee_id}))[assignee_id]
            _history(db, case, user, f"Assigned to {name}")
            pending.append(({assignee_id} - {user.id}, "support_assigned"))
        else:
            _history(db, case, user, "Unassigned the case")
        case.assignee_user_id = assignee_id
        _audit(
            db,
            case,
            user,
            AuditAction.SUPPORT_CASE_ASSIGNED,
            f"Support case assignment changed: {case.subject}",
        )

    new_status = data.get("status")
    if new_status and new_status != case.status:
        label = STATUS_LABELS[CaseStatus(new_status)]
        _history(db, case, user, f"Changed status to {label}")
        case.status = new_status
        _audit(
            db,
            case,
            user,
            AuditAction.SUPPORT_CASE_STATUS_CHANGED,
            f"Support case status → {label}: {case.subject}",
        )
        pending.append(({case.requester_user_id} - {user.id}, "support_status"))
    case.updated_at = _now()
    await db.commit()
    for recipient_ids, kind in pending:
        for recipient in await _users(db, recipient_ids):
            # The status label goes out in the recipient's own language
            await _notify(
                db,
                background,
                [recipient],
                kind,
                case,
                actor=user.full_name,
                status=t(f"status.{case.status}", recipient.preferred_language),
            )
    return await _detail(db, case.id, user)


async def escalate(
    db: AsyncSession,
    case_id: UUID,
    user: User,
    reason: str,
    background: BackgroundTasks,
) -> CaseDetail:
    """Pass an attendee case to the platform team. The organizer team keeps
    access; platform admins can now answer too."""
    case, handler = await _get_visible(db, case_id, user)
    if case.audience != CaseAudience.ATTENDEE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Organizer cases already go to the platform team",
        )
    if not handler:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the organizer's team can escalate"
        )
    if case.is_escalated:
        raise HTTPException(status.HTTP_409_CONFLICT, "The case is already escalated")
    case.is_escalated = True
    case.updated_at = _now()
    _history(db, case, user, f"Escalated to the platform team: {reason}")
    _audit(
        db,
        case,
        user,
        AuditAction.SUPPORT_CASE_ESCALATED,
        f"Support case escalated: {case.subject}",
    )
    admins = await db.execute(select(User).where(User.is_platform_admin.is_(True)))
    admin_users = list(admins.scalars().all())
    await db.commit()
    await _notify(
        db,
        background,
        admin_users,
        "support_escalated",
        case,
        actor=user.full_name,
        reason=reason,
    )
    return await _detail(db, case.id, user)


async def assignee_options(
    db: AsyncSession, case_id: UUID, user: User
) -> list[AssigneeOption]:
    case, handler = await _get_visible(db, case_id, user)
    if not handler:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the support team can assign this case"
        )
    handlers = await _handler_ids(db, case)
    names = await _names(db, set(handlers))
    return sorted(
        (
            AssigneeOption(user_id=uid, full_name=names.get(uid, ""), role=role)
            for uid, role in handlers.items()
        ),
        key=lambda option: option.full_name,
    )


async def count_open_for_event(db: AsyncSession, event_id: UUID) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                SupportCase.event_id == event_id,
                SupportCase.status != CaseStatus.RESOLVED,
            )
        )
        or 0
    )
