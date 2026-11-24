from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import API, PASSWORD, create_account

pytestmark = pytest.mark.anyio


async def test_register_returns_public_fields_and_sends_verification(
    client: AsyncClient, sent_emails
):
    email_address = f"Test-{uuid4().hex}@Example.com"
    response = await client.post(
        f"{API}/users/",
        json={"email": email_address, "full_name": "Dana Sarsen", "password": PASSWORD},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == email_address.lower()
    assert body["is_email_verified"] is False
    assert "password" not in body and "password_hash" not in body
    assert [m.to for m in sent_emails] == [email_address.lower()]
    assert "/verify-email?token=" in sent_emails[0].body


async def test_register_duplicate_email_is_conflict_case_insensitive(
    client: AsyncClient,
):
    account = await create_account(client)
    response = await client.post(
        f"{API}/users/",
        json={
            "email": account.email.upper(),
            "full_name": "Someone Else",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 409


async def test_list_users_requires_platform_admin(client: AsyncClient):
    user = await create_account(client)
    admin = await create_account(client, admin=True)

    assert (await client.get(f"{API}/users/")).status_code == 401
    assert (await client.get(f"{API}/users/", headers=user.headers)).status_code == 403

    response = await client.get(
        f"{API}/users/", params={"limit": 200}, headers=admin.headers
    )
    assert response.status_code == 200


async def test_user_can_read_and_edit_only_own_account(client: AsyncClient):
    alice = await create_account(client)
    bob = await create_account(client)

    own = await client.get(f"{API}/users/{alice.id}", headers=alice.headers)
    assert own.status_code == 200
    assert own.json()["email"] == alice.email

    other = await client.get(f"{API}/users/{bob.id}", headers=alice.headers)
    assert other.status_code == 403

    edit = await client.patch(
        f"{API}/users/{bob.id}", json={"full_name": "Hacked"}, headers=alice.headers
    )
    assert edit.status_code == 403

    renamed = await client.patch(
        f"{API}/users/me", json={"full_name": "Alice Renamed"}, headers=alice.headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["full_name"] == "Alice Renamed"


async def test_admin_gets_404_for_unknown_user(client: AsyncClient):
    admin = await create_account(client, admin=True)
    response = await client.get(
        f"{API}/users/00000000-0000-0000-0000-000000000000", headers=admin.headers
    )
    assert response.status_code == 404


async def test_user_can_delete_own_account(client: AsyncClient):
    account = await create_account(client)

    response = await client.delete(f"{API}/users/{account.id}", headers=account.headers)

    assert response.status_code == 204
    # The token now points at a missing user
    me = await client.get(f"{API}/users/me", headers=account.headers)
    assert me.status_code == 401
