"""Versioned requisitions, signatures, immutable decisions and idempotent commands."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def records() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def ref(name: str, target: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.Uuid(),
        sa.ForeignKey(f"custodian.{target}.id", ondelete="RESTRICT"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.execute("CREATE SEQUENCE custodian.request_reference")
    op.execute("GRANT USAGE ON SEQUENCE custodian.request_reference TO custodian_app")
    op.create_table(
        "requisitions",
        *records(),
        sa.Column("reference", sa.String(), unique=True, nullable=False),
        ref("requester_id", "identities"),
        ref("entity_id", "entities"),
        ref("department_id", "departments"),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("creation_digest", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("total", sa.Numeric(17, 2), nullable=False),
        sa.Column("current_revision_id", sa.Uuid()),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("requester_id", "creation_key"),
        schema="custodian",
    )
    op.create_table(
        "requisition_revisions",
        *records(),
        ref("requisition_id", "requisitions"),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("total", sa.Numeric(17, 2), nullable=False),
        sa.Column("requester_name", sa.String(), nullable=False),
        sa.Column("department_name", sa.String(), nullable=False),
        sa.Column("entity_name", sa.String(), nullable=False),
        sa.Column("authority", sa.String(), nullable=False),
        ref("approver_id", "identities", True),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("routing_explanation", sa.String(), nullable=False),
        sa.Column("content_digest", sa.String(), nullable=False),
        sa.Column("signature", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("requisition_id", "number"),
        schema="custodian",
    )
    op.create_foreign_key(
        "fk_current_revision",
        "requisitions",
        "requisition_revisions",
        ["current_revision_id"],
        ["id"],
        source_schema="custodian",
        referent_schema="custodian",
        ondelete="RESTRICT",
    )
    op.create_table(
        "decisions",
        *records(),
        ref("revision_id", "requisition_revisions"),
        ref("actor_id", "identities"),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("signature", postgresql.JSONB(), nullable=False),
        sa.Column("content_digest", sa.String(), nullable=False),
        sa.UniqueConstraint("revision_id"),
        schema="custodian",
    )
    op.create_table(
        "signing_challenges",
        *records(),
        ref("requisition_id", "requisitions"),
        ref("actor_id", "identities"),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default="false"),
        schema="custodian",
    )
    op.create_table(
        "command_results",
        *records(),
        ref("actor_id", "identities"),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("payload_digest", sa.String(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("actor_id", "idempotency_key"),
        schema="custodian",
    )
    for name in ("requisitions", "signing_challenges"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON custodian.{name} TO custodian_app")
    for name in ("requisition_revisions", "decisions", "command_results"):
        op.execute(f"GRANT SELECT, INSERT ON custodian.{name} TO custodian_app")
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON custodian.{name} FOR EACH STATEMENT EXECUTE FUNCTION custodian.reject_history_change()"
        )
    op.create_index(
        "ix_requests_requester_created",
        "requisitions",
        ["requester_id", "created_at"],
        schema="custodian",
    )


def downgrade() -> None:
    raise RuntimeError("Signed historical records must not be dropped")
