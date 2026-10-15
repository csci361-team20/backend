import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class OrganizerProfileCreate(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=255)


class OrganizerProfileUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=2, max_length=255)
    verification_status: VerificationStatus | None = None


class OrganizerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    verification_status: VerificationStatus
