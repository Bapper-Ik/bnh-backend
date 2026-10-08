"""Keep prior evidence immutable while excluding it from a successor draft."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column("excluded_attachment_ids", JSONB(), nullable=False, server_default="[]"),
        schema="custodian",
    )


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
