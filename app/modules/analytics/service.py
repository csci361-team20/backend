"""Organizer analytics (SRS 4.15).

Every figure comes from BiletFlow's own orders, tickets, campaigns, refunds
and check-ins; attendees are never asked for extra data. Queries only read,
so they never hold locks that checkout or check-in wait for.

Money is counted per order line. A promo discount is shared between an
order's lines in proportion to their value, so filtering by ticket type
still gives a fair net figure.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.schemas import (
    AnalyticsFilters,
    AttendanceStats,
    CampaignSales,
    CapacityStats,
    EventAnalytics,
    EventOverviewRow,
    RevenueStats,
    SalesDay,
    TicketTypeSales,
)
from app.modules.events import service as event_service
from app.modules.events.models import Event
from app.modules.events.permissions import MANAGE_ROLES
from app.modules.orders.enums import OrderStatus, TicketStatus
from app.modules.orders.models import Order, OrderItem, Ticket
from app.modules.promotions.models import PromoCode, PromotionalCampaign
from app.modules.tickets.models import TicketType
from app.modules.users.models import User

# Orders that were completed: still confirmed, or paid and later refunded
COMPLETED = (OrderStatus.CONFIRMED, OrderStatus.REFUNDED)
SOLD = (TicketStatus.VALID, TicketStatus.CHECKED_IN)
MAX_DAYS = 366


@dataclass
class _Line:
    order: Order
    item: OrderItem

    @property
    def gross(self) -> int:
        return self.item.unit_price_kzt * self.item.quantity

    @property
    def discount(self) -> float:
        if not self.order.discount_kzt or not self.order.subtotal_kzt:
            return 0.0
        return self.order.discount_kzt * self.gross / self.order.subtotal_kzt

    @property
    def refunded(self) -> float:
        if self.order.status != OrderStatus.REFUNDED:
            return 0.0
        return self.gross - self.discount

    @property
    def net(self) -> float:
        return self.gross - self.discount - self.refunded


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


async def _lines(
    db: AsyncSession,
    event_id: UUID,
    date_from: datetime | None,
    date_to: datetime | None,
    ticket_type_id: UUID | None,
) -> list[_Line]:
    moment = func.coalesce(Order.confirmed_at, Order.created_at)
    query = (
        select(Order, OrderItem)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.event_id == event_id, Order.status.in_(COMPLETED))
    )
    if date_from:
        query = query.where(moment >= date_from)
    if date_to:
        query = query.where(moment < date_to)
    if ticket_type_id:
        query = query.where(OrderItem.ticket_type_id == ticket_type_id)
    rows = await db.execute(query)
    return [_Line(order, item) for order, item in rows.all()]


async def _ticket_counts(
    db: AsyncSession, item_ids: list[UUID]
) -> dict[UUID, dict[str, int]]:
    """{order_item_id: {status: count}} for the given lines."""
    counts: dict[UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if not item_ids:
        return counts
    rows = await db.execute(
        select(Ticket.order_item_id, Ticket.status, func.count())
        .where(Ticket.order_item_id.in_(item_ids))
        .group_by(Ticket.order_item_id, Ticket.status)
    )
    for item_id, ticket_status, count in rows.all():
        counts[item_id][ticket_status] = count
    return counts


def _local_day(moment: datetime, zone: ZoneInfo) -> date:
    return moment.astimezone(zone).date()


def _sales_over_time(
    lines: list[_Line],
    zone: ZoneInfo,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[SalesDay]:
    """Daily orders, tickets and net revenue, with empty days filled in so a
    chart's x-axis is continuous."""
    tickets: dict[date, int] = defaultdict(int)
    revenue: dict[date, float] = defaultdict(float)
    orders: dict[date, set[UUID]] = defaultdict(set)
    for line in lines:
        day = _local_day(line.order.confirmed_at or line.order.created_at, zone)
        tickets[day] += line.item.quantity
        # Sales over time shows what was sold that day; refunds are separate
        revenue[day] += line.gross - line.discount
        orders[day].add(line.order.id)
    if not tickets and not (date_from and date_to):
        return []
    days = sorted(tickets)
    first = _local_day(date_from, zone) if date_from else days[0]
    last = (
        _local_day(date_to - timedelta(microseconds=1), zone) if date_to else days[-1]
    )
    if (last - first).days > MAX_DAYS:
        first = last - timedelta(days=MAX_DAYS)
    series, day = [], first
    while day <= last:
        series.append(
            SalesDay(
                date=day,
                orders=len(orders.get(day, ())),
                tickets=tickets.get(day, 0),
                revenue_kzt=round(revenue.get(day, 0.0)),
            )
        )
        day += timedelta(days=1)
    return series


async def event_analytics(
    db: AsyncSession,
    event_id: UUID,
    actor: User,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    ticket_type_id: UUID | None = None,
) -> EventAnalytics:
    """Owner, manager or platform admin of the event (SRS 4.15)."""
    event = await event_service.get_managed_event(db, event_id, actor, MANAGE_ROLES)
    return await _build(db, event, date_from, date_to, ticket_type_id)


