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
    email: EmailStr = Field(
        ...,
        max_length=255,
    )
    full_name: str = Field(..., min_length=2, max_length=100, strip_whitespace=True)


class UserCreate(BaseModel, UserBase):
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
    )

    @field_validator("full_name")
    @classmethod
    def validate_name_chars(cls, value: str) -> str:
        if not value.replace(" ", "").isalpha():
            raise ValueError("Full name must contain only alphabetic characters.")
        return value


class UserResponse(BaseModel, UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    is_platform_admin: bool
    email_verified_at: datetime | None
    created_at: datetime


class UserUpdate(BaseModel):
    pass


class UserDelete(BaseModel):
    pass
