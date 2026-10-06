"""Expiring single-use recovery tokens; preserve already-applied migration history."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        schema="custodian",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.recovery_tokens TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
