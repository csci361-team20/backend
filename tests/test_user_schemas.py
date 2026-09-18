import pytest
from pydantic import ValidationError

from app.modules.users.schemas import UserCreate


def test_user_create_accepts_valid_email():
    user = UserCreate(email="student@nu.edu.kz", password="secret123")
    assert user.email == "student@nu.edu.kz"


def test_user_create_rejects_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="secret123")
