"""Private, version-specific export snapshots and durable render jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requisition_exports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "requisition_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.requisitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.requisition_revisions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "requested_by",
            sa.Uuid(),
            sa.ForeignKey("custodian.identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("command_digest", sa.String(), nullable=False),
        sa.Column("request_version", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("include_board", sa.Boolean(), nullable=False),
        sa.Column("includes_bank", sa.Boolean(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("snapshot_digest", sa.String(), nullable=False),
        sa.Column("template_version", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("storage_key", sa.String()),
        sa.Column("object_version", sa.String()),
        sa.Column("file_digest", sa.String()),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("renderer_version", sa.String()),
        sa.Column("font_version", sa.String()),
        sa.Column("last_error", sa.String()),
        sa.UniqueConstraint("requested_by", "idempotency_key"),
        sa.CheckConstraint(
            "status IN ('pending','running','ready','failed','cancelled')", name="export_status"
        ),
        sa.CheckConstraint("attempts >= 0 AND revision_number >= 0", name="export_counters"),
        schema="custodian",
    )
    op.create_index(
        "ix_export_recipient_request",
        "requisition_exports",
        ["requested_by", "requisition_id", "created_at"],
        schema="custodian",
    )
    op.create_index(
        "ix_export_due",
        "requisition_exports",
        ["status", "available_at", "lease_until"],
        schema="custodian",
    )
    op.execute("""CREATE FUNCTION custodian.protect_export() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status = 'ready' THEN RAISE EXCEPTION 'Generated export records are immutable'; END IF;
      IF (to_jsonb(OLD) - ARRAY['status','attempts','available_at','lease_until','lease_token','generated_at','storage_key','object_version','file_digest','byte_size','renderer_version','font_version','last_error'])
         IS DISTINCT FROM
         (to_jsonb(NEW) - ARRAY['status','attempts','available_at','lease_until','lease_token','generated_at','storage_key','object_version','file_digest','byte_size','renderer_version','font_version','last_error'])
      THEN RAISE EXCEPTION 'Export snapshots are immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER export_snapshot_immutable BEFORE UPDATE ON custodian.requisition_exports FOR EACH ROW EXECUTE FUNCTION custodian.protect_export()"
    )
    op.execute(
        "CREATE TRIGGER export_retained BEFORE DELETE OR TRUNCATE ON custodian.requisition_exports FOR EACH STATEMENT EXECUTE FUNCTION custodian.reject_history_change()"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.requisition_exports TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration; preserve export history")
