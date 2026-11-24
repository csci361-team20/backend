"""Promotional campaigns, codes, campaign QR codes and quotes (SRS 4.14)."""

import io
import secrets
from uuid import UUID

import qrcode
from fastapi import HTTPException, status
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.events import service as event_service
from app.modules.events.models import Event
from app.modules.events.permissions import is_publicly_visible
from app.modules.orders.enums import OrderStatus, TicketStatus
from app.modules.orders.models import Order, OrderItem, Ticket
from app.modules.orders.ticket_pdf import unicode_font_paths
from app.modules.promotions import pricing
from app.modules.promotions.models import PromoCode, PromotionalCampaign
from app.modules.promotions.schemas import (
    CampaignCreate,
    CampaignResponse,
    CampaignStats,
    CampaignUpdate,
    PromoLinkResponse,
    QuoteLine,
    QuotePromo,
    QuoteRequest,
    QuoteResponse,
)
from app.modules.seating import service as seating_service
from app.modules.tickets import crud as tickets_crud
from app.modules.tickets.crud import active_hold
from app.modules.tickets.models import TicketType
from app.modules.users.models import User

# No 0/O or 1/I/L, so codes read back unambiguously over the phone
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PROMO_COLOR = (194, 65, 12)  # orange frame: never confused with a black ticket QR


def link_url(event_id: UUID, token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/events/{event_id}?promo={token}"


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


async def _stats(db: AsyncSession, campaign: PromotionalCampaign) -> CampaignStats:
    confirmed = (
        await db.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.subtotal_kzt), 0),
                func.coalesce(func.sum(Order.discount_kzt), 0),
                func.coalesce(func.sum(Order.total_kzt), 0),
            ).where(
                Order.campaign_id == campaign.id,
                Order.status == OrderStatus.CONFIRMED,
            )
        )
    ).one()
    pending = await db.scalar(
        select(func.count(Order.id)).where(
            Order.campaign_id == campaign.id, active_hold()
        )
    )
    tickets = await db.scalar(
        select(func.count(Ticket.id))
        .join(OrderItem, OrderItem.id == Ticket.order_item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.campaign_id == campaign.id,
            Ticket.status.in_((TicketStatus.VALID, TicketStatus.CHECKED_IN)),
        )
    )
    redemptions, gross, discount, net = confirmed
    return CampaignStats(
        redemptions=int(redemptions),
        pending_redemptions=int(pending or 0),
        tickets_sold=int(tickets or 0),
        gross_revenue_kzt=int(gross),
        discount_kzt=int(discount),
        net_revenue_kzt=int(net),
    )


async def _response(
    db: AsyncSession, campaign: PromotionalCampaign
) -> CampaignResponse:
    stats = await _stats(db, campaign)
    remaining = None
    if campaign.max_redemptions is not None:
        used = stats.redemptions + stats.pending_redemptions
        remaining = max(campaign.max_redemptions - used, 0)
    return CampaignResponse(
        id=campaign.id,
        event_id=campaign.event_id,
        name=campaign.name,
        code=campaign.promo_code.code,
        discount_type=campaign.discount_type,
        discount_value=campaign.discount_value,
        discount_label=pricing.describe(campaign),
        starts_at=campaign.starts_at,
        ends_at=campaign.ends_at,
        max_redemptions=campaign.max_redemptions,
        remaining_redemptions=remaining,
        is_active=campaign.is_active,
        ticket_type_ids=[t.id for t in campaign.ticket_types],
        link_url=link_url(campaign.event_id, campaign.link_token),
        created_at=campaign.created_at,
        stats=stats,
    )


async def _get(
    db: AsyncSession, event_id: UUID, campaign_id: UUID
) -> PromotionalCampaign:
    campaign = await db.get(PromotionalCampaign, campaign_id)
    if campaign is None or campaign.event_id != event_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return campaign


def _log(
    db: AsyncSession,
    actor: User,
    action: AuditAction,
    campaign: PromotionalCampaign,
    description: str,
    details: dict | None = None,
) -> None:
    audit.record(
        db,
        actor=actor,
        action=action,
        entity_type=AuditEntity.CAMPAIGN,
        entity_id=campaign.id,
        event_id=campaign.event_id,
        description=description,
        details=details,
    )


# --- Organizer actions ------------------------------------------------------------


