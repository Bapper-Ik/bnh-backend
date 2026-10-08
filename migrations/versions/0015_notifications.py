"""Persistent recipient alerts and leased email delivery."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_items",
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="custodian",
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.audit_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "recipient_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.identities.id", ondelete="RESTRICT"),
            nullable=False,
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
            nullable=False,
        ),
        sa.Column(
            "resolution_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.board_resolutions.id", ondelete="RESTRICT"),
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("template", sa.String(50), nullable=False),
        sa.Column("template_version", sa.String(), server_default="v1", nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("email_status", sa.String(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("recipient_address", sa.String(320)),
        sa.Column("sender_address", sa.String(320)),
        sa.Column("link_origin", sa.String(500)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("provider_id", sa.Uuid()),
        sa.Column("last_error", sa.String(50)),
        sa.UniqueConstraint("event_id", "recipient_id", "kind"),
        sa.CheckConstraint(
            "email_status IN ('pending','sending','accepted','failed','cancelled','disabled','skipped')",
            name="notification_email_state",
        ),
        sa.CheckConstraint("attempts >= 0", name="notification_attempts"),
        schema="custodian",
    )
    op.create_index(
        "ix_notification_recipient_created",
        "notifications",
        ["recipient_id", "created_at", "id"],
        schema="custodian",
    )
    op.create_index(
        "ix_notification_email_due",
        "notifications",
        ["email_status", "available_at", "lease_until"],
        schema="custodian",
    )
    op.create_index(
        "ix_outbox_notification_due",
        "outbox_items",
        ["destination", "status", "available_at"],
        schema="custodian",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON custodian.notifications TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration; preserve notification delivery history")
