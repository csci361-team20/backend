from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SETTINGS_ROW_ID = 1


class PlatformSettings(Base):
    """Platform-wide settings administrators can change (SRS 4.12).

    A single row (id 1), created on first read with the defaults below.
    """

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=SETTINGS_ROW_ID)
    # SRS 3.3: one-time fee per event in KZT; the frontend demo uses 2,500
    activation_fee_kzt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2500, server_default="2500"
    )
    support_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="support@example.com",
        server_default="support@example.com",
    )
    # Platform-wide switch for new bookings (frontend admin console)
    bookings_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )
