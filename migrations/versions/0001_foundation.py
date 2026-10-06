"""Persistent shared identities and least-privilege foundation."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        schema="custodian",
    )
    op.execute("REVOKE ALL ON SCHEMA custodian FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA custodian TO custodian_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.identities TO custodian_app")
    op.execute("GRANT SELECT ON custodian.alembic_version TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; use a reviewed forward migration")
