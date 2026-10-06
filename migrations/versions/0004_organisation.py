"""Companies, departments, memberships and protected office appointments."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def record_columns() -> list[sa.Column]:
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
    op.create_table(
        "entities",
        *record_columns(),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        schema="custodian",
    )
    op.create_table(
        "departments",
        *record_columns(),
        ref("entity_id", "entities"),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("entity_id", "name"),
        schema="custodian",
    )
    op.create_table(
        "memberships",
        *record_columns(),
        ref("identity_id", "identities"),
        ref("entity_id", "entities"),
        ref("department_id", "departments"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.UniqueConstraint("identity_id", "entity_id"),
        schema="custodian",
    )
    op.create_table(
        "offices",
        *record_columns(),
        ref("identity_id", "identities"),
        ref("entity_id", "entities"),
        ref("department_id", "departments", True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("authorisation_reference", sa.String(), nullable=False),
        sa.CheckConstraint(
            "(role='hod' AND department_id IS NOT NULL) OR (role IN ('chief_of_staff','md','secretary','chairman') AND department_id IS NULL)",
            name="office_scope",
        ),
        schema="custodian",
    )
    op.execute(
        "CREATE UNIQUE INDEX unique_active_executive ON custodian.offices(entity_id,role) WHERE active AND department_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX unique_active_hod ON custodian.offices(department_id) WHERE active AND role='hod'"
    )
    for name in ("entities", "departments", "memberships", "offices"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON custodian.{name} TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration")
