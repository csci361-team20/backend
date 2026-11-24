import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class AnalyticsFilters(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    ticket_type_id: uuid.UUID | None


class CapacityStats(BaseModel):
    capacity: int
    tickets_sold: int
    tickets_remaining: int
    percent_sold: float


class RevenueStats(BaseModel):
    """Demonstration figures in KZT, from BiletFlow's own order records."""

    gross_sales_kzt: int
    discounts_kzt: int
    refunds_kzt: int
    net_revenue_kzt: int


class AttendanceStats(BaseModel):
    tickets_sold: int
    checked_in: int
    absent: int
    checked_in_percent: float


class SalesDay(BaseModel):
    """One day in the event's time zone."""

    date: date
    orders: int
    tickets: int
    revenue_kzt: int


class TicketTypeSales(BaseModel):
    ticket_type_id: uuid.UUID
    name: str
    price_kzt: int
    quantity: int
    tickets_sold: int
    checked_in: int
    revenue_kzt: int


class CampaignSales(BaseModel):
    campaign_id: uuid.UUID
    name: str
    code: str
    redemptions: int
    tickets_sold: int
    gross_revenue_kzt: int
    discount_kzt: int
    net_revenue_kzt: int


class EventAnalytics(BaseModel):
    """The organizer dashboard for one event (SRS 4.15)."""

    event_id: uuid.UUID
    event_title: str
    lifecycle: str
    timezone: str
    currency: Literal["KZT"] = "KZT"
    is_simulated: bool = True
    filters: AnalyticsFilters
    capacity: CapacityStats
    revenue: RevenueStats
    attendance: AttendanceStats
    sales_over_time: list[SalesDay]
    by_ticket_type: list[TicketTypeSales]
    campaigns: list[CampaignSales]


class EventOverviewRow(BaseModel):
    event_id: uuid.UUID
    title: str
    lifecycle: str
    start_at: datetime
    capacity: int
    tickets_sold: int
    percent_sold: float
    checked_in: int
    net_revenue_kzt: int
