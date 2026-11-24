import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from app.modules.orders.schemas import OrderItemCreate
from app.modules.promotions.enums import DiscountType

_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{3,31}$")


class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    discount_type: DiscountType
    discount_value: int = Field(..., ge=1)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    max_redemptions: int | None = Field(None, ge=1)
    # Empty or left out = every paid ticket type of the event
    ticket_type_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    # Leave out to get a generated code
    code: str | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not _CODE.match(value):
            raise ValueError("Codes are 4-32 letters, digits or dashes")
        return value

    @model_validator(mode="after")
    def validate_campaign(self) -> "CampaignCreate":
        if self.discount_type == DiscountType.PERCENT and self.discount_value > 100:
            raise ValueError("A percentage discount can be at most 100")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class CampaignUpdate(BaseModel):
    """Disable with ``is_active: false``. The discount itself cannot change
    once created, so attendees and reports stay consistent."""

    name: str | None = Field(None, min_length=2, max_length=100)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    max_redemptions: int | None = Field(None, ge=1)
    is_active: bool | None = None


class CampaignStats(BaseModel):
    """Exact figures from confirmed orders (SRS 4.14). Demonstration data."""

    redemptions: int
    pending_redemptions: int
    tickets_sold: int
    gross_revenue_kzt: int
    discount_kzt: int
    net_revenue_kzt: int


class CampaignResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    code: str
    discount_type: DiscountType
    discount_value: int
    discount_label: str
    starts_at: datetime | None
    ends_at: datetime | None
    max_redemptions: int | None
    remaining_redemptions: int | None
    is_active: bool
    ticket_type_ids: list[uuid.UUID]
    # Encode this in the campaign QR; it opens the event page with the code
    link_url: str
    created_at: datetime
    stats: CampaignStats


class QuoteRequest(BaseModel):
    """Same shape as checkout: ``items`` or, for a seated event, ``seat_ids``."""

    items: list[OrderItemCreate] = Field(default_factory=list, max_length=20)
    seat_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    promo_code: str | None = Field(None, max_length=32)

    @model_validator(mode="after")
    def one_selection(self) -> "QuoteRequest":
        if bool(self.items) == bool(self.seat_ids):
            raise ValueError("Send either items or seat_ids")
        if len(self.seat_ids) != len(set(self.seat_ids)):
            raise ValueError("Each seat may appear only once")
        return self


class QuoteLine(BaseModel):
    ticket_type_id: uuid.UUID
    name: str
    unit_price_kzt: int
    quantity: int
    subtotal_kzt: int


class QuotePromo(BaseModel):
    code: str
    applied: bool
    message: str
    campaign_name: str | None = None


class QuoteResponse(BaseModel):
    """What checkout would charge right now. Not a reservation."""

    lines: list[QuoteLine]
    subtotal_kzt: int
    discount_kzt: int
    total_kzt: int
    currency: Literal["KZT"] = "KZT"
    promo: QuotePromo | None = None


class PromoLinkResponse(BaseModel):
    """What a campaign QR link resolves to; the frontend then applies ``code``."""

    event_id: uuid.UUID
    code: str
    campaign_name: str
    discount_label: str
