"""Phase 3.5: fixes found when re-checking phases 0–3 against the SRS."""

import pytest
from httpx import AsyncClient

from app.modules.orders.enums import OrderStatus
from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
    event_payload,
)
from tests.orders_helpers import activate_paid_sales, expire_hold, insert_order

pytestmark = pytest.mark.anyio


async def _buy(client: AsyncClient, buyer, event: dict, ticket_type: dict) -> dict:
    response = await client.post(
        f"{API}/events/{event['id']}/orders",
        json={"items": [{"ticket_type_id": ticket_type["id"], "quantity": 1}]},
        headers=buyer.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _event_with(client: AsyncClient, *tickets: dict):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    types = [await add_ticket_type(client, owner, event["id"], **t) for t in tickets]
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    return owner, event, types


# --- Cancelling an event ----------------------------------------------------


async def test_cancel_voids_free_tickets_and_emails_holders(
    client: AsyncClient, sent_emails
):
    owner, event, (free, paid) = await _event_with(
        client, {"name": "Free"}, {"name": "Paid", "price_kzt": 4000}
    )
    await activate_paid_sales(event["id"])
    holder = await create_account(client)
    shopper = await create_account(client)
    ticketed = await _buy(client, holder, event, free)
    pending = await _buy(client, shopper, event, paid)
    sent_emails.clear()

    response = await client.post(
        f"{API}/events/{event['id']}/cancel", headers=owner.headers
    )

    assert response.status_code == 200, response.text
    order = (
        await client.get(f"{API}/orders/{ticketed['id']}", headers=holder.headers)
    ).json()
    assert order["status"] == "cancelled"
    assert [t["status"] for t in order["tickets"]] == ["cancelled"]
    # The open checkout is closed too, so it can no longer be paid
    paid_late = await client.post(
        f"{API}/orders/{pending['id']}/pay", json={}, headers=shopper.headers
    )
    assert paid_late.status_code == 409
    assert [m.to for m in sent_emails] == [holder.email]
    assert "cancelled" in sent_emails[0].subject


# --- Unpublish counts only live orders ---------------------------------------


async def test_unpublish_ignores_expired_and_cancelled_orders(client: AsyncClient):
    owner, event, (ticket_type,) = await _event_with(client, {"price_kzt": 2000})
    await activate_paid_sales(event["id"])
    buyer = await create_account(client)
    expired = await _buy(client, buyer, event, ticket_type)
    await expire_hold(expired["id"])
    await insert_order(
        event["id"],
        buyer.id,
        ticket_type["id"],
        quantity=1,
        status=OrderStatus.CANCELLED,
    )

    response = await client.post(
        f"{API}/events/{event['id']}/unpublish", headers=owner.headers
    )
    assert response.status_code == 200, response.text


# --- Assigned seating is not offered yet ------------------------------------


async def test_assigned_seating_is_set_up_through_the_seating_endpoint(
    client: AsyncClient,
):
    owner = await create_organizer(client)
    response = await client.post(
        f"{API}/events/",
        json=event_payload(seating_type="assigned"),
        headers=owner.headers,
    )
    assert response.status_code == 422
    assert "/seating" in response.text


# --- Event time zone --------------------------------------------------------


async def test_event_time_zone_defaults_and_is_validated(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    assert event["timezone"] == "Asia/Almaty"

    aqtobe = await create_event(client, owner, timezone="Asia/Aqtobe")
    assert aqtobe["timezone"] == "Asia/Aqtobe"

    bad = await client.post(
        f"{API}/events/",
        json=event_payload(timezone="Mars/Olympus"),
        headers=owner.headers,
    )
    assert bad.status_code == 422

    moved = await client.patch(
        f"{API}/events/{event['id']}",
        json={"timezone": "Europe/Moscow"},
        headers=owner.headers,
    )
    assert moved.json()["timezone"] == "Europe/Moscow"


# --- Organizer contact details (SRS 4.1) ------------------------------------


async def test_organizer_contact_details(client: AsyncClient):
    account = await create_account(client)
    created = await client.post(
        f"{API}/organizers/",
        json={
            "display_name": "Steppe Events",
            "contact_email": "hello@steppe.kz",
            "contact_phone": "+7 701 123 45 67",
            "website_url": "https://steppe.kz",
        },
        headers=account.headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["contact_phone"] == "+7 701 123 45 67"

    cleared = await client.patch(
        f"{API}/organizers/me",
        json={"website_url": None, "display_name": None},
        headers=account.headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["website_url"] is None
    assert cleared.json()["display_name"] == "Steppe Events"

    for bad in (
        {"contact_phone": "call me"},
        {"website_url": "ftp://steppe.kz"},
        {"contact_email": "not-an-email"},
    ):
        response = await client.patch(
            f"{API}/organizers/me", json=bad, headers=account.headers
        )
        assert response.status_code == 422, bad
