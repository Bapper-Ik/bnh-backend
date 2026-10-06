"""Individual accounts and revocable opaque sessions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "accounts",
        *record_columns(),
        sa.Column(
            "identity_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.identities.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default="[]"),
        schema="custodian",
    )
    op.create_table(
        "login_sessions",
        *record_columns(),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        schema="custodian",
    )
    op.create_table(
        "login_attempts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        schema="custodian",
    )
    for name in ("accounts", "login_sessions", "login_attempts"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON custodian.{name} TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
