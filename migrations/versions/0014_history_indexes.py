"""Indexes for scoped history and audit navigation."""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_entity_created",
        "audit_events",
        ["entity_id", "created_at", "id"],
        schema="custodian",
    )
    op.create_index(
        "ix_audit_actor_created",
        "audit_events",
        ["actor_id", "created_at", "id"],
        schema="custodian",
    )
    op.create_index(
        "ix_request_entity_created",
        "requisitions",
        ["entity_id", "created_at", "id"],
        schema="custodian",
    )


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
