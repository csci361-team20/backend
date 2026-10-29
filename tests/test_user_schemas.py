import pytest
from pydantic import ValidationError

from app.modules.users.schemas import UserCreate


def test_user_create_accepts_valid_data():
    user = UserCreate(
        email="student@nu.edu.kz",
        full_name="Zhandaulet Seidekhanov",
        password="secret123",
    )
    assert user.email == "student@nu.edu.kz"


def test_user_create_rejects_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", full_name="Zhandaulet", password="secret123")


def test_user_create_rejects_non_alphabetic_name():
    with pytest.raises(ValidationError):
        UserCreate(
            email="student@nu.edu.kz", full_name="Zh4nd4ulet99", password="secret123"
        )
