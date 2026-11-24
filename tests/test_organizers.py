import pytest
from httpx import AsyncClient

from tests.conftest import API, create_account, create_organizer, event_payload

pytestmark = pytest.mark.anyio


async def test_organizer_profile_requires_verified_email(client: AsyncClient):
    unverified = await create_account(client, verified=False)
    response = await client.post(
        f"{API}/organizers/",
        json={"display_name": "Steppe Events"},
        headers=unverified.headers,
    )
    assert response.status_code == 403


async def test_one_profile_per_user(client: AsyncClient):
    owner = await create_organizer(client)
    again = await client.post(
        f"{API}/organizers/", json={"display_name": "Second"}, headers=owner.headers
    )
    assert again.status_code == 409


async def test_owner_edits_own_profile_and_only_admin_verifies(client: AsyncClient):
    owner = await create_organizer(client)
    outsider = await create_account(client)
    admin = await create_account(client, admin=True)
    profile = (await client.get(f"{API}/organizers/me", headers=owner.headers)).json()

    rename = await client.patch(
        f"{API}/organizers/me", json={"display_name": "Renamed"}, headers=owner.headers
    )
    assert rename.status_code == 200
    assert rename.json()["display_name"] == "Renamed"

    url = f"{API}/organizers/{profile['id']}/verification"
    for account in (owner, outsider):
        denied = await client.patch(
            url, json={"verification_status": "verified"}, headers=account.headers
        )
        assert denied.status_code == 403
    verify = await client.patch(
        url, json={"verification_status": "verified"}, headers=admin.headers
    )
    assert verify.status_code == 200
    assert verify.json()["verification_status"] == "verified"


async def test_profile_body_is_optional_and_defaults_to_full_name(
    client: AsyncClient,
):
    account = await create_account(client, full_name="Arman Bekov")
    response = await client.post(f"{API}/organizers/", headers=account.headers)
    assert response.status_code == 201, response.text
    assert response.json()["display_name"] == "Arman Bekov"


async def test_first_event_creates_organizer_profile(client: AsyncClient):
    account = await create_account(client)
    assert (
        await client.get(f"{API}/organizers/me", headers=account.headers)
    ).status_code == 404

    created = await client.post(
        f"{API}/events/", json=event_payload(), headers=account.headers
    )
    assert created.status_code == 201, created.text

    profile = await client.get(f"{API}/organizers/me", headers=account.headers)
    assert profile.status_code == 200
    assert created.json()["organizer_profile_id"] == profile.json()["id"]


async def test_my_profile_404_when_missing(client: AsyncClient):
    account = await create_account(client)
    response = await client.get(f"{API}/organizers/me", headers=account.headers)
    assert response.status_code == 404
