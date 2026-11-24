from uuid import UUID

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.activation import service as activation_service
from app.modules.activation.schemas import (
    ActivationResponse,
    FeePaymentCreate,
    TermsAcceptance,
)

router = APIRouter(
    prefix="/events/{event_id}/activation", tags=["Paid-sales activation"]
)


@router.get("", response_model=ActivationResponse)
async def get_activation(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """The activation checklist for this event (SRS 4.5). Owner or manager."""
    return await activation_service.get_activation(
        db=db, event_id=event_id, actor=actor
    )


@router.post("/pay-fee", response_model=ActivationResponse)
async def pay_activation_fee(
    event_id: UUID, data_in: FeePaymentCreate, db: DatabaseSession, actor: CurrentUser
):
    """Pay the one-time activation fee (simulated, KZT). Owner only.

    ``outcome=failure`` returns 402 to demonstrate a declined payment.
    """
    return await activation_service.pay_fee(
        db=db, event_id=event_id, actor=actor, outcome=data_in.outcome
    )


@router.post("/accept-terms", response_model=ActivationResponse)
async def accept_terms(
    event_id: UUID, data_in: TermsAcceptance, db: DatabaseSession, actor: CurrentUser
):
    """Accept the paid-event terms; the version must be the current one
    (shown as ``terms_version`` on the checklist). Owner only."""
    return await activation_service.accept_terms(
        db=db, event_id=event_id, actor=actor, terms_version=data_in.terms_version
    )


@router.post("/activate", response_model=ActivationResponse)
async def activate_paid_sales(
    event_id: UUID, db: DatabaseSession, actor: CurrentUser, background: BackgroundTasks
):
    """Open paid ticket sales once every checklist item is done. Owner only.

    Applies to this event alone.
    """
    return await activation_service.activate(
        db=db, event_id=event_id, actor=actor, background=background
    )
