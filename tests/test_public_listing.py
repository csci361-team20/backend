from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.modules.orders.enums import OrderStatus, TicketStatus
from tests.conftest import API, add_ticket_type, create_event, create_organizer
from tests.orders_helpers import insert_order

pytestmark = pytest.mark.anyio


def unique(title: str) -> str:
    """Titles are searched, so each run needs its own."""
    return f"{title} {uuid4().hex[:8]}"


async def test_public_list_shows_card_details(client: AsyncClient):
    card_title = unique("Card details night")
    owner = await create_organizer(client)
    event = await create_event(client, owner, title=card_title)
    await add_ticket_type(client, owner, event["id"], name="Standing", quantity=30)
    await add_ticket_type(
        client, owner, event["id"], name="Crew", quantity=5, is_hidden=True
    )
    published = await client.post(
        f"{API}/events/{event['id']}/publish", headers=owner.headers
    )
    assert published.status_code == 200, published.text

    response = await client.get(f"{API}/events/", params={"q": card_title})
    assert response.status_code == 200
    [item] = response.json()
    assert item["organizer_name"] == "Steppe Events"
    assert item["price_from_kzt"] == 0
    # Hidden ticket types are not counted
    assert item["tickets_available"] == 30
    assert item["sale_state"] == "on_sale"


async def test_public_list_marks_events_without_sales(client: AsyncClient):
    quiet_title = unique("Quiet night")
    owner = await create_organizer(client)
    event = await create_event(client, owner, title=quiet_title)
    ticket = await add_ticket_type(client, owner, event["id"], quantity=10)
    assert (
        await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    ).status_code == 200
    await client.patch(
        f"{API}/ticket-types/{ticket['id']}",
        json={"sale_start": "2099-01-01T00:00:00Z"},
        headers=owner.headers,
    )

    [item] = (await client.get(f"{API}/events/", params={"q": quiet_title})).json()
    assert item["sale_state"] == "scheduled"
    assert item["tickets_available"] == 0
    assert item["price_from_kzt"] == 0


async def test_public_list_marks_sold_out_and_empty_events(client: AsyncClient):
    packed_title = unique("Packed night")
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True, title=packed_title)
    [ticket] = (await client.get(f"{API}/events/{event['id']}/ticket-types")).json()
    await insert_order(
        event["id"],
        owner.id,
        ticket["id"],
        quantity=ticket["quantity"],
        status=OrderStatus.CONFIRMED,
        ticket_statuses=[TicketStatus.VALID] * ticket["quantity"],
    )

    [item] = (await client.get(f"{API}/events/", params={"q": packed_title})).json()
    assert item["sale_state"] == "sold_out"
    assert item["tickets_available"] == 0
