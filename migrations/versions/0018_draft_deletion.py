"""Retain audit/evidence while hiding requester-deleted drafts."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="custodian",
    )
    op.create_check_constraint(
        "only_drafts_deleted",
        "requisitions",
        "deleted_at IS NULL OR state = 'DRAFT'",
        schema="custodian",
    )


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration; retain deletion history")
