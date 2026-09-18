from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_all_users_stub():
    response = client.get("/api/v1/users/")
    assert response.status_code == 200
    assert response.json() == {"1": "neo"}
