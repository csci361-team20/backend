import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OrganizerProfile(Base):
    __tablename__ = "organizer_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )
    # Public contact details shown on event pages (SRS 4.1)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Identity verification for paid sales (SRS 3.2). Simulated in the MVP:
    # no documents are checked and no real KYC provider is called.
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Kazakhstan IIN (individuals) or BIN (organisations), 12 digits
    tax_id: Mapped[str | None] = mapped_column(String(12), nullable=True)
    verification_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PayoutAccount(Base):
    """Where an organizer's ticket revenue would be paid (SRS 3.2, 4.1).

    Simulated: the account is checked for a well-formed Kazakhstan IBAN but no
    money is ever sent to it in the academic MVP.
    """

    __tablename__ = "payout_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organizer_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizer_profiles.id"),
        unique=True,
        nullable=False,
    )
    holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    iban: Mapped[str] = mapped_column(String(34), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
