"""Phase 12: organizer analytics (SRS 4.15) and event history (SRS 4.16)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import activate_paid_sales

pytestmark = pytest.mark.anyio


async def _buy(client, buyer, event, lines, code=None, pay=True):
    body: dict = {
        "items": [{"ticket_type_id": t["id"], "quantity": q} for t, q in lines]
    }
    if code:
        body["promo_code"] = code
    order = (
        await client.post(
            f"{API}/events/{event['id']}/orders", json=body, headers=buyer.headers
        )
    ).json()
    if pay and order["status"] == "pending":
        order = (
            await client.post(
                f"{API}/orders/{order['id']}/pay", json={}, headers=buyer.headers
            )
        ).json()
    return order


async def _scan(client, owner, event, buyer, ticket_id):
    payload = (
        await client.get(f"{API}/tickets/{ticket_id}", headers=buyer.headers)
    ).json()["qr_payload"]
    await client.post(
        f"{API}/events/{event['id']}/check-in/scan",
        json={"qr_payload": payload},
        headers=owner.headers,
    )


@pytest.fixture
async def scenario(client: AsyncClient):
    """A known mix of orders whose figures are worked out by hand below."""
    owner = await create_organizer(client)
    event = await create_event(client, owner, capacity=100)
    standard = await add_ticket_type(
        client, owner, event["id"], name="Standard", price_kzt=10000, quantity=40
    )
    vip = await add_ticket_type(
        client, owner, event["id"], name="VIP", price_kzt=25000, quantity=20
    )
    free = await add_ticket_type(client, owner, event["id"], name="Free", quantity=40)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    campaign = (
        await client.post(
            f"{API}/events/{event['id']}/campaigns",
            json={
                "name": "Early",
                "discount_type": "percent",
                "discount_value": 20,
                "ticket_type_ids": [standard["id"]],
            },
            headers=owner.headers,
        )
    ).json()
    a, b, c, d, e = [await create_account(client) for _ in range(5)]

    order_a = await _buy(client, a, event, [(standard, 2)], code=campaign["code"])
    await _buy(client, b, event, [(vip, 1), (standard, 1)])
    order_c = await _buy(client, c, event, [(vip, 1)])
    order_d = await _buy(client, d, event, [(free, 3)])
    await _buy(client, e, event, [(standard, 1)], pay=False)  # unpaid hold
    await client.post(
        f"{API}/orders/{order_c['id']}/refund",
        json={"reason": "Cannot attend"},
        headers=owner.headers,
    )
    await _scan(client, owner, event, a, order_a["tickets"][0]["id"])
    await _scan(client, owner, event, d, order_d["tickets"][0]["id"])
    return {
        "owner": owner,
        "event": event,
        "types": {"standard": standard, "vip": vip, "free": free},
        "campaign": campaign,
    }


async def _analytics(client, account, event, **params):
    response = await client.get(
        f"{API}/events/{event['id']}/analytics", params=params, headers=account.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_dashboard_figures(client: AsyncClient, scenario):
    data = await _analytics(client, scenario["owner"], scenario["event"])

    assert data["is_simulated"] is True and data["currency"] == "KZT"
    # 2 Standard (A) + VIP and Standard (B) + 3 Free (D); C was refunded
    assert data["capacity"] == {
        "capacity": 100,
        "tickets_sold": 7,
        "tickets_remaining": 93,
        "percent_sold": 7.0,
    }
    # Gross 20 000 + 35 000 + 25 000; 20% off A's Standard tickets; C refunded
    assert data["revenue"] == {
        "gross_sales_kzt": 80000,
        "discounts_kzt": 4000,
        "refunds_kzt": 25000,
        "net_revenue_kzt": 51000,
    }
    assert data["attendance"] == {
        "tickets_sold": 7,
        "checked_in": 2,
        "absent": 5,
        "checked_in_percent": 28.6,
    }
    by_type = {row["name"]: row for row in data["by_ticket_type"]}
    assert (
        by_type["Standard"]["tickets_sold"],
        by_type["Standard"]["revenue_kzt"],
    ) == (
        3,
        26000,
    )
    assert (by_type["VIP"]["tickets_sold"], by_type["VIP"]["revenue_kzt"]) == (1, 25000)
    assert (by_type["Free"]["tickets_sold"], by_type["Free"]["checked_in"]) == (3, 1)
    assert data["campaigns"] == [
        {
            "campaign_id": scenario["campaign"]["id"],
            "name": "Early",
            "code": scenario["campaign"]["code"],
            "redemptions": 1,
            "tickets_sold": 2,
            "gross_revenue_kzt": 20000,
            "discount_kzt": 4000,
            "net_revenue_kzt": 16000,
        }
    ]
    # Everything was sold today; the unpaid hold is not a sale
    [today] = data["sales_over_time"]
    assert (today["orders"], today["tickets"], today["revenue_kzt"]) == (4, 8, 76000)


async def test_filters_by_ticket_type_and_date(client: AsyncClient, scenario):
    owner, event = scenario["owner"], scenario["event"]
    vip = await _analytics(
        client, owner, event, ticket_type_id=scenario["types"]["vip"]["id"]
    )
    assert vip["capacity"]["capacity"] == 20
    assert vip["capacity"]["tickets_sold"] == 1
    assert vip["revenue"]["gross_sales_kzt"] == 50000
    assert vip["revenue"]["net_revenue_kzt"] == 25000
    assert [row["name"] for row in vip["by_ticket_type"]] == ["VIP"]
    assert vip["campaigns"] == []

    # Midnight tomorrow in the event's zone, so three days are exactly three
    almaty = ZoneInfo("Asia/Almaty")
    tomorrow = datetime.now(almaty).date() + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time(), almaty)
    future = await _analytics(
        client,
        owner,
        event,
        date_from=start.isoformat(),
        date_to=(start + timedelta(days=3)).isoformat(),
    )
    assert future["revenue"]["gross_sales_kzt"] == 0
    assert future["capacity"]["tickets_sold"] == 0
    # Empty days are filled in, so a chart's axis stays continuous
    assert len(future["sales_over_time"]) == 3
    assert {day["tickets"] for day in future["sales_over_time"]} == {0}

    backwards = await client.get(
        f"{API}/events/{event['id']}/analytics",
        params={"date_from": start.isoformat(), "date_to": start.isoformat()},
        headers=owner.headers,
    )
    assert backwards.status_code == 400


async def test_only_owners_managers_and_admins_see_analytics(
    client: AsyncClient, scenario
):
    event = scenario["event"]
    door = await create_account(client)
    outsider = await create_account(client)
    admin = await create_account(client, admin=True)
    await client.post(
        f"{API}/events/{event['id']}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=scenario["owner"].headers,
    )
    url = f"{API}/events/{event['id']}/analytics"
    assert (await client.get(url, headers=door.headers)).status_code == 403
    assert (await client.get(url, headers=outsider.headers)).status_code == 403
    assert (await client.get(url, headers=admin.headers)).status_code == 200


async def test_overview_lists_the_organizers_events(client: AsyncClient, scenario):
    rows = (
        await client.get(f"{API}/analytics/events", headers=scenario["owner"].headers)
    ).json()
    row = next(r for r in rows if r["event_id"] == scenario["event"]["id"])
    assert (row["tickets_sold"], row["net_revenue_kzt"], row["checked_in"]) == (
        7,
        51000,
        2,
    )


async def test_history_filters_by_action_and_pages(client: AsyncClient, scenario):
    owner, event = scenario["owner"], scenario["event"]
    url = f"{API}/events/{event['id']}/activity"

    refunds = await client.get(
        url, params={"action": "refund.completed"}, headers=owner.headers
    )
    assert [e["action"] for e in refunds.json()] == ["refund.completed"]
    both = await client.get(
        url,
        params=[("action", "check_in.admitted"), ("action", "promo.created")],
        headers=owner.headers,
    )
    assert sorted(e["action"] for e in both.json()) == [
        "check_in.admitted",
        "check_in.admitted",
        "promo.created",
    ]

    everything = (await client.get(url, headers=owner.headers)).json()
    first = (await client.get(url, params={"limit": 3}, headers=owner.headers)).json()
    second = (
        await client.get(url, params={"limit": 3, "offset": 3}, headers=owner.headers)
    ).json()
    assert [e["id"] for e in first + second] == [e["id"] for e in everything[:6]]
    # Every entry carries what SRS 4.16 asks for
    entry = everything[0]
    assert {"created_at", "actor_name", "action", "entity_type", "description"} <= set(
        entry
    )


async def test_past_events_keep_their_records_and_duplicate_cleanly(
    client: AsyncClient, scenario
):
    owner, event = scenario["owner"], scenario["event"]
    await client.post(f"{API}/events/{event['id']}/cancel", headers=owner.headers)

    cancelled = await client.get(
        f"{API}/events/mine", params={"lifecycle": "cancelled"}, headers=owner.headers
    )
    assert event["id"] in [e["id"] for e in cancelled.json()]
    # Records stay reviewable after cancellation (SRS 4.16)
    orders = await client.get(
        f"{API}/events/{event['id']}/orders", headers=owner.headers
    )
    assert len(orders.json()) == 5
    assert (await _analytics(client, owner, event))["revenue"]["refunds_kzt"] > 0

    copy = (
        await client.post(
            f"{API}/events/{event['id']}/duplicate", headers=owner.headers
        )
    ).json()
    assert (
        await client.get(f"{API}/events/{copy['id']}/orders", headers=owner.headers)
    ).json() == []
    assert (
        await client.get(f"{API}/events/{copy['id']}/campaigns", headers=owner.headers)
    ).json() == []
