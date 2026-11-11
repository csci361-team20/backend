from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.users.schemas import UserResponse, UserUpdate


def test_update_rejects_digits_in_name():
    with pytest.raises(ValidationError):
        UserUpdate(full_name="User 123")


def test_update_accepts_valid_name_and_null():
    assert UserUpdate(full_name="Anna-Maria O'Neil").full_name == "Anna-Maria O'Neil"
    assert UserUpdate(full_name=None).full_name is None


def test_response_does_not_apply_input_rules():
    response = UserResponse(
        id=uuid4(),
        email="a@example.com",
        full_name="User 123",
        created_at=datetime.now(UTC),
    )
    assert response.full_name == "User 123"
