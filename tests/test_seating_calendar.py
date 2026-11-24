"""Phase 13 (bonus): assigned seating (SRS 4.3.1, UC8) and calendar export."""

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import activate_paid_sales, expire_hold

pytestmark = pytest.mark.anyio

PRICES = [
    {"category": "A", "name": "Stalls front", "price_kzt": 9000},
    {"category": "B", "name": "Stalls back", "price_kzt": 6000},
    {"category": "C", "name": "Balcony", "price_kzt": 0},
]


async def _hall(client: AsyncClient, account) -> dict:
    response = await client.get(f"{API}/venue-layouts", headers=account.headers)
    assert response.status_code == 200, response.text
    return next(v for v in response.json() if v["name"] == "BiletFlow Hall")


async def _seated_event(client: AsyncClient, *, publish: bool = True):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    hall = await _hall(client, owner)
    response = await client.post(
        f"{API}/events/{event['id']}/seating",
        json={"venue_id": hall["id"], "categories": PRICES},
        headers=owner.headers,
    )
    assert response.status_code == 200, response.text
    if publish:
        published = await client.post(
            f"{API}/events/{event['id']}/publish", headers=owner.headers
        )
        assert published.status_code == 200, published.text
        await activate_paid_sales(event["id"])
    return owner, event, response.json()


async def _map(client: AsyncClient, event: dict) -> dict:
    response = await client.get(f"{API}/events/{event['id']}/seat-map")
    assert response.status_code == 200, response.text
    return response.json()


def _seats(seat_map: dict, category: str, n: int = 1) -> list[str]:
    free = [
        seat["id"]
        for section in seat_map["sections"]
        for row in section["rows"]
        for seat in row["seats"]
        if seat["category"] == category and seat["status"] == "available"
    ]
    return free[:n]


def _status(seat_map: dict, seat_id: str) -> str:
    for section in seat_map["sections"]:
        for row in section["rows"]:
            for seat in row["seats"]:
                if seat["id"] == seat_id:
                    return seat["status"]
    raise AssertionError("seat not on map")


def _order(client: AsyncClient, buyer, event: dict, seat_ids: list[str]):
    return client.post(
        f"{API}/events/{event['id']}/orders",
        json={"seat_ids": seat_ids},
        headers=buyer.headers,
    )