async def create_campaign(
    db: AsyncSession, event_id: UUID, actor: User, data_in: CampaignCreate
) -> CampaignResponse:
    event = await event_service.get_managed_event(db, event_id, actor)
    ticket_types: list[TicketType] = []
    if data_in.ticket_type_ids:
        ticket_types = list(
            (
                await db.execute(
                    select(TicketType).where(
                        TicketType.id.in_(data_in.ticket_type_ids),
                        TicketType.event_id == event.id,
                    )
                )
            ).scalars()
        )
        if len(ticket_types) != len(set(data_in.ticket_type_ids)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Every ticket type must belong to this event",
            )
        if all(t.price_kzt == 0 for t in ticket_types):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A discount needs at least one paid ticket type",
            )
    code = data_in.code or _generate_code()
    campaign = PromotionalCampaign(
        event_id=event.id,
        name=data_in.name,
        discount_type=data_in.discount_type,
        discount_value=data_in.discount_value,
        starts_at=data_in.starts_at,
        ends_at=data_in.ends_at,
        max_redemptions=data_in.max_redemptions,
        link_token=secrets.token_urlsafe(16)[:22],
        created_by_user_id=actor.id,
        ticket_types=ticket_types,
    )
    db.add(campaign)
    await db.flush()
    db.add(PromoCode(campaign_id=campaign.id, event_id=event.id, code=code))
    _log(
        db,
        actor,
        AuditAction.CAMPAIGN_CREATED,
        campaign,
        f"Created promo code {code} ({pricing.describe(campaign)}) for {data_in.name}",
        {"code": code, "max_redemptions": data_in.max_redemptions},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"The code {code} is already used for this event"
        ) from None
    await db.refresh(campaign)
    return await _response(db, campaign)


async def update_campaign(
    db: AsyncSession,
    event_id: UUID,
    campaign_id: UUID,
    actor: User,
    data_in: CampaignUpdate,
) -> CampaignResponse:
    await event_service.get_managed_event(db, event_id, actor)
    campaign = await _get(db, event_id, campaign_id)
    data = data_in.model_dump(exclude_unset=True)
    data = {
        k: v
        for k, v in data.items()
        if v is not None or k in ("starts_at", "ends_at", "max_redemptions")
    }
    starts = data.get("starts_at", campaign.starts_at)
    ends = data.get("ends_at", campaign.ends_at)
    if starts and ends and ends <= starts:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "ends_at must be after starts_at"
        )
    if data.get("max_redemptions") is not None:
        used = await pricing.counted_redemptions(db, campaign.id)
        if data["max_redemptions"] < used:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{used} redemptions are already used or held; "
                "the limit cannot be lower",
            )
    changed = audit.changes(campaign, data)
    if changed:
        disabled = changed.get("is_active", {}).get("to") is False
        action = (
            AuditAction.CAMPAIGN_DISABLED if disabled else AuditAction.CAMPAIGN_UPDATED
        )
        verb = "Disabled" if disabled else "Changed"
        _log(
            db,
            actor,
            action,
            campaign,
            f"{verb} promo code {campaign.promo_code.code}",
            {"changes": changed},
        )
        for field, value in data.items():
            setattr(campaign, field, value)
        await db.commit()
        await db.refresh(campaign)
    return await _response(db, campaign)


async def list_campaigns(
    db: AsyncSession, event_id: UUID, actor: User
) -> list[CampaignResponse]:
    await event_service.get_managed_event(db, event_id, actor)
    campaigns = (
        await db.execute(
            select(PromotionalCampaign)
            .where(PromotionalCampaign.event_id == event_id)
            .order_by(PromotionalCampaign.created_at.desc())
        )
    ).scalars()
    return [await _response(db, c) for c in campaigns]


async def get_campaign(
    db: AsyncSession, event_id: UUID, campaign_id: UUID, actor: User
) -> CampaignResponse:
    await event_service.get_managed_event(db, event_id, actor)
    return await _response(db, await _get(db, event_id, campaign_id))


# --- Campaign QR codes -------------------------------------------------------------


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = unicode_font_paths()
    if paths is not None:
        return ImageFont.truetype(paths[1], size)
    return ImageFont.load_default(size=size)


