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


async def _activity(client: AsyncClient, account, event_id: str, **params) -> list:
    response = await client.get(
        f"{API}/events/{event_id}/activity", params=params, headers=account.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_event_actions_land_on_the_timeline(client: AsyncClient):
    owner = await create_organizer(client)
    door = await create_account(client, full_name="Door Keeper")
    event = await create_event(client, owner)
    url = f"{API}/events/{event['id']}"
    ticket = await add_ticket_type(client, owner, event["id"], price_kzt=0)
    await client.patch(
        f"{API}/ticket-types/{ticket['id']}",
        json={"quantity": 20},
        headers=owner.headers,
    )
    await client.patch(url, json={"capacity": 150}, headers=owner.headers)
    await client.post(f"{url}/publish", headers=owner.headers)
    await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )
    await client.delete(f"{url}/staff/{door.id}", headers=owner.headers)
    await client.post(f"{url}/unpublish", headers=owner.headers)

    entries = await _activity(client, owner, event["id"])
    assert [e["action"] for e in entries] == [
        "event.unpublished",
        "staff.removed",
        "staff.added",
        "event.published",
        "event.updated",
        "ticket_type.updated",
        "ticket_type.created",
        "event.created",
    ]
    by_action = {e["action"]: e for e in entries}
    assert by_action["event.updated"]["details"]["changes"]["capacity"] == {
        "from": 100,
        "to": 150,
    }
    assert "quantity 10 → 20" in by_action["ticket_type.updated"]["description"]
    assert by_action["staff.added"]["description"] == (
        "Added Door Keeper as checkin staff"
    )
    assert {e["actor_name"] for e in entries} == {"Test User"}

    staff_only = await _activity(client, owner, event["id"], area="staff")
    assert [e["action"] for e in staff_only] == ["staff.removed", "staff.added"]


async def test_unchanged_edit_writes_nothing(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    await client.patch(
        f"{API}/events/{event['id']}",
        json={"title": event["title"]},
        headers=owner.headers,
    )
    entries = await _activity(client, owner, event["id"])
    assert [e["action"] for e in entries] == ["event.created"]


async def test_orders_and_payments_are_recorded(client: AsyncClient):
    owner = await create_organizer(client)
    buyer = await create_account(client)
    event = await create_event(client, owner)
    paid = await add_ticket_type(client, owner, event["id"], price_kzt=5000)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    order = (
        await client.post(
            f"{API}/events/{event['id']}/orders",
            json={"items": [{"ticket_type_id": paid["id"], "quantity": 1}]},
            headers=buyer.headers,
        )
    ).json()
    pay = f"{API}/orders/{order['id']}/pay"
    await client.post(pay, json={"outcome": "failure"}, headers=buyer.headers)
    await client.post(pay, json={}, headers=buyer.headers)

    entries = await _activity(client, owner, event["id"], area="payment")
    assert [e["action"] for e in entries] == ["payment.succeeded", "payment.failed"]
    assert entries[0]["description"] == "Paid 5000 KZT (simulated)"
    orders = await _activity(client, owner, event["id"], area="order")
    assert [e["action"] for e in orders] == ["order.confirmed"]


async def test_timeline_access_and_no_editing(client: AsyncClient):
    owner = await create_organizer(client)
    door = await create_account(client)
    outsider = await create_account(client)
    admin = await create_account(client, admin=True)
    event = await create_event(client, owner)
    url = f"{API}/events/{event['id']}"
    await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )

    assert (
        await client.get(f"{url}/activity", headers=door.headers)
    ).status_code == 403
    assert (
        await client.get(f"{url}/activity", headers=outsider.headers)
    ).status_code == 404
    assert (
        await client.get(f"{url}/activity", headers=admin.headers)
    ).status_code == 200
    # Entries are append-only: there is no route to change or remove them
    for method in ("PATCH", "PUT", "DELETE"):
        response = await client.request(
            method, f"{url}/activity", headers=owner.headers
        )
        assert response.status_code == 405
