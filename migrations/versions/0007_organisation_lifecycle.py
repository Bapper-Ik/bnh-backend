"""Entity/department directory metadata and lifecycle state."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("entities", "departments"):
        op.add_column(name, sa.Column("code", sa.String(40)), schema="custodian")
        op.execute(f"UPDATE custodian.{name} SET code = replace(id::text, '-', '')")
        op.alter_column(name, "code", nullable=False, schema="custodian")
        op.add_column(
            name,
            sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
            schema="custodian",
        )
    op.create_unique_constraint("uq_entities_code", "entities", ["code"], schema="custodian")
    op.create_unique_constraint(
        "uq_departments_entity_code", "departments", ["entity_id", "code"], schema="custodian"
    )
    op.add_column(
        "entities",
        sa.Column("kind", sa.String(20), nullable=False, server_default="subsidiary"),
        schema="custodian",
    )
    op.create_check_constraint(
        "entity_kind", "entities", "kind IN ('holding','subsidiary')", schema="custodian"
    )


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