def render_campaign_qr(url: str, code: str, discount_label: str) -> bytes:
    """A PNG that cannot be mistaken for an admission ticket (SRS 4.14).

    Orange frame and a "PROMO, NOT A TICKET" banner; the QR itself holds only
    the https link, which every scanner rejects as an admission code.
    """
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2
    )
    qr.add_data(url)
    qr.make(fit=True)
    code_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    pad, frame, banner = 30, 14, 150
    width = code_image.width + 2 * (pad + frame)
    height = code_image.height + 2 * (pad + frame) + banner
    canvas = Image.new("RGB", (width, height), PROMO_COLOR)
    inner = Image.new("RGB", (width - 2 * frame, height - 2 * frame), "white")
    canvas.paste(inner, (frame, frame))
    canvas.paste(code_image, (frame + pad, frame + pad))

    draw = ImageDraw.Draw(canvas)
    top = frame + pad + code_image.height + 18
    for text, size, color in (
        ("PROMO CODE · NOT A TICKET", 30, PROMO_COLOR),
        (f"{code}  ·  {discount_label}", 26, (20, 20, 20)),
    ):
        font = _font(size)
        text_width = draw.textlength(text, font=font)
        draw.text(((width - text_width) / 2, top), text, fill=color, font=font)
        top += size + 22
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def get_campaign_qr(
    db: AsyncSession, event_id: UUID, campaign_id: UUID, actor: User
) -> bytes:
    await event_service.get_managed_event(db, event_id, actor)
    campaign = await _get(db, event_id, campaign_id)
    return render_campaign_qr(
        link_url(campaign.event_id, campaign.link_token),
        campaign.promo_code.code,
        pricing.describe(campaign),
    )


async def resolve_link(db: AsyncSession, token: str) -> PromoLinkResponse:
    """Public: what a scanned campaign QR opens. Only live campaigns of events
    anyone can see resolve; everything else is 404."""
    campaign = await db.scalar(
        select(PromotionalCampaign).where(PromotionalCampaign.link_token == token)
    )
    event = await db.get(Event, campaign.event_id) if campaign else None
    if campaign is None or event is None or not is_publicly_visible(event):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This promotion link is not valid"
        )
    return PromoLinkResponse(
        event_id=event.id,
        code=campaign.promo_code.code,
        campaign_name=campaign.name,
        discount_label=pricing.describe(campaign),
    )


# --- Quotes ------------------------------------------------------------------------


async def quote(
    db: AsyncSession, event_id: UUID, actor: User | None, data_in: QuoteRequest
) -> QuoteResponse:
    """Prices with the promo code applied, before checkout (SRS 4.14)."""
    event = await event_service.get_visible_event(db, event_id, actor)
    quantities = {item.ticket_type_id: item.quantity for item in data_in.items}
    if data_in.seat_ids:
        seats = await seating_service.resolve_seats(db, event, data_in.seat_ids)
        by_category = {
            t.seat_category: t.id
            for t in await tickets_crud.get_by_event(db, event.id)
            if t.seat_category
        }
        if any(seat.category not in by_category for seat in seats):
            raise HTTPException(status.HTTP_409_CONFLICT, "That seat is not on sale")
        for seat in seats:
            ticket_type_id = by_category[seat.category]
            quantities[ticket_type_id] = quantities.get(ticket_type_id, 0) + 1
    ticket_types = list(
        (
            await db.execute(
                select(TicketType).where(
                    TicketType.id.in_(quantities),
                    TicketType.event_id == event.id,
                    TicketType.is_hidden.is_(False),
                )
            )
        ).scalars()
    )
    if len(ticket_types) != len(quantities):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ticket type not found for this event"
        )
    lines = pricing.lines_for(ticket_types, quantities)
    subtotal = sum(line.subtotal_kzt for line in lines)
    discount, promo = 0, None
    if data_in.promo_code:
        code = pricing.normalize_code(data_in.promo_code)
        try:
            applied = await pricing.apply_code(db, event.id, lines, code, lock=False)
        except pricing.PromoError as error:
            promo = QuotePromo(code=code, applied=False, message=str(error))
        else:
            discount = applied.discount_kzt
            promo = QuotePromo(
                code=code,
                applied=True,
                message=f"{pricing.describe(applied.campaign)} applied",
                campaign_name=applied.campaign.name,
            )
    return QuoteResponse(
        lines=[
            QuoteLine(
                ticket_type_id=line.ticket_type_id,
                name=line.name,
                unit_price_kzt=line.unit_price_kzt,
                quantity=line.quantity,
                subtotal_kzt=line.subtotal_kzt,
            )
            for line in lines
        ],
        subtotal_kzt=subtotal,
        discount_kzt=discount,
        total_kzt=subtotal - discount,
        promo=promo,
    )
