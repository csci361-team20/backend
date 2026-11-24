"""Server-side prices and promo discounts (SRS 4.14).

The client never sends a price or a discount: it sends ticket types,
quantities and optionally a code, and this module works out the rest.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.enums import OrderStatus
from app.modules.orders.models import Order
from app.modules.promotions.enums import DiscountType
from app.modules.promotions.models import (
    PromoCode,
    PromoRedemption,
    PromotionalCampaign,
)
from app.modules.tickets.crud import active_hold
from app.modules.tickets.models import TicketType


class PromoError(Exception):
    """A code that cannot be used, with a message fit to show the attendee."""


@dataclass(frozen=True)
class PriceLine:
    ticket_type_id: UUID
    name: str
    unit_price_kzt: int
    quantity: int

    @property
    def subtotal_kzt(self) -> int:
        return self.unit_price_kzt * self.quantity


@dataclass(frozen=True)
class AppliedPromo:
    campaign: PromotionalCampaign
    code: PromoCode
    discount_kzt: int


def normalize_code(code: str) -> str:
    return code.strip().upper()


def lines_for(
    ticket_types: list[TicketType], quantities: dict[UUID, int]
) -> list[PriceLine]:
    return [
        PriceLine(t.id, t.name, t.price_kzt, quantities[t.id])
        for t in ticket_types
        if t.id in quantities
    ]


def describe(campaign: PromotionalCampaign) -> str:
    if campaign.discount_type == DiscountType.PERCENT:
        return f"{campaign.discount_value}% off"
    return f"{campaign.discount_value} KZT off"


async def counted_redemptions(db: AsyncSession, campaign_id: UUID) -> int:
    """Redemptions that use up the limit: confirmed orders and live holds."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(PromoRedemption)
            .join(Order, Order.id == PromoRedemption.order_id)
            .where(
                PromoRedemption.campaign_id == campaign_id,
                or_(Order.status == OrderStatus.CONFIRMED, active_hold()),
            )
        )
        or 0
    )


async def _find(
    db: AsyncSession, event_id: UUID, code: str, lock: bool
) -> tuple[PromotionalCampaign, PromoCode]:
    query = (
        select(PromotionalCampaign, PromoCode)
        .join(PromoCode, PromoCode.campaign_id == PromotionalCampaign.id)
        .where(PromoCode.event_id == event_id, PromoCode.code == normalize_code(code))
    )
    if lock:
        # Serialises redemptions of one campaign so its limit cannot be overrun
        query = query.with_for_update(of=PromotionalCampaign)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise PromoError("This promo code does not exist for this event")
    return row[0], row[1]


def _check_window(campaign: PromotionalCampaign, now: datetime) -> None:
    if not campaign.is_active:
        raise PromoError("This promo code has been disabled")
    if campaign.starts_at and now < campaign.starts_at:
        raise PromoError("This promo code is not valid yet")
    if campaign.ends_at and now >= campaign.ends_at:
        raise PromoError("This promo code has expired")


def compute_discount(campaign: PromotionalCampaign, lines: list[PriceLine]) -> int:
    allowed = {t.id for t in campaign.ticket_types}
    eligible = sum(
        line.subtotal_kzt
        for line in lines
        if line.unit_price_kzt > 0 and (not allowed or line.ticket_type_id in allowed)
    )
    if eligible == 0:
        raise PromoError("This promo code does not apply to the selected tickets")
    if campaign.discount_type == DiscountType.PERCENT:
        return eligible * campaign.discount_value // 100
    return min(campaign.discount_value, eligible)


async def apply_code(
    db: AsyncSession,
    event_id: UUID,
    lines: list[PriceLine],
    code: str,
    *,
    lock: bool,
) -> AppliedPromo:
    """Validate ``code`` for these lines and work out the discount.

    With ``lock`` (checkout), the campaign row stays locked until the caller
    commits, so the redemption limit holds under concurrent checkouts.
    """
    campaign, promo_code = await _find(db, event_id, code, lock)
    _check_window(campaign, datetime.now(UTC))
    discount = compute_discount(campaign, lines)
    if campaign.max_redemptions is not None:
        used = await counted_redemptions(db, campaign.id)
        if used >= campaign.max_redemptions:
            raise PromoError("This promo code has been fully redeemed")
    return AppliedPromo(campaign, promo_code, discount)
