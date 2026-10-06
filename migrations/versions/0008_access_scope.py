"""Explicit read-only review grants and private evidence ownership metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def records() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def ref(name: str, table: str) -> sa.Column:
    return sa.Column(
        name, sa.Uuid(), sa.ForeignKey(f"custodian.{table}.id", ondelete="RESTRICT"), nullable=False
    )


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default="false"),
        schema="custodian",
    )
    op.create_table(
        "review_grants",
        *records(),
        ref("identity_id", "identities"),
        ref("entity_id", "entities"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.UniqueConstraint("identity_id", "entity_id"),
        schema="custodian",
    )
    op.create_table(
        "attachments",
        *records(),
        ref("requisition_id", "requisitions"),
        ref("uploaded_by", "identities"),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False, unique=True),
        sa.Column("object_version", sa.String(), nullable=False),
        sa.Column("validation_state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("detached", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default="false"),
        sa.CheckConstraint(
            "kind IN ('request_support','board_resolution')", name="attachment_kind"
        ),
        sa.CheckConstraint("byte_size > 0", name="attachment_size"),
        schema="custodian",
    )
    for table in ("review_grants", "attachments"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON custodian.{table} TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
