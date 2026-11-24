import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LayoutRow(BaseModel):
    label: str
    seats: int


class LayoutSection(BaseModel):
    name: str
    rows: list[LayoutRow]


class VenueLayoutResponse(BaseModel):
    id: uuid.UUID
    name: str
    address: str | None
    city: str | None
    total_seats: int
    accessible_seats: int
    # Seats per price category, e.g. {"A": 36, "B": 60, "C": 40}
    categories: dict[str, int]
    sections: list[LayoutSection]


class CategoryPrice(BaseModel):
    category: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=2, max_length=100)
    price_kzt: int = Field(..., ge=0)
    max_per_order: int = Field(10, ge=1, le=50)


class SeatingConfigure(BaseModel):
    """Use a predefined layout for this event. One ticket type is created per
    price category, with one ticket per seat in it."""

    venue_id: uuid.UUID
    categories: list[CategoryPrice] = Field(..., min_length=1, max_length=20)

    @field_validator("categories")
    @classmethod
    def unique_categories(cls, value: list[CategoryPrice]) -> list[CategoryPrice]:
        names = [c.category for c in value]
        if len(names) != len(set(names)):
            raise ValueError("Each category may appear only once")
        return value


SeatStatus = Literal["available", "held", "sold", "unavailable"]


class SeatView(BaseModel):
    id: uuid.UUID
    number: str
    category: str
    is_accessible: bool
    status: SeatStatus
    ticket_type_id: uuid.UUID | None
    price_kzt: int | None
    # Screen-reader text, so status never relies on colour alone
    label: str


class SeatRowView(BaseModel):
    label: str
    seats: list[SeatView]


class SeatSectionView(BaseModel):
    name: str
    rows: list[SeatRowView]


class SeatMapResponse(BaseModel):
    """The interactive seat map (SRS 4.3.1). ``selected`` is the client's own
    state; every other status comes from the server."""

    event_id: uuid.UUID
    venue_id: uuid.UUID
    venue_name: str
    sections: list[SeatSectionView]
    counts: dict[str, int]
    legend: dict[str, str]