async def _pay(client: AsyncClient, buyer, order: dict) -> dict:
    response = await client.post(
        f"{API}/orders/{order['id']}/pay", json={}, headers=buyer.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- Calendar export ------------------------------------------------------------------


async def test_ics_file_updates_and_cancels(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True, timezone="Asia/Almaty")
    url = f"{API}/events/{event['id']}/calendar.ics"

    first = await client.get(url)
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/calendar")
    body = first.text
    assert "BEGIN:VCALENDAR" in body and "BEGIN:VEVENT" in body
    assert f"UID:event-{event['id']}@biletflow" in body
    assert "DTSTART;TZID=Asia/Almaty:" in body
    assert "SEQUENCE:0" in body and "STATUS:CONFIRMED" in body
    assert "\r\n" in body

    changed = await client.patch(
        f"{API}/events/{event['id']}",
        json={"title": "Night at the Philharmonic, moved"},
        headers=owner.headers,
    )
    assert changed.status_code == 200, changed.text
    second = (await client.get(url)).text
    assert "SEQUENCE:1" in second
    assert f"UID:event-{event['id']}@biletflow" in second

    cancelled = await client.post(
        f"{API}/events/{event['id']}/cancel", headers=owner.headers
    )
    assert cancelled.status_code == 200, cancelled.text
    third = (await client.get(url)).text
    assert "STATUS:CANCELLED" in third and "METHOD:CANCEL" in third
    assert "SEQUENCE:2" in third


async def test_calendar_links_and_order_links(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True)
    links = await client.get(f"{API}/events/{event['id']}/calendar-links")
    assert links.status_code == 200
    data = links.json()
    assert set(data) == {"ics", "google", "outlook", "yahoo"}
    assert data["ics"].endswith(f"/events/{event['id']}/calendar.ics")
    assert "calendar.google.com" in data["google"]

    types = await client.get(f"{API}/events/{event['id']}/ticket-types")
    buyer = await create_account(client)
    order = await client.post(
        f"{API}/events/{event['id']}/orders",
        json={"items": [{"ticket_type_id": types.json()[0]["id"], "quantity": 1}]},
        headers=buyer.headers,
    )
    assert order.status_code == 201, order.text
    assert order.json()["calendar_links"]["ics"] == data["ics"]


async def test_draft_calendar_is_private(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    response = await client.get(f"{API}/events/{event['id']}/calendar.ics")
    assert response.status_code == 404


# --- Layouts and setup ----------------------------------------------------------------


async def test_predefined_layout_is_listed(client: AsyncClient):
    account = await create_account(client)
    hall = await _hall(client, account)
    assert hall["total_seats"] == 136
    assert hall["categories"] == {"A": 36, "B": 60, "C": 40}
    assert hall["accessible_seats"] == 4
    assert [s["name"] for s in hall["sections"]] == ["Stalls", "Balcony"]


async def test_configure_seating_creates_ticket_types(client: AsyncClient):
    owner, event, ticket_types = await _seated_event(client, publish=False)
    assert sorted((t["seat_category"], t["quantity"]) for t in ticket_types) == [
        ("A", 36),
        ("B", 60),
        ("C", 40),
    ]
    fetched = await client.get(f"{API}/events/{event['id']}", headers=owner.headers)
    assert fetched.json()["seating_type"] == "assigned"
    assert fetched.json()["capacity"] == 136
    assert fetched.json()["venue_layout_id"] is not None

    hall = await _hall(client, owner)
    again = await client.post(
        f"{API}/events/{event['id']}/seating",
        json={"venue_id": hall["id"], "categories": PRICES},
        headers=owner.headers,
    )
    assert again.status_code == 409

    extra = await client.post(
        f"{API}/events/{event['id']}/ticket-types",
        json={"name": "Standing", "price_kzt": 0, "quantity": 5},
        headers=owner.headers,
    )
    assert extra.status_code == 409
    resize = await client.patch(
        f"{API}/ticket-types/{ticket_types[0]['id']}",
        json={"quantity": 5},
        headers=owner.headers,
    )
    assert resize.status_code == 409
    rename = await client.patch(
        f"{API}/ticket-types/{ticket_types[0]['id']}",
        json={"name": "Premium stalls"},
        headers=owner.headers,
    )
    assert rename.status_code == 200, rename.text
    removed = await client.delete(
        f"{API}/ticket-types/{ticket_types[0]['id']}",
        headers=owner.headers,
    )
    assert removed.status_code == 409


async def test_configure_needs_every_category_and_no_ticket_types(
    client: AsyncClient,
):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    hall = await _hall(client, owner)
    missing = await client.post(
        f"{API}/events/{event['id']}/seating",
        json={"venue_id": hall["id"], "categories": PRICES[:2]},
        headers=owner.headers,
    )
    assert missing.status_code == 400

    await add_ticket_type(client, owner, event["id"])
    late = await client.post(
        f"{API}/events/{event['id']}/seating",
        json={"venue_id": hall["id"], "categories": PRICES},
        headers=owner.headers,
    )
    assert late.status_code == 409

    stranger = await create_organizer(client)
    other = await create_event(client, stranger)
    denied = await client.post(
        f"{API}/events/{other['id']}/seating",
        json={"venue_id": hall["id"], "categories": PRICES},
        headers=owner.headers,
    )
    assert denied.status_code in (403, 404)


async def test_general_admission_has_no_seat_map(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True)
    response = await client.get(f"{API}/events/{event['id']}/seat-map")
    assert response.status_code == 404


# --- Seated checkout ------------------------------------------------------------------


async def test_seat_map_lists_every_seat_with_labels(client: AsyncClient):
    _, event, _ = await _seated_event(client)
    seat_map = await _map(client, event)
    assert seat_map["counts"] == {"available": 136}
    assert set(seat_map["legend"]) >= {"available", "held", "sold", "accessible"}
    row_h = next(r for r in seat_map["sections"][0]["rows"] if r["label"] == "H")
    first = row_h["seats"][0]
    assert first["is_accessible"] is True
    assert "accessible" in first["label"] and "available" in first["label"]
    assert first["price_kzt"] == 6000


async def test_seated_checkout_puts_seats_on_tickets(client: AsyncClient):
    owner, event, _ = await _seated_event(client)
    buyer = await create_account(client)
    chosen = _seats(await _map(client, event), "A", 2)

    created = await _order(client, buyer, event, chosen)
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "pending"
    assert order["total_kzt"] == 18000
    [item] = order["items"]
    assert item["quantity"] == 2
    assert len(item["seats"]) == 2 and item["seats"][0].startswith("Stalls, Row A")
    held = await _map(client, event)
    assert _status(held, chosen[0]) == "held"

    order = await _pay(client, buyer, order)
    assert order["status"] == "confirmed"
    sold = await _map(client, event)
    assert [_status(sold, s) for s in chosen] == ["sold", "sold"]
    assert all(t["seat"].startswith("Stalls, Row A, Seat") for t in order["tickets"])

    ticket_id = order["tickets"][0]["id"]
    detail = await client.get(f"{API}/tickets/{ticket_id}", headers=buyer.headers)
    assert detail.json()["seat"]["section"] == "Stalls"
    assert detail.json()["seat"]["row"] == "A"
    pdf = await client.get(f"{API}/tickets/{ticket_id}/pdf", headers=buyer.headers)
    assert pdf.status_code == 200

    attendees = await client.get(
        f"{API}/events/{event['id']}/attendees", headers=owner.headers
    )
    assert all(a["seat"] for a in attendees.json())

    taken = await _order(client, await create_account(client), event, chosen[:1])
    assert taken.status_code == 409


async def test_free_seats_confirm_immediately(client: AsyncClient):
    _, event, _ = await _seated_event(client)
    buyer = await create_account(client)
    chosen = _seats(await _map(client, event), "C", 1)
    response = await _order(client, buyer, event, chosen)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "confirmed"
    assert response.json()["tickets"][0]["seat"].startswith("Balcony, Row 1")


async def test_seat_selection_rules(client: AsyncClient):
    _, event, ticket_types = await _seated_event(client)
    buyer = await create_account(client)
    by_items = await client.post(
        f"{API}/events/{event['id']}/orders",
        json={"items": [{"ticket_type_id": ticket_types[0]["id"], "quantity": 1}]},
        headers=buyer.headers,
    )
    assert by_items.status_code == 400

    unknown = await _order(client, buyer, event, [ticket_types[0]["id"]])
    assert unknown.status_code == 404

    both = await client.post(
        f"{API}/events/{event['id']}/orders",
        json={
            "items": [{"ticket_type_id": ticket_types[0]["id"], "quantity": 1}],
            "seat_ids": _seats(await _map(client, event), "B", 1),
        },
        headers=buyer.headers,
    )
    assert both.status_code == 422

    owner = await create_organizer(client)
    general = await create_event(client, owner, publish=True)
    seated = _seats(await _map(client, event), "B", 1)
    refused = await _order(client, buyer, general, seated)
    assert refused.status_code == 400


async def test_expired_hold_frees_the_seat(client: AsyncClient):
    _, event, _ = await _seated_event(client)
    first, second = await create_account(client), await create_account(client)
    chosen = _seats(await _map(client, event), "B", 1)
    held = await _order(client, first, event, chosen)
    assert held.status_code == 201
    blocked = await _order(client, second, event, chosen)
    assert blocked.status_code == 409

    await expire_hold(held.json()["id"])
    assert _status(await _map(client, event), chosen[0]) == "available"
    again = await _order(client, second, event, chosen)
    assert again.status_code == 201, again.text


async def test_refund_frees_the_seat(client: AsyncClient):
    owner, event, _ = await _seated_event(client)
    buyer = await create_account(client)
    chosen = _seats(await _map(client, event), "A", 1)
    order = await _pay(
        client, buyer, (await _order(client, buyer, event, chosen)).json()
    )

    refund = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"reason": "Attendee is ill"},
        headers=owner.headers,
    )
    assert refund.status_code == 200, refund.text
    assert _status(await _map(client, event), chosen[0]) == "available"
    resold = await _order(client, await create_account(client), event, chosen)
    assert resold.status_code == 201, resold.text


