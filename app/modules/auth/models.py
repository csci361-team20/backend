from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RevokedRefreshToken(Base):
    """A refresh token signed out on one device (sign-out without "everywhere").

    Stored as a SHA-256 digest; rows past ``expires_at`` can be deleted, since
    the token would be refused as expired anyway.
    """

    __tablename__ = "revoked_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
