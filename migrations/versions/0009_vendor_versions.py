"""Stable entity-scoped vendors and append-only beneficiary/contact versions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def records() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def ref(name: str, table: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.Uuid(),
        sa.ForeignKey(f"custodian.{table}.id", ondelete="RESTRICT"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "vendors",
        *records(),
        ref("entity_id", "entities"),
        ref("created_by", "identities"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_version_id", sa.Uuid(), nullable=False),
        schema="custodian",
    )
    op.create_table(
        "beneficiary_versions",
        *records(),
        ref("vendor_id", "vendors"),
        sa.Column("bank_name", sa.String(150), nullable=False),
        sa.Column("account_number", sa.String(100), nullable=False),
        sa.Column("account_name", sa.String(250), nullable=False),
        schema="custodian",
    )
    op.create_table(
        "vendor_versions",
        *records(),
        ref("vendor_id", "vendors"),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        ref("beneficiary_id", "beneficiary_versions", True),
        sa.UniqueConstraint("vendor_id", "number"),
        schema="custodian",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.vendors TO custodian_app")
    for table in ("vendor_versions", "beneficiary_versions"):
        op.execute(f"GRANT SELECT, INSERT ON custodian.{table} TO custodian_app")
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON custodian.{table} FOR EACH STATEMENT EXECUTE FUNCTION custodian.reject_history_change()"
        )


def downgrade() -> None:
    raise RuntimeError("Historical beneficiary versions must not be dropped")
