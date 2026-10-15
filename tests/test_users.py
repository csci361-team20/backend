from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_users_router_exists():
    assert app is not None


@pytest.mark.anyio
async def test_get_users():
    email = f"test-{uuid4().hex}@example.com"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_response = await client.post(
            "/api/v1/users/",
            json={
                "email": email,
                "full_name": "Test User",
                "password": "testpassword123",
            },
        )

        assert create_response.status_code == 200, create_response.text

        response = await client.get("/api/v1/users/")

    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert any(
        user["email"] == email and user["full_name"] == "Test User" for user in data
    )


@pytest.mark.anyio
async def test_unknown_users_route_returns_404():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/users/00000000-0000-0000-0000-000000000000"
        )

    assert response.status_code == 404