async def _build(
    db: AsyncSession,
    event: Event,
    date_from: datetime | None,
    date_to: datetime | None,
    ticket_type_id: UUID | None,
) -> EventAnalytics:
    zone = ZoneInfo(event.timezone)
    ticket_types = list(
        (
            await db.execute(
                select(TicketType)
                .where(TicketType.event_id == event.id)
                .order_by(TicketType.price_kzt, TicketType.name)
            )
        ).scalars()
    )
    if ticket_type_id:
        ticket_types = [t for t in ticket_types if t.id == ticket_type_id]

    lines = await _lines(db, event.id, date_from, date_to, ticket_type_id)
    counts = await _ticket_counts(db, [line.item.id for line in lines])

    def sold_of(item_id: UUID) -> int:
        return sum(counts[item_id].get(s, 0) for s in SOLD)

    tickets_sold = sum(sold_of(line.item.id) for line in lines)
    checked_in = sum(
        counts[line.item.id].get(TicketStatus.CHECKED_IN, 0) for line in lines
    )
    capacity = (
        sum(t.quantity for t in ticket_types) if ticket_type_id else event.capacity
    )

    by_type: list[TicketTypeSales] = []
    for ticket_type in ticket_types:
        own = [line for line in lines if line.item.ticket_type_id == ticket_type.id]
        by_type.append(
            TicketTypeSales(
                ticket_type_id=ticket_type.id,
                name=ticket_type.name,
                price_kzt=ticket_type.price_kzt,
                quantity=ticket_type.quantity,
                tickets_sold=sum(sold_of(line.item.id) for line in own),
                checked_in=sum(
                    counts[line.item.id].get(TicketStatus.CHECKED_IN, 0) for line in own
                ),
                revenue_kzt=round(sum(line.net for line in own)),
            )
        )

    campaign_lines: dict[UUID, list[_Line]] = defaultdict(list)
    for line in lines:
        if line.order.campaign_id and line.order.status == OrderStatus.CONFIRMED:
            campaign_lines[line.order.campaign_id].append(line)
    campaigns: list[CampaignSales] = []
    if campaign_lines:
        rows = await db.execute(
            select(PromotionalCampaign.id, PromotionalCampaign.name, PromoCode.code)
            .join(PromoCode, PromoCode.campaign_id == PromotionalCampaign.id)
            .where(PromotionalCampaign.id.in_(campaign_lines))
        )
        for campaign_id, name, code in rows.all():
            own = campaign_lines[campaign_id]
            gross = sum(line.gross for line in own)
            discount = round(sum(line.discount for line in own))
            campaigns.append(
                CampaignSales(
                    campaign_id=campaign_id,
                    name=name,
                    code=code,
                    redemptions=len({line.order.id for line in own}),
                    tickets_sold=sum(sold_of(line.item.id) for line in own),
                    gross_revenue_kzt=gross,
                    discount_kzt=discount,
                    net_revenue_kzt=gross - discount,
                )
            )
        campaigns.sort(key=lambda c: c.net_revenue_kzt, reverse=True)

    gross = sum(line.gross for line in lines)
    discounts = round(sum(line.discount for line in lines))
    refunds = round(sum(line.refunded for line in lines))
    return EventAnalytics(
        event_id=event.id,
        event_title=event.title,
        lifecycle=event.lifecycle,
        timezone=event.timezone,
        filters=AnalyticsFilters(
            date_from=date_from, date_to=date_to, ticket_type_id=ticket_type_id
        ),
        capacity=CapacityStats(
            capacity=capacity,
            tickets_sold=tickets_sold,
            tickets_remaining=max(capacity - tickets_sold, 0),
            percent_sold=_pct(tickets_sold, capacity),
        ),
        revenue=RevenueStats(
            gross_sales_kzt=gross,
            discounts_kzt=discounts,
            refunds_kzt=refunds,
            net_revenue_kzt=gross - discounts - refunds,
        ),
        attendance=AttendanceStats(
            tickets_sold=tickets_sold,
            checked_in=checked_in,
            absent=tickets_sold - checked_in,
            checked_in_percent=_pct(checked_in, tickets_sold),
        ),
        sales_over_time=_sales_over_time(lines, zone, date_from, date_to),
        by_ticket_type=by_type,
        campaigns=campaigns,
    )


async def overview(db: AsyncSession, actor: User) -> list[EventOverviewRow]:
    """One row per event the user owns or manages, newest first."""
    events = await event_service.get_my_events(db, actor)
    rows = []
    for mine in events:
        event = await db.get(Event, mine.id)
        assert event is not None
        stats = await _build(db, event, None, None, None)
        rows.append(
            EventOverviewRow(
                event_id=event.id,
                title=event.title,
                lifecycle=event.lifecycle,
                start_at=event.start_at,
                capacity=stats.capacity.capacity,
                tickets_sold=stats.capacity.tickets_sold,
                percent_sold=stats.capacity.percent_sold,
                checked_in=stats.attendance.checked_in,
                net_revenue_kzt=stats.revenue.net_revenue_kzt,
            )
        )
    return rows


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)
