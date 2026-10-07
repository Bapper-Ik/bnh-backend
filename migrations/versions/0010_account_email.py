"""Single-use invitation purposes and durable credential-free email jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("password_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="custodian",
    )
    op.add_column(
        "recovery_tokens",
        sa.Column("purpose", sa.String(20), nullable=False, server_default="reset"),
        schema="custodian",
    )
    op.create_check_constraint(
        "token_purpose", "recovery_tokens", "purpose IN ('reset', 'activate')", schema="custodian"
    )
    op.create_table(
        "account_emails",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "token_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.recovery_tokens.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column("link_origin", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'failed', 'cancelled')", name="email_status"
        ),
        schema="custodian",
    )
    op.create_index(
        "ix_account_emails_pending",
        "account_emails",
        ["status", "available_at"],
        schema="custodian",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.account_emails TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
