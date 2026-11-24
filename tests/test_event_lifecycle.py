from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
    event_payload,
)
from tests.orders_helpers import insert_order

pytestmark = pytest.mark.anyio


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


async def test_publish_requires_a_ticket_type(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    url = f"{API}/events/{event['id']}/publish"

    refused = await client.post(url, headers=owner.headers)
    assert refused.status_code == 400
    assert "ticket type" in refused.json()["detail"]

    await add_ticket_type(client, owner, event["id"])
    assert (await client.post(url, headers=owner.headers)).status_code == 200


async def test_ended_event_cannot_be_published(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(
        client,
        owner,
        start_at=_iso(timedelta(days=-2)),
        end_at=_iso(timedelta(days=-1)),
    )
    assert event["lifecycle"] == "completed"

    response = await client.post(
        f"{API}/events/{event['id']}/publish", headers=owner.headers
    )
    assert response.status_code == 400
    assert "ended" in response.json()["detail"]


async def test_unpublish_hides_event_until_orders_exist(client: AsyncClient):
    owner = await create_organizer(client)
    buyer = await create_account(client)
    event = await create_event(client, owner, publish=True)
    url = f"{API}/events/{event['id']}"

    unpublished = await client.post(f"{url}/unpublish", headers=owner.headers)
    assert unpublished.status_code == 200
    assert unpublished.json()["status"] == "draft"
    assert (await client.get(url)).status_code == 404

    assert (
        await client.post(f"{url}/publish", headers=owner.headers)
    ).status_code == 200
    tickets = (await client.get(f"{url}/ticket-types")).json()
    await insert_order(event["id"], buyer.id, tickets[0]["id"], quantity=1)

    refused = await client.post(f"{url}/unpublish", headers=owner.headers)
    assert refused.status_code == 409


async def test_duplicate_copies_configuration_not_people(client: AsyncClient):
    owner = await create_organizer(client)
    door = await create_account(client)
    outsider = await create_organizer(client)
    event = await create_event(client, owner, publish=True, subtitle="Live")
    url = f"{API}/events/{event['id']}"
    await add_ticket_type(
        client, owner, event["id"], name="VIP", price_kzt=15000, is_hidden=True
    )
    await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )

    assert (
        await client.post(f"{url}/duplicate", headers=outsider.headers)
    ).status_code == 403

    response = await client.post(f"{url}/duplicate", headers=owner.headers)
    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["id"] != event["id"]
    assert copy["title"] == f"{event['title']} (copy)"
    assert copy["subtitle"] == "Live"
    assert copy["status"] == "draft"
    assert copy["published_at"] is None

    copy_url = f"{API}/events/{copy['id']}"
    types = await client.get(
        f"{copy_url}/ticket-types",
        params={"include_hidden": True},
        headers=owner.headers,
    )
    assert sorted(t["name"] for t in types.json()) == ["General", "VIP"]
    staff = await client.get(f"{copy_url}/staff", headers=owner.headers)
    assert [s["role"] for s in staff.json()] == ["owner"]


async def test_preview_shows_attendee_view_to_event_team(client: AsyncClient):
    owner = await create_organizer(client)
    door = await create_account(client)
    outsider = await create_account(client)
    event = await create_event(client, owner)
    await add_ticket_type(client, owner, event["id"], name="Standard")
    await add_ticket_type(client, owner, event["id"], name="Comp", is_hidden=True)
    url = f"{API}/events/{event['id']}"
    await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )

    preview = await client.get(f"{url}/preview", headers=owner.headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["event"]["status"] == "draft"
    assert body["organizer_name"] == "Steppe Events"
    assert [t["name"] for t in body["ticket_types"]] == ["Standard"]

    assert (await client.get(f"{url}/preview", headers=door.headers)).status_code == 200
    assert (
        await client.get(f"{url}/preview", headers=outsider.headers)
    ).status_code == 404


async def test_lifecycle_and_my_events_filter(client: AsyncClient):
    owner = await create_organizer(client)
    upcoming = await create_event(client, owner, publish=True)
    cancelled = await create_event(client, owner)
    await client.post(f"{API}/events/{cancelled['id']}/cancel", headers=owner.headers)

    assert upcoming["lifecycle"] == "upcoming"

    mine = await client.get(
        f"{API}/events/mine", params={"lifecycle": "cancelled"}, headers=owner.headers
    )
    assert [e["id"] for e in mine.json()] == [cancelled["id"]]
    assert mine.json()[0]["lifecycle"] == "cancelled"


async def test_registration_window_is_validated(client: AsyncClient):
    owner = await create_organizer(client)
    bad = await client.post(
        f"{API}/events/",
        json=event_payload(registration_closes_at=_iso(timedelta(days=60))),
        headers=owner.headers,
    )
    assert bad.status_code == 422

    event = await create_event(
        client,
        owner,
        registration_opens_at=_iso(timedelta(days=1)),
        registration_closes_at=_iso(timedelta(days=10)),
    )
    url = f"{API}/events/{event['id']}"

    # Each field is valid alone, but closing before opening is not
    flipped = await client.patch(
        url,
        json={"registration_opens_at": _iso(timedelta(days=20))},
        headers=owner.headers,
    )
    assert flipped.status_code == 400

    cleared = await client.patch(
        url, json={"registration_opens_at": None}, headers=owner.headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["registration_opens_at"] is None


async def test_cover_image_must_be_http_url(client: AsyncClient):
    owner = await create_organizer(client)
    bad = await client.post(
        f"{API}/events/",
        json=event_payload(cover_image_url="javascript:alert(1)"),
        headers=owner.headers,
    )
    assert bad.status_code == 422

    event = await create_event(
        client, owner, cover_image_url="https://cdn.example.kz/poster.jpg"
    )
    assert event["cover_image_url"] == "https://cdn.example.kz/poster.jpg"


async def test_capacity_cannot_drop_below_ticket_quantities(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, capacity=100)
    await add_ticket_type(client, owner, event["id"], quantity=60)
    url = f"{API}/events/{event['id']}"

    assert (
        await client.patch(url, json={"capacity": 50}, headers=owner.headers)
    ).status_code == 400
    assert (
        await client.patch(url, json={"capacity": 60}, headers=owner.headers)
    ).status_code == 200


async def test_public_list_search_filters_and_sort(client: AsyncClient):
    owner = await create_organizer(client)
    token = uuid4().hex[:10]
    soon = await create_event(
        client,
        owner,
        publish=True,
        title=f"Jazz {token} early",
        city="Almaty",
        start_at=_iso(timedelta(days=5)),
        end_at=_iso(timedelta(days=5, hours=2)),
    )
    later = await create_event(
        client,
        owner,
        publish=True,
        title=f"Jazz {token} late",
        city="Almaty",
        start_at=_iso(timedelta(days=40)),
        end_at=_iso(timedelta(days=40, hours=2)),
    )

    async def ids(**params: object) -> list[str]:
        response = await client.get(f"{API}/events/", params={"q": token, **params})
        assert response.status_code == 200, response.text
        return [e["id"] for e in response.json()]

    assert await ids() == [soon["id"], later["id"]]
    assert await ids(sort="-start_at") == [later["id"], soon["id"]]
    assert await ids(city="almaty") == [soon["id"], later["id"]]
    assert await ids(city="Astana") == []
    assert await ids(starts_from=_iso(timedelta(days=10))) == [later["id"]]
    assert await ids(starts_to=_iso(timedelta(days=10))) == [soon["id"]]
