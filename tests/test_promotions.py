"""Phase 8: promo codes and campaign QR codes (SRS 4.14, UC10)."""

import asyncio
from datetime import UTC, datetime, timedelta

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


async def _event(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, capacity=200)
    standard = await add_ticket_type(
        client, owner, event["id"], name="Standard", price_kzt=10000, quantity=50
    )
    vip = await add_ticket_type(
        client, owner, event["id"], name="VIP", price_kzt=20000, quantity=50
    )
    free = await add_ticket_type(client, owner, event["id"], name="Free", quantity=50)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    return owner, event, {"standard": standard, "vip": vip, "free": free}


async def _campaign(client: AsyncClient, owner, event: dict, **fields) -> dict:
    payload = {"name": "Spring", "discount_type": "percent", "discount_value": 10}
    payload.update(fields)
    response = await client.post(
        f"{API}/events/{event['id']}/campaigns", json=payload, headers=owner.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _items(*pairs) -> list[dict]:
    return [{"ticket_type_id": t["id"], "quantity": q} for t, q in pairs]


async def _order(client: AsyncClient, buyer, event: dict, items, code=None):
    body: dict = {"items": items}
    if code:
        body["promo_code"] = code
    return await client.post(
        f"{API}/events/{event['id']}/orders", json=body, headers=buyer.headers
    )


async def _quote(client: AsyncClient, event: dict, items, code=None):
    body: dict = {"items": items}
    if code:
        body["promo_code"] = code
    response = await client.post(f"{API}/events/{event['id']}/quote", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- Creating campaigns -------------------------------------------------------


async def test_campaign_gets_a_code_and_an_opaque_link(client: AsyncClient):
    owner, event, _ = await _event(client)

    campaign = await _campaign(client, owner, event)

    assert len(campaign["code"]) == 8
    assert not set(campaign["code"]) & set("01OIL")
    assert campaign["discount_label"] == "10% off"
    assert campaign["link_url"].startswith(
        f"http://localhost:3000/events/{event['id']}"
    )
    # The link carries a token, never the code or the discount
    assert campaign["code"] not in campaign["link_url"]
    assert "10" not in campaign["link_url"].split("promo=")[1]
    assert campaign["stats"]["redemptions"] == 0
    assert campaign["remaining_redemptions"] is None


async def test_custom_codes_are_normalised_and_unique_per_event(client: AsyncClient):
    owner, event, _ = await _event(client)
    other_owner, other_event, _ = await _event(client)

    first = await _campaign(client, owner, event, code="steppe-10")
    assert first["code"] == "STEPPE-10"
    duplicate = await client.post(
        f"{API}/events/{event['id']}/campaigns",
        json={
            "name": "Again",
            "discount_type": "fixed",
            "discount_value": 500,
            "code": "STEPPE-10",
        },
        headers=owner.headers,
    )
    assert duplicate.status_code == 409
    # Another event may use the same word
    await _campaign(client, other_owner, other_event, code="STEPPE-10")

    for bad in (
        {"code": "no spaces!"},
        {"discount_value": 150},
        {"starts_at": "2030-01-02T00:00:00Z", "ends_at": "2030-01-01T00:00:00Z"},
    ):
        response = await client.post(
            f"{API}/events/{event['id']}/campaigns",
            json={
                "name": "Bad",
                "discount_type": "percent",
                "discount_value": 10,
                **bad,
            },
            headers=owner.headers,
        )
        assert response.status_code == 422, bad


async def test_only_owner_or_manager_manages_campaigns(client: AsyncClient):
    owner, event, _ = await _event(client)
    outsider = await create_account(client)
    response = await client.post(
        f"{API}/events/{event['id']}/campaigns",
        json={"name": "Hack", "discount_type": "percent", "discount_value": 100},
        headers=outsider.headers,
    )
    assert response.status_code == 403
    campaign = await _campaign(client, owner, event)
    assert (
        await client.get(
            f"{API}/events/{event['id']}/campaigns/{campaign['id']}",
            headers=outsider.headers,
        )
    ).status_code == 403


# --- Quotes and discounts ---------------------------------------------------------


async def test_quote_applies_discount_to_paid_tickets_only(client: AsyncClient):
    owner, event, t = await _event(client)
    campaign = await _campaign(client, owner, event, discount_value=25)

    quote = await _quote(
        client,
        event,
        _items((t["standard"], 2), (t["free"], 1)),
        campaign["code"].lower(),
    )

    assert quote["subtotal_kzt"] == 20000
    assert quote["discount_kzt"] == 5000
    assert quote["total_kzt"] == 15000
    assert quote["promo"]["applied"] is True
    assert quote["promo"]["message"] == "25% off applied"

    unknown = await _quote(client, event, _items((t["standard"], 1)), "NOPE1234")
    assert unknown["promo"] == {
        "code": "NOPE1234",
        "applied": False,
        "message": "This promo code does not exist for this event",
        "campaign_name": None,
    }
    assert unknown["total_kzt"] == 10000

    only_free = await _quote(client, event, _items((t["free"], 2)), campaign["code"])
    assert only_free["promo"]["applied"] is False
    assert "does not apply" in only_free["promo"]["message"]


async def test_campaign_limited_to_some_ticket_types(client: AsyncClient):
    owner, event, t = await _event(client)
    campaign = await _campaign(
        client, owner, event, discount_value=50, ticket_type_ids=[t["vip"]["id"]]
    )

    quote = await _quote(
        client, event, _items((t["standard"], 1), (t["vip"], 1)), campaign["code"]
    )

    assert quote["discount_kzt"] == 10000  # half of the VIP ticket only


async def test_fixed_discount_is_capped_and_can_make_an_order_free(client: AsyncClient):
    owner, event, t = await _event(client)
    campaign = await _campaign(
        client, owner, event, discount_type="fixed", discount_value=50000
    )
    buyer = await create_account(client)

    response = await _order(
        client, buyer, event, _items((t["standard"], 1)), campaign["code"]
    )

    order = response.json()
    assert (order["subtotal_kzt"], order["discount_kzt"], order["total_kzt"]) == (
        10000,
        10000,
        0,
    )
    # Nothing left to pay: confirmed at once, no payment step
    assert order["status"] == "confirmed"
    assert len(order["tickets"]) == 1


# --- Checkout ------------------------------------------------------------------


async def test_checkout_with_code_and_campaign_report(client: AsyncClient, sent_emails):
    owner, event, t = await _event(client)
    campaign = await _campaign(
        client, owner, event, discount_value=20, max_redemptions=5
    )
    buyer = await create_account(client)

    created = await _order(
        client,
        buyer,
        event,
        _items((t["standard"], 2), (t["free"], 1)),
        campaign["code"],
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert (order["subtotal_kzt"], order["discount_kzt"], order["total_kzt"]) == (
        20000,
        4000,
        16000,
    )
    assert order["promo_code"] == campaign["code"]

    sent_emails.clear()
    paid = await client.post(
        f"{API}/orders/{order['id']}/pay", json={}, headers=buyer.headers
    )
    assert paid.json()["payments"][-1]["amount_kzt"] == 16000
    assert campaign["code"] in sent_emails[0].body

    report = (
        await client.get(
            f"{API}/events/{event['id']}/campaigns/{campaign['id']}",
            headers=owner.headers,
        )
    ).json()
    assert report["stats"] == {
        "redemptions": 1,
        "pending_redemptions": 0,
        "tickets_sold": 3,
        "gross_revenue_kzt": 20000,
        "discount_kzt": 4000,
        "net_revenue_kzt": 16000,
    }
    assert report["remaining_redemptions"] == 4


async def test_unusable_codes_are_refused_at_checkout(client: AsyncClient):
    owner, event, t = await _event(client)
    now = datetime.now(UTC)
    expired = await _campaign(
        client,
        owner,
        event,
        name="Old",
        starts_at=(now - timedelta(days=5)).isoformat(),
        ends_at=(now - timedelta(days=1)).isoformat(),
    )
    future = await _campaign(
        client,
        owner,
        event,
        name="Soon",
        starts_at=(now + timedelta(days=3)).isoformat(),
    )
    disabled = await _campaign(client, owner, event, name="Off")
    await client.patch(
        f"{API}/events/{event['id']}/campaigns/{disabled['id']}",
        json={"is_active": False},
        headers=owner.headers,
    )
    buyer = await create_account(client)

    for campaign, message in (
        (expired, "expired"),
        (future, "not valid yet"),
        (disabled, "disabled"),
    ):
        response = await _order(
            client, buyer, event, _items((t["standard"], 1)), campaign["code"]
        )
        assert response.status_code == 400, campaign["name"]
        assert message in response.json()["detail"]


async def test_limit_counts_holds_and_frees_them_on_cancel(client: AsyncClient):
    owner, event, t = await _event(client)
    campaign = await _campaign(client, owner, event, max_redemptions=1)
    first = await create_account(client)
    second = await create_account(client)

    held = await _order(
        client, first, event, _items((t["standard"], 1)), campaign["code"]
    )
    assert held.status_code == 201
    exhausted = await _order(
        client, second, event, _items((t["standard"], 1)), campaign["code"]
    )
    assert exhausted.status_code == 400
    assert "fully redeemed" in exhausted.json()["detail"]

    await client.post(f"{API}/orders/{held.json()['id']}/cancel", headers=first.headers)
    again = await _order(
        client, second, event, _items((t["standard"], 1)), campaign["code"]
    )
    assert again.status_code == 201


async def test_concurrent_checkouts_respect_the_limit(client: AsyncClient):
    owner, event, _ = await _event(client)
    # One ticket type per buyer, so only the campaign lock can serialise them
    types = [
        await add_ticket_type(
            client, owner, event["id"], name=f"Zone {i}", price_kzt=5000, quantity=5
        )
        for i in range(5)
    ]
    campaign = await _campaign(client, owner, event, max_redemptions=2)
    buyers = [await create_account(client) for _ in range(5)]

    responses = await asyncio.gather(
        *(
            _order(client, buyer, event, _items((ticket_type, 1)), campaign["code"])
            for buyer, ticket_type in zip(buyers, types, strict=True)
        )
    )

    assert sorted(r.status_code for r in responses) == [201, 201, 400, 400, 400]


async def test_limit_cannot_drop_below_used(client: AsyncClient):
    owner, event, t = await _event(client)
    campaign = await _campaign(client, owner, event, max_redemptions=5)
    for _ in range(2):
        buyer = await create_account(client)
        await _order(client, buyer, event, _items((t["standard"], 1)), campaign["code"])
    url = f"{API}/events/{event['id']}/campaigns/{campaign['id']}"

    assert (
        await client.patch(url, json={"max_redemptions": 1}, headers=owner.headers)
    ).status_code == 409
    lowered = await client.patch(
        url, json={"max_redemptions": 2}, headers=owner.headers
    )
    assert lowered.json()["remaining_redemptions"] == 0

    timeline = (
        await client.get(
            f"{API}/events/{event['id']}/activity",
            params={"area": "promo"},
            headers=owner.headers,
        )
    ).json()
    assert [e["action"] for e in timeline] == ["promo.updated", "promo.created"]


# --- Campaign QR codes ------------------------------------------------------------


async def test_campaign_link_resolves_and_qr_is_a_png(client: AsyncClient):
    owner, event, t = await _event(client)
    campaign = await _campaign(client, owner, event)
    token = campaign["link_url"].split("promo=")[1]

    resolved = await client.get(f"{API}/promo-links/{token}")
    assert resolved.status_code == 200
    assert resolved.json() == {
        "event_id": event["id"],
        "code": campaign["code"],
        "campaign_name": "Spring",
        "discount_label": "10% off",
    }
    assert (await client.get(f"{API}/promo-links/not-a-token")).status_code == 404

    image = await client.get(
        f"{API}/events/{event['id']}/campaigns/{campaign['id']}/qr.png",
        headers=owner.headers,
    )
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")

    # The admission scanner never accepts the campaign link (SRS 4.14)
    scan = await client.post(
        f"{API}/events/{event['id']}/check-in/scan",
        json={"qr_payload": campaign["link_url"]},
        headers=owner.headers,
    )
    assert scan.json()["result"] == "invalid"
    assert scan.json()["admitted"] is False


async def test_links_for_hidden_events_do_not_resolve(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    await add_ticket_type(client, owner, event["id"], price_kzt=1000)
    campaign = await _campaign(client, owner, event)
    token = campaign["link_url"].split("promo=")[1]
    assert (await client.get(f"{API}/promo-links/{token}")).status_code == 404
