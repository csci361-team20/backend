import pytest
from httpx import AsyncClient

from tests.conftest import API, create_account, create_event, create_organizer

pytestmark = pytest.mark.anyio

TICKET = {"name": "Standard", "price_kzt": 0, "quantity": 50}


async def test_only_owner_or_manager_can_create_and_edit_ticket_types(
    client: AsyncClient,
):
    owner = await create_organizer(client)
    outsider = await create_account(client)
    event = await create_event(client, owner, publish=True)
    url = f"{API}/events/{event['id']}/ticket-types"

    assert (await client.post(url, json=TICKET)).status_code == 401
    assert (
        await client.post(url, json=TICKET, headers=outsider.headers)
    ).status_code == 403

    created = await client.post(url, json=TICKET, headers=owner.headers)
    assert created.status_code == 201, created.text
    ticket_url = f"{API}/ticket-types/{created.json()['id']}"

    hijack = await client.patch(
        ticket_url, json={"price_kzt": 1}, headers=outsider.headers
    )
    assert hijack.status_code == 403
    edit = await client.patch(
        ticket_url, json={"price_kzt": 5000}, headers=owner.headers
    )
    assert edit.status_code == 200
    assert edit.json()["price_kzt"] == 5000


async def test_hidden_ticket_types_are_only_visible_to_managers(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True, capacity=200)
    url = f"{API}/events/{event['id']}/ticket-types"
    await client.post(url, json=TICKET, headers=owner.headers)
    hidden = await client.post(
        url, json={**TICKET, "name": "Comp", "is_hidden": True}, headers=owner.headers
    )
    hidden_url = f"{API}/ticket-types/{hidden.json()['id']}"

    public = await client.get(url)
    assert sorted(t["name"] for t in public.json()) == ["General", "Standard"]
    assert (await client.get(url, params={"include_hidden": True})).status_code == 401
    assert (await client.get(hidden_url)).status_code == 404

    staff_view = await client.get(
        url, params={"include_hidden": True}, headers=owner.headers
    )
    assert sorted(t["name"] for t in staff_view.json()) == [
        "Comp",
        "General",
        "Standard",
    ]
    assert (await client.get(hidden_url, headers=owner.headers)).status_code == 200


async def test_ticket_types_of_draft_events_are_not_public(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    url = f"{API}/events/{event['id']}/ticket-types"
    await client.post(url, json=TICKET, headers=owner.headers)

    assert (await client.get(url)).status_code == 404
    assert (await client.get(url, headers=owner.headers)).status_code == 200
