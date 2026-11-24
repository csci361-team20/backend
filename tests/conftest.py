"""Shared fixtures for API tests.

API tests talk to a real PostgreSQL database (the one in DATABASE_URL, with
migrations applied). Every test creates its own users with unique emails, so
tests never depend on each other or on existing data.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.core import email, rate_limit
from app.core.database import AsyncSessionLocal
from app.main import app
from app.modules.users.models import User

API = "/api/v1"
PASSWORD = "correct-horse-42"


@dataclass
class SentEmail:
    to: str
    subject: str
    body: str
    attachments: list[tuple[str, bytes, str]] | None = None


@dataclass
class Account:
    id: UUID
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    """Each test starts with empty sign-in and email limits."""
    rate_limit.login_failures.reset()
    rate_limit.auth_emails.reset()


@pytest.fixture
def sent_emails(monkeypatch: pytest.MonkeyPatch) -> list[SentEmail]:
    """Capture outgoing email instead of talking to SMTP."""
    outbox: list[SentEmail] = []
    monkeypatch.setattr(
        email,
        "send_email",
        lambda to, subject, body, attachments=None: outbox.append(
            SentEmail(to, subject, body, attachments)
        ),
    )
    return outbox


@pytest.fixture
async def client(sent_emails: list[SentEmail]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def set_user_fields(user_id: UUID, **fields: object) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(User).where(User.id == user_id).values(**fields))
        await session.commit()


async def login(client: AsyncClient, email_address: str, password: str) -> str:
    response = await client.post(
        f"{API}/auth/login", data={"username": email_address, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def create_account(
    client: AsyncClient,
    *,
    verified: bool = True,
    admin: bool = False,
    full_name: str = "Test User",
) -> Account:
    email_address = f"test-{uuid4().hex}@example.com"
    response = await client.post(
        f"{API}/users/",
        json={"email": email_address, "full_name": full_name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    user_id = UUID(response.json()["id"])
    fields: dict[str, object] = {}
    if verified:
        fields["email_verified_at"] = datetime.now(UTC)
    if admin:
        fields["is_platform_admin"] = True
    if fields:
        await set_user_fields(user_id, **fields)
    return Account(user_id, email_address, await login(client, email_address, PASSWORD))


async def create_organizer(client: AsyncClient) -> Account:
    account = await create_account(client)
    response = await client.post(
        f"{API}/organizers/",
        json={"display_name": "Steppe Events"},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    return account


def event_payload(**overrides: object) -> dict[str, object]:
    start = datetime.now(UTC) + timedelta(days=30)
    payload: dict[str, object] = {
        "title": "Night at the Philharmonic",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=3)).isoformat(),
        "capacity": 100,
        "city": "Astana",
        "category": "concert",
    }
    payload.update(overrides)
    return payload


async def add_ticket_type(
    client: AsyncClient, owner: Account, event_id: str, **overrides: object
) -> dict:
    payload: dict[str, object] = {"name": "General", "price_kzt": 0, "quantity": 10}
    payload.update(overrides)
    response = await client.post(
        f"{API}/events/{event_id}/ticket-types", json=payload, headers=owner.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_event(
    client: AsyncClient, owner: Account, *, publish: bool = False, **overrides: object
) -> dict:
    """Create a draft; with ``publish``, add a "General" ticket type and publish
    (an event needs at least one ticket type to be published)."""
    response = await client.post(
        f"{API}/events/", json=event_payload(**overrides), headers=owner.headers
    )
    assert response.status_code == 201, response.text
    event = response.json()
    if publish:
        await add_ticket_type(client, owner, event["id"])
        response = await client.post(
            f"{API}/events/{event['id']}/publish", headers=owner.headers
        )
        assert response.status_code == 200, response.text
        event = response.json()
    return event


def token_from_email(message: SentEmail) -> str:
    """Pull the ``token`` query value out of the link in an email body."""
    marker = "token="
    start = message.body.index(marker) + len(marker)
    end = message.body.find("\n", start)
    return unquote(message.body[start : end if end != -1 else None])
