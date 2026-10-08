"""Frozen submission context and idempotent private attachment uploads."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("requisitions", "requisition_revisions"):
        op.add_column(
            table,
            sa.Column("context", JSONB(), nullable=False, server_default="{}"),
            schema="custodian",
        )
    op.add_column(
        "attachments", sa.Column("upload_key", sa.Uuid(), unique=True), schema="custodian"
    )

    op.execute("""
        CREATE FUNCTION custodian.protect_submitted_attachment() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            IF OLD.frozen THEN
                RAISE EXCEPTION 'Submitted attachment metadata is immutable';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER protect_submitted_attachment BEFORE UPDATE OR DELETE
        ON custodian.attachments FOR EACH ROW
        EXECUTE FUNCTION custodian.protect_submitted_attachment()
    """)


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
