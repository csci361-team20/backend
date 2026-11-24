from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.modules.orders.enums import OrderStatus, TicketStatus
from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import insert_order

pytestmark = pytest.mark.anyio


async def _event_with_ticket(client: AsyncClient, **ticket: object):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    ticket_type = await add_ticket_type(client, owner, event["id"], **ticket)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    return owner, event, ticket_type


async def test_stats_break_down_reserved_sold_refunded_checked_in(
    client: AsyncClient,
):
    owner, event, ticket_type = await _event_with_ticket(client, quantity=10)
    buyer = await create_account(client)
    await insert_order(
        event["id"],
        buyer.id,
        ticket_type["id"],
        quantity=4,
        status=OrderStatus.CONFIRMED,
        ticket_statuses=[
            TicketStatus.VALID,
            TicketStatus.CHECKED_IN,
            TicketStatus.REFUNDED,
            TicketStatus.CANCELLED,
        ],
    )
    await insert_order(event["id"], buyer.id, ticket_type["id"], quantity=3)

    response = await client.get(
        f"{API}/events/{event['id']}/ticket-stats", headers=owner.headers
    )
    assert response.status_code == 200, response.text
    row = response.json()["ticket_types"][0]
    assert (row["sold"], row["checked_in"], row["refunded"], row["reserved"]) == (
        2,
        1,
        1,
        3,
    )
    # 10 - 2 sold - 3 held; refunded and cancelled places are free again
    assert row["available"] == 5
    assert response.json()["totals"]["available"] == 5

    public = await client.get(f"{API}/events/{event['id']}/ticket-types")
    assert public.json()[0]["available"] == 5
    assert "sold" not in public.json()[0]


async def test_ticket_stats_are_for_owner_and_managers_only(client: AsyncClient):
    owner, event, _ = await _event_with_ticket(client)
    door = await create_account(client)
    url = f"{API}/events/{event['id']}"
    await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )
    assert (await client.get(f"{url}/ticket-stats")).status_code == 401
    assert (
        await client.get(f"{url}/ticket-stats", headers=door.headers)
    ).status_code == 403


async def test_sale_status_reflects_window_and_stock(client: AsyncClient):
    now = datetime.now(UTC)
    _, event, sold_out = await _event_with_ticket(client, quantity=2)
    buyer = await create_account(client)
    await insert_order(event["id"], buyer.id, sold_out["id"], quantity=2)

    owner = await create_organizer(client)
    later = await create_event(client, owner)
    scheduled = await add_ticket_type(
        client,
        owner,
        later["id"],
        sale_start=(now + timedelta(days=3)).isoformat(),
    )
    ended = await add_ticket_type(
        client,
        owner,
        later["id"],
        name="Early bird",
        sale_start=(now - timedelta(days=3)).isoformat(),
        sale_end=(now - timedelta(days=1)).isoformat(),
    )
    on_sale = await add_ticket_type(client, owner, later["id"], name="Standard")

    statuses = {
        t["id"]: t["sale_status"]
        for t in (await client.get(f"{API}/events/{event['id']}/ticket-types")).json()
    }
    assert statuses[sold_out["id"]] == "sold_out"
    assert scheduled["sale_status"] == "scheduled"
    assert ended["sale_status"] == "ended"
    assert on_sale["sale_status"] == "on_sale"


async def test_quantity_cannot_drop_below_sold_and_reserved(client: AsyncClient):
    owner, event, ticket_type = await _event_with_ticket(client, quantity=10)
    buyer = await create_account(client)
    await insert_order(
        event["id"],
        buyer.id,
        ticket_type["id"],
        quantity=3,
        status=OrderStatus.CONFIRMED,
        ticket_statuses=[TicketStatus.VALID] * 3,
    )
    await insert_order(event["id"], buyer.id, ticket_type["id"], quantity=2)
    url = f"{API}/ticket-types/{ticket_type['id']}"

    assert (
        await client.patch(url, json={"quantity": 4}, headers=owner.headers)
    ).status_code == 409
    response = await client.patch(url, json={"quantity": 5}, headers=owner.headers)
    assert response.status_code == 200
    assert response.json()["available"] == 0


async def test_delete_only_without_orders(client: AsyncClient):
    owner, event, ticket_type = await _event_with_ticket(client)
    unused = await add_ticket_type(client, owner, event["id"], name="Spare")
    buyer = await create_account(client)
    await insert_order(event["id"], buyer.id, ticket_type["id"], quantity=1)

    used = await client.delete(
        f"{API}/ticket-types/{ticket_type['id']}", headers=owner.headers
    )
    assert used.status_code == 409
    gone = await client.delete(
        f"{API}/ticket-types/{unused['id']}", headers=owner.headers
    )
    assert gone.status_code == 204
    assert (
        await client.get(f"{API}/ticket-types/{unused['id']}", headers=owner.headers)
    ).status_code == 404
