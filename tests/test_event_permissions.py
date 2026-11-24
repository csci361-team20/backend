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

pytestmark = pytest.mark.anyio


async def test_creating_events_requires_verified_account(client: AsyncClient):
    anonymous = await client.post(f"{API}/events/", json=event_payload())
    assert anonymous.status_code == 401

    unverified = await create_account(client, verified=False)
    response = await client.post(
        f"{API}/events/", json=event_payload(), headers=unverified.headers
    )
    assert response.status_code == 403


async def test_owner_creates_event_for_own_profile(client: AsyncClient):
    owner = await create_organizer(client)
    profile = (await client.get(f"{API}/organizers/me", headers=owner.headers)).json()

    event = await create_event(client, owner)

    assert event["organizer_profile_id"] == profile["id"]
    assert event["status"] == "draft"
    assert event["published_at"] is None

    mine = await client.get(f"{API}/events/mine", headers=owner.headers)
    assert [(e["id"], e["my_role"]) for e in mine.json()] == [(event["id"], "owner")]


async def test_draft_and_private_events_are_hidden_from_outsiders(
    client: AsyncClient,
):
    owner = await create_organizer(client)
    outsider = await create_account(client)
    admin = await create_account(client, admin=True)
    draft = await create_event(client, owner)
    private = await create_event(client, owner, publish=True, visibility="private")
    unlisted = await create_event(client, owner, publish=True, visibility="unlisted")

    for event in (draft, private):
        url = f"{API}/events/{event['id']}"
        assert (await client.get(url)).status_code == 404
        assert (await client.get(url, headers=outsider.headers)).status_code == 404
        assert (await client.get(url, headers=owner.headers)).status_code == 200
        assert (await client.get(url, headers=admin.headers)).status_code == 200

    # Unlisted: reachable by link, absent from the public list
    assert (await client.get(f"{API}/events/{unlisted['id']}")).status_code == 200
    listed = await client.get(f"{API}/events/", params={"limit": 200})
    listed_ids = {e["id"] for e in listed.json()}
    assert unlisted["id"] not in listed_ids
    assert private["id"] not in listed_ids


async def test_only_event_team_can_edit_publish_and_cancel(client: AsyncClient):
    owner = await create_organizer(client)
    other_organizer = await create_organizer(client)
    event = await create_event(client, owner, publish=True)
    url = f"{API}/events/{event['id']}"

    edit = await client.patch(
        url, json={"title": "Taken over"}, headers=other_organizer.headers
    )
    assert edit.status_code == 403
    cancel = await client.post(f"{url}/cancel", headers=other_organizer.headers)
    assert cancel.status_code == 403
    assert (await client.patch(url, json={"title": "x" * 5})).status_code == 401

    edit = await client.patch(url, json={"title": "New title"}, headers=owner.headers)
    assert edit.status_code == 200
    assert edit.json()["title"] == "New title"


async def test_publish_sets_published_at(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True)
    assert event["status"] == "published"
    assert event["published_at"] is not None


async def test_manager_can_edit_but_not_cancel_or_add_managers(client: AsyncClient):
    owner = await create_organizer(client)
    manager = await create_account(client)
    door = await create_account(client)
    event = await create_event(client, owner)
    await add_ticket_type(client, owner, event["id"])
    url = f"{API}/events/{event['id']}"

    added = await client.post(
        f"{url}/staff",
        json={"email": manager.email, "role": "manager"},
        headers=owner.headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "manager"

    assert (
        await client.patch(url, json={"title": "Manager edit"}, headers=manager.headers)
    ).status_code == 200
    assert (
        await client.post(f"{url}/publish", headers=manager.headers)
    ).status_code == 200
    assert (
        await client.post(f"{url}/cancel", headers=manager.headers)
    ).status_code == 403

    promote = await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "manager"},
        headers=manager.headers,
    )
    assert promote.status_code == 403

    checkin = await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=manager.headers,
    )
    assert checkin.status_code == 201

    # Managers cannot remove other managers, owners can
    remove = await client.delete(f"{url}/staff/{manager.id}", headers=manager.headers)
    assert remove.status_code == 403
    remove = await client.delete(f"{url}/staff/{manager.id}", headers=owner.headers)
    assert remove.status_code == 204


async def test_checkin_staff_sees_assigned_event_but_cannot_manage_it(
    client: AsyncClient,
):
    owner = await create_organizer(client)
    door = await create_account(client)
    event = await create_event(client, owner)
    url = f"{API}/events/{event['id']}"
    await client.post(
        f"{url}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )

    # Draft, but visible to its own team
    assert (await client.get(url, headers=door.headers)).status_code == 200
    assert (
        await client.patch(url, json={"title": "Door edit"}, headers=door.headers)
    ).status_code == 403
    assert (await client.get(f"{url}/staff", headers=door.headers)).status_code == 403

    assigned = await client.get(
        f"{API}/events/mine", params={"role": "checkin_staff"}, headers=door.headers
    )
    assert [e["id"] for e in assigned.json()] == [event["id"]]
    # The default view is the organizer dashboard: owned or managed events only
    dashboard = await client.get(f"{API}/events/mine", headers=door.headers)
    assert dashboard.json() == []


async def test_staff_assignment_errors(client: AsyncClient):
    owner = await create_organizer(client)
    door = await create_account(client)
    event = await create_event(client, owner)
    url = f"{API}/events/{event['id']}/staff"

    unknown = await client.post(
        url,
        json={"email": "no-such-person@example.com", "role": "checkin_staff"},
        headers=owner.headers,
    )
    assert unknown.status_code == 404

    owner_role = await client.post(
        url, json={"email": door.email, "role": "owner"}, headers=owner.headers
    )
    assert owner_role.status_code == 422

    first = await client.post(
        url, json={"email": door.email, "role": "checkin_staff"}, headers=owner.headers
    )
    assert first.status_code == 201
    duplicate = await client.post(
        url, json={"email": door.email, "role": "manager"}, headers=owner.headers
    )
    assert duplicate.status_code == 409

    staff = await client.get(url, headers=owner.headers)
    assert {s["role"] for s in staff.json()} == {"owner", "checkin_staff"}

    remove_owner = await client.delete(f"{url}/{owner.id}", headers=owner.headers)
    assert remove_owner.status_code == 400


async def test_expired_token_still_reads_public_events(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True)
    stale = {"Authorization": "Bearer not-a-valid-token"}

    assert (
        await client.get(f"{API}/events/{event['id']}", headers=stale)
    ).status_code == 200
    # Protected routes still refuse it
    assert (await client.get(f"{API}/events/mine", headers=stale)).status_code == 401
