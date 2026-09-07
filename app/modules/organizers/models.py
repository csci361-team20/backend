import uuid

from sqlalchemy import ForeignKey, String
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
