from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.support import service as support_service
from app.modules.support.enums import CaseScope, CaseStatus
from app.modules.support.schemas import (
    AssigneeOption,
    CaseCreate,
    CaseDetail,
    CaseSummary,
    CaseUpdate,
    EscalationCreate,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(prefix="/support/cases", tags=["Support"])


@router.post("", response_model=CaseDetail, status_code=status.HTTP_201_CREATED)
async def open_case(
    data_in: CaseCreate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Open a support case with a first message.

    Attendees open ``audience=attendee`` cases from an event, order or ticket
    page; organizers open ``audience=organizer`` cases for the platform team.
    """
    return await support_service.open_case(db, actor, data_in, background)


@router.get("", response_model=list[CaseSummary])
async def list_cases(
    db: DatabaseSession,
    actor: CurrentUser,
    scope: CaseScope = CaseScope.ALL,
    case_status: Annotated[CaseStatus | None, Query(alias="status")] = None,
    event_id: UUID | None = None,
):
    """Cases you opened (``requested``), cases you can answer (``handling``),
    or both. Most recently active first."""
    return await support_service.list_cases(db, actor, scope, case_status, event_id)


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: UUID, db: DatabaseSession, actor: CurrentUser):
    return await support_service.get_case(db, case_id, actor)


@router.get("/{case_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    case_id: UUID,
    db: DatabaseSession,
    actor: CurrentUser,
    since: datetime | None = None,
):
    """Poll for new messages: pass the last message's ``created_at``."""
    return await support_service.get_messages(db, case_id, actor, since)


@router.post("/{case_id}/messages", response_model=CaseDetail)
async def post_message(
    case_id: UUID,
    data_in: MessageCreate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Reply in the thread. A reply on a resolved case reopens it."""
    return await support_service.post_message(
        db, case_id, actor, data_in.body, background
    )


@router.patch("/{case_id}", response_model=CaseDetail)
async def update_case(
    case_id: UUID,
    data_in: CaseUpdate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Support team only: assign the case or change its status."""
    return await support_service.update_case(db, case_id, actor, data_in, background)


@router.post("/{case_id}/escalate", response_model=CaseDetail)
async def escalate_case(
    case_id: UUID,
    data_in: EscalationCreate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """The organizer's team passes an attendee case to the platform team."""
    return await support_service.escalate(
        db, case_id, actor, data_in.reason, background
    )


@router.get("/{case_id}/assignees", response_model=list[AssigneeOption])
async def list_assignees(case_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """People the case can be assigned to. Support team only."""
    return await support_service.assignee_options(db, case_id, actor)
