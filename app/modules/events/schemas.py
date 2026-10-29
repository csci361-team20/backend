import uuid
from datetime import datetime

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.modules.events.enums import EventStatus, EventVisibility, SeatingType


class EventCreate(BaseModel):
    # TODO: derive from the current user once JWT lands
    organizer_profile_id: uuid.UUID
    title: str = Field(..., min_length=3, max_length=255)
    description: str | None = None
    visibility: EventVisibility = EventVisibility.PUBLIC
    seating_type: SeatingType = SeatingType.GENERAL_ADMISSION
    start_at: AwareDatetime
    end_at: AwareDatetime
    capacity: int = Field(..., gt=0)
    venue_name: str | None = Field(None, max_length=255)
    venue_address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    category: str | None = Field(None, max_length=50)

    @model_validator(mode="after")
    def validate_dates(self) -> "EventCreate":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class EventUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = None
    visibility: EventVisibility | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    capacity: int | None = Field(None, gt=0)
    venue_name: str | None = Field(None, max_length=255)
    venue_address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    category: str | None = Field(None, max_length=50)


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organizer_profile_id: uuid.UUID
    title: str
    description: str | None
    status: EventStatus
    visibility: EventVisibility
    seating_type: SeatingType
    start_at: datetime
    end_at: datetime
    capacity: int
    paid_sales_activated_at: datetime | None
    venue_name: str | None
    venue_address: str | None
    city: str | None
    category: str | None
    created_at: datetime
