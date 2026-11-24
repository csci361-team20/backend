import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    is_platform_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_suspended: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    suspension_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Language for emails and notifications: kk, ru or en (SRS 7)
    preferred_language: Mapped[str] = mapped_column(
        String(2), nullable=False, default="en", server_default="en"
    )
    # Copied into every access token; incrementing it signs the user out everywhere
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None
