"""Fixes from the security review: rate limits, per-device sign-out, CORS,
production settings and one checkout at a time under concurrency."""

import asyncio

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import DEV_SECRET_KEY, Settings, settings
from tests.conftest import (
    API,
    PASSWORD,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import activate_paid_sales

pytestmark = pytest.mark.anyio


async def _login(client: AsyncClient, email_address: str, password: str):
    return await client.post(
        f"{API}/auth/login", data={"username": email_address, "password": password}
    )


async def test_repeated_wrong_passwords_lock_sign_in_for_a_while(client: AsyncClient):
    account = await create_account(client)
    for _ in range(settings.LOGIN_MAX_FAILURES):
        assert (await _login(client, account.email, "wrong-guess")).status_code == 401
    # Even the right password waits until the window passes
    locked = await _login(client, account.email.upper(), PASSWORD)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    # Unknown accounts are limited the same way, so nothing is revealed
    for _ in range(settings.LOGIN_MAX_FAILURES):
        await _login(client, "nobody-here@example.com", "x")
    assert (await _login(client, "nobody-here@example.com", "x")).status_code == 429


async def test_successful_sign_in_clears_failed_attempts(client: AsyncClient):
    account = await create_account(client)
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        await _login(client, account.email, "wrong-guess")
    assert (await _login(client, account.email, PASSWORD)).status_code == 200
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        await _login(client, account.email, "wrong-guess")
    assert (await _login(client, account.email, PASSWORD)).status_code == 200


async def test_password_reset_emails_are_limited(client: AsyncClient, sent_emails):
    account = await create_account(client)
    sent_emails.clear()
    for _ in range(settings.AUTH_EMAILS_PER_WINDOW + 2):
        response = await client.post(
            f"{API}/auth/password-reset/request", json={"email": account.email}
        )
        # Same answer every time; only the email stops
        assert response.status_code == 202
    assert len(sent_emails) == settings.AUTH_EMAILS_PER_WINDOW


async def test_verification_emails_are_limited(client: AsyncClient, sent_emails):
    account = await create_account(client, verified=False)
    url = f"{API}/auth/verify-email/request"
    for _ in range(settings.AUTH_EMAILS_PER_WINDOW):
        assert (await client.post(url, headers=account.headers)).status_code == 202
    too_many = await client.post(url, headers=account.headers)
    assert too_many.status_code == 429


async def test_signing_out_one_device_keeps_the_others(client: AsyncClient):
    account = await create_account(client)
    laptop = (await _login(client, account.email, PASSWORD)).json()
    phone = (await _login(client, account.email, PASSWORD)).json()

    out = await client.post(
        f"{API}/auth/logout-session", json={"refresh_token": laptop["refresh_token"]}
    )
    assert out.status_code == 204
    refused = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": laptop["refresh_token"]}
    )
    assert refused.status_code == 401
    still = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": phone["refresh_token"]}
    )
    assert still.status_code == 200
    # Signing out twice, or with junk, is harmless
    again = await client.post(
        f"{API}/auth/logout-session", json={"refresh_token": laptop["refresh_token"]}
    )
    assert again.status_code == 204
    junk = await client.post(
        f"{API}/auth/logout-session", json={"refresh_token": "not-a-real-token"}
    )
    assert junk.status_code == 204


async def test_other_sites_are_not_allowed_by_cors(client: AsyncClient):
    preflight = {"Access-Control-Request-Method": "GET"}
    evil = await client.options(
        f"{API}/orders/mine", headers={"Origin": "https://evil.example", **preflight}
    )
    assert "access-control-allow-origin" not in evil.headers
    site = await client.options(
        f"{API}/orders/mine", headers={"Origin": "http://localhost:3000", **preflight}
    )
    assert site.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_production_refuses_unsafe_settings():
    base = {"DATABASE_URL": "postgresql+asyncpg://x/y", "ENVIRONMENT": "production"}
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(**base, SECRET_KEY=DEV_SECRET_KEY, _env_file=None)
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(**base, SECRET_KEY="short", _env_file=None)
    with pytest.raises(ValidationError, match="ORIGINS"):
        Settings(**base, SECRET_KEY="k" * 40, ORIGINS=["*"], _env_file=None)
    ok = Settings(**base, SECRET_KEY="k" * 40, _env_file=None)
    assert ok.ORIGINS == ["http://localhost:3000"]


async def test_fast_double_click_creates_one_checkout(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    ticket_type = await add_ticket_type(
        client, owner, event["id"], price_kzt=5000, quantity=20
    )
    await activate_paid_sales(event["id"])
    published = await client.post(
        f"{API}/events/{event['id']}/publish", headers=owner.headers
    )
    assert published.status_code == 200, published.text
    buyer = await create_account(client)
    payload = {"items": [{"ticket_type_id": ticket_type["id"], "quantity": 1}]}

    responses = await asyncio.gather(
        *(
            client.post(
                f"{API}/events/{event['id']}/orders",
                json=payload,
                headers=buyer.headers,
            )
            for _ in range(4)
        )
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409], [r.text for r in responses]
