import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    Account,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import activate_paid_sales, expire_hold

pytestmark = pytest.mark.anyio


async def _published_event(client: AsyncClient, **ticket: object):
    """An organizer, a published event and one ticket type on it."""
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    ticket_type = await add_ticket_type(client, owner, event["id"], **ticket)
    published = await client.post(
        f"{API}/events/{event['id']}/publish", headers=owner.headers
    )
    assert published.status_code == 200, published.text
    return owner, event, ticket_type


async def _order(
    client: AsyncClient, buyer: Account, event: dict, ticket_type: dict, **body
):
    payload = {"items": [{"ticket_type_id": ticket_type["id"], "quantity": 1}]}
    payload.update(body)
    return await client.post(
        f"{API}/events/{event['id']}/orders", json=payload, headers=buyer.headers
    )


async def _stats_row(client: AsyncClient, owner: Account, event: dict) -> dict:
    response = await client.get(
        f"{API}/events/{event['id']}/ticket-stats", headers=owner.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["ticket_types"][0]


# --- Free registration ------------------------------------------------------


async def test_free_registration_issues_tickets_immediately(
    client: AsyncClient, sent_emails
):
    owner, event, ticket_type = await _published_event(client)
    buyer = await create_account(client, full_name="Dana Sarsen")
    sent_emails.clear()

    response = await _order(
        client,
        buyer,
        event,
        ticket_type,
        items=[{"ticket_type_id": ticket_type["id"], "quantity": 2}],
        attendees=[
            {"name": "Dana Sarsen", "email": "dana@example.kz"},
            {"name": "Aruzhan Bek", "email": "aruzhan@example.kz"},
        ],
    )

    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "confirmed"
    assert order["total_kzt"] == 0
    assert order["expires_at"] is None
    assert order["payments"] == []
    assert [t["attendee_name"] for t in order["tickets"]] == [
        "Dana Sarsen",
        "Aruzhan Bek",
    ]
    assert {t["status"] for t in order["tickets"]} == {"valid"}
    # The buyer gets every ticket; each named attendee gets their own
    assert sorted(m.to for m in sent_emails) == sorted(
        [buyer.email, "dana@example.kz", "aruzhan@example.kz"]
    )
    assert all(event["title"] in m.subject for m in sent_emails)

    attendees = await client.get(
        f"{API}/events/{event['id']}/attendees", headers=owner.headers
    )
    assert sorted(a["attendee_name"] for a in attendees.json()) == [
        "Aruzhan Bek",
        "Dana Sarsen",
    ]
    row = await _stats_row(client, owner, event)
    assert (row["sold"], row["reserved"], row["available"]) == (2, 0, 8)


async def test_tickets_default_to_the_buyer(client: AsyncClient):
    _, event, ticket_type = await _published_event(client)
    buyer = await create_account(client, full_name="Arman Bekov")

    order = (await _order(client, buyer, event, ticket_type)).json()

    assert order["tickets"][0]["attendee_name"] == "Arman Bekov"
    assert order["tickets"][0]["attendee_email"] == buyer.email


async def test_attendee_count_must_match_tickets(client: AsyncClient):
    _, event, ticket_type = await _published_event(client)
    buyer = await create_account(client)
    response = await _order(
        client,
        buyer,
        event,
        ticket_type,
        items=[{"ticket_type_id": ticket_type["id"], "quantity": 2}],
        attendees=[{"name": "Only One", "email": "one@example.kz"}],
    )
    assert response.status_code == 422


# --- Paid checkout ----------------------------------------------------------


async def test_paid_tickets_need_activated_sales(client: AsyncClient):
    _, event, ticket_type = await _published_event(client, price_kzt=5000)
    buyer = await create_account(client)

    response = await _order(client, buyer, event, ticket_type)

    assert response.status_code == 400
    assert "not on sale" in response.json()["detail"]


async def test_paid_checkout_failure_then_success(client: AsyncClient, sent_emails):
    owner, event, ticket_type = await _published_event(client, price_kzt=10000)
    await activate_paid_sales(event["id"])
    buyer = await create_account(client)

    created = await _order(
        client,
        buyer,
        event,
        ticket_type,
        items=[{"ticket_type_id": ticket_type["id"], "quantity": 2}],
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "pending"
    assert order["total_kzt"] == 20000
    assert order["tickets"] == []
    assert order["expires_at"] is not None
    assert (await _stats_row(client, owner, event))["reserved"] == 2

    pay_url = f"{API}/orders/{order['id']}/pay"
    sent_emails.clear()
    failed = await client.post(
        pay_url, json={"outcome": "failure"}, headers=buyer.headers
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "pending"
    assert failed.json()["tickets"] == []
    assert failed.json()["payments"][0]["status"] == "failed"
    assert "failed" in sent_emails[-1].subject.lower()

    paid = await client.post(pay_url, json={}, headers=buyer.headers)
    assert paid.status_code == 200, paid.text
    body = paid.json()
    assert body["status"] == "confirmed"
    assert len(body["tickets"]) == 2
    payment = body["payments"][-1]
    assert payment["status"] == "succeeded"
    assert payment["is_simulated"] is True
    assert payment["processing_fee_kzt"] == 500  # 2.5% of 20 000

    again = await client.post(pay_url, json={}, headers=buyer.headers)
    assert again.status_code == 409

    sales = await client.get(f"{API}/events/{event['id']}/sales", headers=owner.headers)
    assert sales.json() == {
        "event_id": event["id"],
        "currency": "KZT",
        "is_simulated": True,
        "confirmed_orders": 1,
        "tickets_sold": 2,
        "gross_sales_kzt": 20000,
        "processing_fees_kzt": 500,
        "refunds_kzt": 0,
        "estimated_payout_kzt": 19500,
    }


async def test_expired_hold_releases_places_and_cannot_be_paid(client: AsyncClient):
    owner, event, ticket_type = await _published_event(
        client, price_kzt=3000, quantity=1
    )
    await activate_paid_sales(event["id"])
    first = await create_account(client)
    second = await create_account(client)

    order = (await _order(client, first, event, ticket_type)).json()
    assert (await _order(client, second, event, ticket_type)).status_code == 409

    await expire_hold(order["id"])
    assert (await _stats_row(client, owner, event))["available"] == 1
    seen = await client.get(f"{API}/orders/{order['id']}", headers=first.headers)
    assert seen.json()["status"] == "expired"

    late = await client.post(
        f"{API}/orders/{order['id']}/pay", json={}, headers=first.headers
    )
    assert late.status_code == 409
    assert (await _order(client, second, event, ticket_type)).status_code == 201


async def test_cancel_pending_order_releases_places(client: AsyncClient):
    owner, event, ticket_type = await _published_event(client, price_kzt=3000)
    await activate_paid_sales(event["id"])
    buyer = await create_account(client)
    order = (await _order(client, buyer, event, ticket_type)).json()

    cancelled = await client.post(
        f"{API}/orders/{order['id']}/cancel", headers=buyer.headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert (await _stats_row(client, owner, event))["reserved"] == 0

    # A new checkout is allowed once the old one is gone
    assert (await _order(client, buyer, event, ticket_type)).status_code == 201


async def test_one_checkout_at_a_time_per_event(client: AsyncClient):
    _, event, ticket_type = await _published_event(client, price_kzt=3000)
    await activate_paid_sales(event["id"])
    buyer = await create_account(client)

    assert (await _order(client, buyer, event, ticket_type)).status_code == 201
    assert (await _order(client, buyer, event, ticket_type)).status_code == 409


async def test_confirmed_order_cannot_be_cancelled_here(client: AsyncClient):
    _, event, ticket_type = await _published_event(client)
    buyer = await create_account(client)
    order = (await _order(client, buyer, event, ticket_type)).json()

    response = await client.post(
        f"{API}/orders/{order['id']}/cancel", headers=buyer.headers
    )
    assert response.status_code == 409


# --- Stock and sale rules ---------------------------------------------------


async def test_limits_stock_and_sale_window(client: AsyncClient):
    owner, event, ticket_type = await _published_event(
        client, quantity=3, max_per_order=2
    )
    buyer = await create_account(client)
    too_many = await _order(
        client,
        buyer,
        event,
        ticket_type,
        items=[{"ticket_type_id": ticket_type["id"], "quantity": 3}],
    )
    assert too_many.status_code == 400

    hidden = await add_ticket_type(
        client, owner, event["id"], name="Comp", is_hidden=True
    )
    assert (await _order(client, buyer, event, hidden)).status_code == 409

    later = await add_ticket_type(
        client,
        owner,
        event["id"],
        name="Late",
        sale_start=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
    )
    not_yet = await _order(client, buyer, event, later)
    assert not_yet.status_code == 409
    assert "not on sale yet" in not_yet.json()["detail"]


async def test_concurrent_checkouts_never_oversell(client: AsyncClient):
    owner, event, ticket_type = await _published_event(client, quantity=5)
    buyers = [await create_account(client) for _ in range(10)]

    responses = await asyncio.gather(
        *(_order(client, buyer, event, ticket_type) for buyer in buyers)
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] * 5 + [409] * 5
    row = await _stats_row(client, owner, event)
    assert (row["sold"], row["available"]) == (5, 0)


async def test_unavailable_events_refuse_orders(client: AsyncClient):
    owner = await create_organizer(client)
    buyer = await create_account(client)
    draft = await create_event(client, owner)
    ticket_type = await add_ticket_type(client, owner, draft["id"])
    assert (await _order(client, buyer, draft, ticket_type)).status_code == 404

    _, event, ticket_type = await _published_event(client)
    await client.post(f"{API}/events/{event['id']}/cancel", headers=_.headers)
    cancelled = await _order(client, buyer, event, ticket_type)
    assert cancelled.status_code == 400


# --- Who sees what ----------------------------------------------------------


async def test_order_visibility(client: AsyncClient):
    owner, event, ticket_type = await _published_event(client)
    buyer = await create_account(client)
    stranger = await create_account(client)
    door = await create_account(client)
    await client.post(
        f"{API}/events/{event['id']}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )
    order = (await _order(client, buyer, event, ticket_type)).json()
    url = f"{API}/orders/{order['id']}"

    assert (await client.get(url, headers=buyer.headers)).status_code == 200
    assert (await client.get(url, headers=owner.headers)).status_code == 200
    assert (await client.get(url, headers=stranger.headers)).status_code == 404
    assert (await client.get(url, headers=door.headers)).status_code == 404

    mine = await client.get(f"{API}/orders/mine", headers=buyer.headers)
    assert [o["id"] for o in mine.json()] == [order["id"]]
    assert (
        await client.get(f"{API}/orders/mine", headers=stranger.headers)
    ).json() == []

    event_url = f"{API}/events/{event['id']}"
    listed = await client.get(
        f"{event_url}/orders", params={"status": "confirmed"}, headers=owner.headers
    )
    assert [o["id"] for o in listed.json()] == [order["id"]]
    assert (
        await client.get(f"{event_url}/orders", headers=door.headers)
    ).status_code == 403
    assert (
        await client.get(f"{event_url}/sales", headers=door.headers)
    ).status_code == 403

    # Check-in staff may search the attendee list
    found = await client.get(
        f"{event_url}/attendees", params={"q": "test user"}, headers=door.headers
    )
    assert found.status_code == 200
    assert len(found.json()) == 1
