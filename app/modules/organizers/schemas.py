import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.kz_ids import is_valid_iin_bin, is_valid_kz_iban, mask, normalize_iban


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class OrganizerContact(BaseModel):
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(
        None, max_length=50, pattern=r"^\+?[\d\s()-]{5,}$"
    )
    website_url: str | None = Field(None, max_length=500, pattern=r"^https?://\S+$")
    description: str | None = Field(None, max_length=2000)


class OrganizerProfileCreate(OrganizerContact):
    # Defaults to the user's full name
    display_name: str | None = Field(None, min_length=2, max_length=255)


class OrganizerProfileUpdate(OrganizerContact):
    """Contact fields may be cleared with null; the name may not."""

    display_name: str | None = Field(None, min_length=2, max_length=255)


class OrganizerVerificationUpdate(BaseModel):
    verification_status: VerificationStatus


class OrganizerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    verification_status: VerificationStatus
    contact_email: str | None
    contact_phone: str | None
    website_url: str | None
    description: str | None
    verified_at: datetime | None


class MyOrganizerProfileResponse(OrganizerProfileResponse):
    """The owner's own view: includes the (masked) identity details."""

    legal_name: str | None
    tax_id_masked: str | None
    verification_submitted_at: datetime | None


def my_profile_response(profile) -> MyOrganizerProfileResponse:
    return MyOrganizerProfileResponse.model_validate(
        {
            **{
                key: getattr(profile, key)
                for key in OrganizerProfileResponse.model_fields
            },
            "legal_name": profile.legal_name,
            "tax_id_masked": mask(profile.tax_id) if profile.tax_id else None,
            "verification_submitted_at": profile.verification_submitted_at,
        }
    )


class IdentityVerificationCreate(BaseModel):
    """Simulated identity check: a legal name and a valid IIN/BIN."""

    legal_name: str = Field(..., min_length=2, max_length=255)
    tax_id: str = Field(..., description="12-digit IIN (person) or BIN (organisation)")

    @field_validator("tax_id")
    @classmethod
    def validate_tax_id(cls, value: str) -> str:
        value = value.strip()
        if not is_valid_iin_bin(value):
            raise ValueError("Enter a valid 12-digit IIN or BIN")
        return value


class PayoutAccountUpsert(BaseModel):
    holder_name: str = Field(..., min_length=2, max_length=255)
    bank_name: str = Field(..., min_length=2, max_length=255)
    iban: str = Field(..., description="Kazakhstan IBAN, e.g. KZ86125KZT5004100100")

    @field_validator("iban")
    @classmethod
    def validate_iban(cls, value: str) -> str:
        if not is_valid_kz_iban(value):
            raise ValueError("Enter a valid Kazakhstan IBAN (20 characters, KZ…)")
        return normalize_iban(value)


class PayoutAccountResponse(BaseModel):
    holder_name: str
    bank_name: str
    iban_masked: str
    is_verified: bool
    verified_at: datetime | None
    is_simulated: bool = True


def payout_response(account) -> PayoutAccountResponse:
    return PayoutAccountResponse(
        holder_name=account.holder_name,
        bank_name=account.bank_name,
        iban_masked=mask(account.iban),
        is_verified=account.is_verified,
        verified_at=account.verified_at,
    )
