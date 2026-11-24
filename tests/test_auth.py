import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    PASSWORD,
    create_account,
    login,
    set_user_fields,
    token_from_email,
)

pytestmark = pytest.mark.anyio


async def test_login_rejects_wrong_password(client: AsyncClient):
    account = await create_account(client)
    response = await client.post(
        f"{API}/auth/login", data={"username": account.email, "password": "nope-nope"}
    )
    assert response.status_code == 401


async def test_login_is_case_insensitive_on_email(client: AsyncClient):
    account = await create_account(client)
    assert await login(client, account.email.upper(), PASSWORD)


async def test_suspended_user_cannot_log_in_or_use_existing_token(
    client: AsyncClient,
):
    account = await create_account(client)
    await set_user_fields(account.id, is_suspended=True)

    me = await client.get(f"{API}/users/me", headers=account.headers)
    assert me.status_code == 403

    response = await client.post(
        f"{API}/auth/login", data={"username": account.email, "password": PASSWORD}
    )
    assert response.status_code == 403


async def test_logout_revokes_existing_tokens(client: AsyncClient):
    account = await create_account(client)

    response = await client.post(f"{API}/auth/logout", headers=account.headers)
    assert response.status_code == 204

    me = await client.get(f"{API}/users/me", headers=account.headers)
    assert me.status_code == 401

    fresh = await login(client, account.email, PASSWORD)
    me = await client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {fresh}"}
    )
    assert me.status_code == 200


async def test_email_verification_flow(client: AsyncClient, sent_emails):
    account = await create_account(client, verified=False)
    token = token_from_email(sent_emails[-1])

    response = await client.post(
        f"{API}/auth/verify-email/confirm", json={"token": token}
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_email_verified"] is True

    me = await client.get(f"{API}/users/me", headers=account.headers)
    assert me.json()["is_email_verified"] is True

    # Re-using the link is harmless
    again = await client.post(f"{API}/auth/verify-email/confirm", json={"token": token})
    assert again.status_code == 200


async def test_resend_verification_email(client: AsyncClient, sent_emails):
    account = await create_account(client, verified=False)
    sent_emails.clear()

    response = await client.post(
        f"{API}/auth/verify-email/request", headers=account.headers
    )

    assert response.status_code == 202
    assert [m.to for m in sent_emails] == [account.email]


async def test_verification_rejects_garbage_and_wrong_purpose_tokens(
    client: AsyncClient, sent_emails
):
    await create_account(client, verified=False)
    garbage = await client.post(
        f"{API}/auth/verify-email/confirm", json={"token": "not-a-real-token"}
    )
    assert garbage.status_code == 400

    # An access token is not a verification token
    account = await create_account(client, verified=False)
    wrong = await client.post(
        f"{API}/auth/verify-email/confirm", json={"token": account.token}
    )
    assert wrong.status_code == 400


async def test_password_reset_flow_is_single_use(client: AsyncClient, sent_emails):
    account = await create_account(client)
    sent_emails.clear()

    response = await client.post(
        f"{API}/auth/password-reset/request", json={"email": account.email}
    )
    assert response.status_code == 202
    token = token_from_email(sent_emails[-1])

    new_password = "brand-new-password-7"
    reset = await client.post(
        f"{API}/auth/password-reset/confirm",
        json={"token": token, "new_password": new_password},
    )
    assert reset.status_code == 204

    # Old sessions are signed out and the old password no longer works
    me = await client.get(f"{API}/users/me", headers=account.headers)
    assert me.status_code == 401
    old = await client.post(
        f"{API}/auth/login", data={"username": account.email, "password": PASSWORD}
    )
    assert old.status_code == 401
    assert await login(client, account.email, new_password)

    reused = await client.post(
        f"{API}/auth/password-reset/confirm",
        json={"token": token, "new_password": "another-password-9"},
    )
    assert reused.status_code == 400


async def test_password_reset_does_not_reveal_unknown_emails(
    client: AsyncClient, sent_emails
):
    response = await client.post(
        f"{API}/auth/password-reset/request",
        json={"email": "nobody-here@example.com"},
    )
    assert response.status_code == 202
    assert sent_emails == []


async def test_change_password_returns_fresh_token(client: AsyncClient):
    account = await create_account(client)

    wrong = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": "wrong-one", "new_password": "new-password-11"},
        headers=account.headers,
    )
    assert wrong.status_code == 400

    response = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-password-11"},
        headers=account.headers,
    )
    assert response.status_code == 200
    fresh = response.json()["access_token"]

    assert (
        await client.get(f"{API}/users/me", headers=account.headers)
    ).status_code == 401
    me = await client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {fresh}"}
    )
    assert me.status_code == 200


async def test_refresh_token_rotation_and_revocation(client: AsyncClient):
    account = await create_account(client)
    login_response = await client.post(
        f"{API}/auth/login", data={"username": account.email, "password": PASSWORD}
    )
    tokens = login_response.json()
    assert tokens["expires_in"] == 30 * 60
    refresh_token = tokens["refresh_token"]

    renewed = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert renewed.status_code == 200, renewed.text
    fresh = renewed.json()
    me = await client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {fresh['access_token']}"}
    )
    assert me.status_code == 200

    # A refresh token is never accepted as an access token
    as_access = await client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {refresh_token}"}
    )
    assert as_access.status_code == 401
    garbage = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": "not-a-real-token"}
    )
    assert garbage.status_code == 401

    # Signing out revokes every refresh token issued so far
    await client.post(
        f"{API}/auth/logout",
        headers={"Authorization": f"Bearer {fresh['access_token']}"},
    )
    for old in (refresh_token, fresh["refresh_token"]):
        revoked = await client.post(f"{API}/auth/refresh", json={"refresh_token": old})
        assert revoked.status_code == 401
