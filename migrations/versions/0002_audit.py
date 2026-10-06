"""Append-only audit and durable archive delivery intent."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "audit_events",
        *record_columns(),
        sa.Column("event_key", sa.String(200), nullable=False, unique=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("custodian.identities.id", ondelete="RESTRICT")
        ),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("actor_type IN ('staff','system')", name="actor_type"),
        schema="custodian",
    )
    op.create_index(
        "ix_audit_resource_created",
        "audit_events",
        ["resource_id", "created_at"],
        schema="custodian",
    )
    op.create_table(
        "outbox_items",
        *record_columns(),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.audit_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("destination", sa.String(30), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("event_id", "destination"),
        schema="custodian",
    )
    op.execute("""
        CREATE FUNCTION custodian.reject_history_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Historical evidence is append-only'; END; $$
    """)
    op.execute("""CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON custodian.audit_events FOR EACH STATEMENT EXECUTE FUNCTION custodian.reject_history_change()""")
    op.execute("GRANT SELECT, INSERT ON custodian.audit_events TO custodian_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.outbox_items TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Historical audit records must not be dropped")
