import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)

from app.core.timezones import DEFAULT_TIMEZONE, TimeZoneName
from app.modules.events.enums import (
    EventLifecycle,
    EventStatus,
    EventVisibility,
    SeatingType,
    StaffRole,
)
from app.modules.tickets.schemas import SaleStatus, TicketTypeResponse

# Plain http(s) URL for now; uploads to object storage come later
ImageUrl = Field(None, max_length=1000, pattern=r"^https?://\S+$")


def _check_windows(
    start_at: datetime | None,
    end_at: datetime | None,
    opens_at: datetime | None,
    closes_at: datetime | None,
) -> None:
    if start_at and end_at and end_at <= start_at:
        raise ValueError("end_at must be after start_at")
    if opens_at and closes_at and closes_at <= opens_at:
        raise ValueError("registration_closes_at must be after registration_opens_at")
    if closes_at and end_at and closes_at > end_at:
        raise ValueError("registration_closes_at cannot be after the event ends")


class EventCreate(BaseModel):
    # The organizer profile is taken from the signed-in user
    title: str = Field(..., min_length=3, max_length=255)
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    subtitle: str | None = Field(None, max_length=255)
    description: str | None = None
    cover_image_url: str | None = ImageUrl
    registration_opens_at: AwareDatetime | None = None
    registration_closes_at: AwareDatetime | None = None
    refund_policy: str | None = Field(None, max_length=5000)
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
        if self.seating_type == SeatingType.ASSIGNED:
            # Seating needs a layout; POST /events/{id}/seating sets both
            raise ValueError(
                "Create the event, then choose a layout with POST /events/{id}/seating"
            )
        _check_windows(
            self.start_at,
            self.end_at,
            self.registration_opens_at,
            self.registration_closes_at,
        )
        return self


class EventUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    timezone: TimeZoneName | None = None
    subtitle: str | None = Field(None, max_length=255)
    description: str | None = None
    cover_image_url: str | None = ImageUrl
    registration_opens_at: AwareDatetime | None = None
    registration_closes_at: AwareDatetime | None = None
    refund_policy: str | None = Field(None, max_length=5000)
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
    subtitle: str | None
    description: str | None
    cover_image_url: str | None
    refund_policy: str | None
    status: EventStatus
    lifecycle: EventLifecycle
    visibility: EventVisibility
    seating_type: SeatingType
    start_at: datetime
    end_at: datetime
    timezone: str
    capacity: int
    registration_opens_at: datetime | None
    registration_closes_at: datetime | None
    paid_sales_activated_at: datetime | None
    paid_sales_suspended_at: datetime | None
    paid_sales_open: bool
    is_suspended: bool = False
    venue_layout_id: uuid.UUID | None = None
    published_at: datetime | None
    venue_name: str | None
    venue_address: str | None
    city: str | None
    category: str | None
    created_at: datetime


class PublicEventListItem(EventResponse):
    """An event in the public listing, with what an event card shows."""

    organizer_name: str = ""
    # Lowest price among the visible ticket types; None when there are none
    price_from_kzt: int | None = None
    # Places left across visible ticket types that are on sale now
    tickets_available: int = 0
    # on_sale, scheduled, sold_out or ended (the most hopeful across ticket
    # types); None when the event has no visible ticket types
    sale_state: SaleStatus | None = None


class MyEventResponse(EventResponse):
    """An event the signed-in user works on, with their role on it."""

    my_role: StaffRole


class StaffAssignmentCreate(BaseModel):
    # The account must already exist; owners are assigned at event creation
    email: EmailStr
    role: Literal[StaffRole.MANAGER, StaffRole.CHECKIN_STAFF, StaffRole.SUPPORT_STAFF]


class StaffAssignmentResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    role: StaffRole
    full_name: str
    email: str


class EventSort(StrEnum):
    START_ASC = "start_at"
    START_DESC = "-start_at"


class EventPreviewResponse(BaseModel):
    """The event page as attendees will see it (hidden ticket types left out)."""

    event: EventResponse
    organizer_name: str
    ticket_types: list[TicketTypeResponse]


class EventImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    url: str
    content_type: str
    size_bytes: int
    created_at: datetime
