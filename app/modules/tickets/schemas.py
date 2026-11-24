import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class TicketTypeCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = None
    price_kzt: int = Field(0, ge=0)  # 0 = free ticket
    quantity: int = Field(..., gt=0)
    max_per_order: int = Field(10, gt=0)
    sale_start: AwareDatetime | None = None
    sale_end: AwareDatetime | None = None
    is_hidden: bool = False

    @model_validator(mode="after")
    def validate_sale_window(self) -> "TicketTypeCreate":
        if self.sale_start and self.sale_end and self.sale_end <= self.sale_start:
            raise ValueError("sale_end must be after sale_start")
        return self


class TicketTypeUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = None
    price_kzt: int | None = Field(None, ge=0)
    quantity: int | None = Field(None, gt=0)
    max_per_order: int | None = Field(None, gt=0)
    sale_start: AwareDatetime | None = None
    sale_end: AwareDatetime | None = None
    is_hidden: bool | None = None


class SaleStatus(StrEnum):
    HIDDEN = "hidden"
    SCHEDULED = "scheduled"
    ON_SALE = "on_sale"
    SOLD_OUT = "sold_out"
    ENDED = "ended"


class TicketTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    description: str | None
    price_kzt: int
    quantity: int
    max_per_order: int
    sale_start: datetime | None
    sale_end: datetime | None
    is_hidden: bool
    seat_category: str | None = None
    created_at: datetime
    available: int
    sale_status: SaleStatus


class TicketTypeStats(TicketTypeResponse):
    """Staff view: the full breakdown behind ``available`` (SRS 4.3)."""

    sold: int
    reserved: int
    refunded: int
    checked_in: int


class TicketStatsTotals(BaseModel):
    quantity: int
    available: int
    sold: int
    reserved: int
    refunded: int
    checked_in: int


class EventTicketStats(BaseModel):
    event_id: uuid.UUID
    capacity: int
    ticket_types: list[TicketTypeStats]
    totals: TicketStatsTotals
