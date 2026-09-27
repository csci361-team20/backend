import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_users_router_exists():
    assert app is not None


@pytest.mark.anyio
async def test_get_users():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/users/")

    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["email"] == "test@example.com"
    assert data[0]["full_name"] == "Test User"


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
