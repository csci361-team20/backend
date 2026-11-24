"""add auth fields to users and published_at to events

Revision ID: a7c2e91f4b10
Revises: 1e5beb59d9f3
Create Date: 2026-11-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c2e91f4b10"
down_revision: str | Sequence[str] | None = "1e5beb59d9f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("is_suspended", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "events",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Events already past draft were published at some point
    op.execute("UPDATE events SET published_at = created_at WHERE status <> 'draft'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "published_at")
    op.drop_column("users", "token_version")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "is_suspended")
