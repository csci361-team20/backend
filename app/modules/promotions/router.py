from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DatabaseSession, OptionalUser
from app.modules.promotions import service as promo_service
from app.modules.promotions.schemas import (
    CampaignCreate,
    CampaignResponse,
    CampaignUpdate,
    PromoLinkResponse,
    QuoteRequest,
    QuoteResponse,
)

router = APIRouter(tags=["Promotions"])


@router.post(
    "/events/{event_id}/campaigns",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    event_id: UUID, data_in: CampaignCreate, db: DatabaseSession, actor: CurrentUser
):
    """Create a campaign with its promo code and QR link. Owner or manager.

    Percentage (1-100) or fixed KZT off, optional dates, redemption limit and
    ticket types. Leave ``code`` out to get a generated one.
    """
    return await promo_service.create_campaign(db, event_id, actor, data_in)


@router.get("/events/{event_id}/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Campaigns with exact redemption and revenue figures. Owner or manager."""
    return await promo_service.list_campaigns(db, event_id, actor)


@router.get(
    "/events/{event_id}/campaigns/{campaign_id}", response_model=CampaignResponse
)
async def get_campaign(
    event_id: UUID, campaign_id: UUID, db: DatabaseSession, actor: CurrentUser
):
    return await promo_service.get_campaign(db, event_id, campaign_id, actor)


@router.patch(
    "/events/{event_id}/campaigns/{campaign_id}", response_model=CampaignResponse
)
async def update_campaign(
    event_id: UUID,
    campaign_id: UUID,
    data_in: CampaignUpdate,
    db: DatabaseSession,
    actor: CurrentUser,
):
    """Rename, change dates or limit, or disable (``is_active: false``)."""
    return await promo_service.update_campaign(
        db, event_id, campaign_id, actor, data_in
    )


@router.get(
    "/events/{event_id}/campaigns/{campaign_id}/qr.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_campaign_qr(
    event_id: UUID, campaign_id: UUID, db: DatabaseSession, actor: CurrentUser
):
    """The campaign QR image: orange frame and a "not a ticket" banner, so it
    is never mistaken for an admission code. Owner or manager."""
    content = await promo_service.get_campaign_qr(db, event_id, campaign_id, actor)
    return Response(content, media_type="image/png")


@router.get("/promo-links/{token}", response_model=PromoLinkResponse)
async def resolve_promo_link(token: str, db: DatabaseSession):
    """Public. What a scanned campaign QR opens: the event and its code, for
    the frontend to apply (the server still validates it at quote/checkout)."""
    return await promo_service.resolve_link(db, token)


@router.post("/events/{event_id}/quote", response_model=QuoteResponse)
async def quote(
    event_id: UUID, data_in: QuoteRequest, db: DatabaseSession, actor: OptionalUser
):
    """Prices and discount before checkout. A rejected code comes back with
    ``promo.applied`` false and a message to show; nothing is reserved."""
    return await promo_service.quote(db, event_id, actor, data_in)
