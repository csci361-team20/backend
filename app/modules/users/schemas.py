import uuid
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class UserBase(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    full_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        value = value.strip()
        clean_name = value.replace(" ", "").replace("-", "").replace("'", "")
        if not clean_name.isalpha():
            raise ValueError("Full name must contain only alphabetic characters.")
        return value


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
