"""valid default support email

The first default, support@biletflow.local, uses a reserved domain that the
settings endpoint's own email check rejects, so it could not be saved back.

Revision ID: b4d6f8a0c2e1
Revises: a1c3e5f7b9d2
Create Date: 2026-11-24 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d6f8a0c2e1"
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "support@biletflow.local"
NEW = "support@example.com"


def upgrade() -> None:
    op.alter_column("platform_settings", "support_email", server_default=NEW)
    # Only replace the untouched default, never an address an admin set
    op.execute(
        f"UPDATE platform_settings SET support_email = '{NEW}' "
        f"WHERE support_email = '{OLD}'"
    )


def downgrade() -> None:
    op.alter_column("platform_settings", "support_email", server_default=OLD)
