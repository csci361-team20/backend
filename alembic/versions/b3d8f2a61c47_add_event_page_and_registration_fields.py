"""add event subtitle, cover image and registration window

Revision ID: b3d8f2a61c47
Revises: a7c2e91f4b10
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d8f2a61c47"
down_revision: str | Sequence[str] | None = "a7c2e91f4b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("events", sa.Column("subtitle", sa.String(255), nullable=True))
    op.add_column(
        "events",
        sa.Column("registration_opens_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("registration_closes_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events", sa.Column("cover_image_url", sa.String(1000), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "cover_image_url")
    op.drop_column("events", "registration_closes_at")
    op.drop_column("events", "registration_opens_at")
    op.drop_column("events", "subtitle")
