"""Versioned Board records and immutable Chairman decisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "board_resolutions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.requisition_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "predecessor_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.board_resolutions.id", ondelete="RESTRICT"),
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column(
            "recorded_by",
            sa.Uuid(),
            sa.ForeignKey("custodian.identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column(
            "evidence_id", sa.Uuid(), sa.ForeignKey("custodian.attachments.id", ondelete="RESTRICT")
        ),
        sa.Column("signature", JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("revision_id", "number"),
        schema="custodian",
    )
    op.create_table(
        "board_chairman_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "resolution_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.board_resolutions.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("signature", JSONB(), nullable=False),
        schema="custodian",
    )
    op.execute("""CREATE FUNCTION custodian.protect_board_record() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.signature <> '{}'::jsonb THEN RAISE EXCEPTION 'Signed Board records are immutable'; END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER board_record_immutable BEFORE UPDATE OR DELETE ON custodian.board_resolutions FOR EACH ROW EXECUTE FUNCTION custodian.protect_board_record()"
    )
    op.execute(
        "CREATE TRIGGER board_record_no_truncate BEFORE TRUNCATE ON custodian.board_resolutions FOR EACH STATEMENT EXECUTE FUNCTION custodian.reject_history_change()"
    )
    op.execute(
        "CREATE TRIGGER board_decision_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON custodian.board_chairman_decisions FOR EACH STATEMENT EXECUTE FUNCTION custodian.reject_history_change()"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.board_resolutions TO custodian_app")
    op.execute("GRANT SELECT, INSERT ON custodian.board_chairman_decisions TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Signed Board history must not be dropped")