async def test_same_seat_race_sells_once(client: AsyncClient):
    _, event, _ = await _seated_event(client)
    buyers = [await create_account(client) for _ in range(6)]
    chosen = _seats(await _map(client, event), "B", 1)

    responses = await asyncio.gather(
        *(_order(client, buyer, event, chosen) for buyer in buyers)
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * 5
    assert (await _map(client, event))["counts"]["held"] == 1


async def test_overlapping_selections_are_all_or_nothing(client: AsyncClient):
    _, event, _ = await _seated_event(client)
    first, second = await create_account(client), await create_account(client)
    a, b, c = _seats(await _map(client, event), "B", 3)
    assert (await _order(client, first, event, [a, b])).status_code == 201
    overlap = await _order(client, second, event, [b, c])
    assert overlap.status_code == 409
    assert _status(await _map(client, event), c) == "available"


async def test_quote_prices_seats(client: AsyncClient):
    _, event, _ = await _seated_event(client)
    seat_map = await _map(client, event)
    chosen = _seats(seat_map, "A", 1) + _seats(seat_map, "B", 2)
    response = await client.post(
        f"{API}/events/{event['id']}/quote", json={"seat_ids": chosen}
    )
    assert response.status_code == 200, response.text
    assert response.json()["subtotal_kzt"] == 9000 + 2 * 6000
