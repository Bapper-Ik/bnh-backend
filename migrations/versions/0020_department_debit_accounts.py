"""Department sub-accounts for explicitly signed HOD self-approvals."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "department_debit_accounts",
        sa.Column(
            "department_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.departments.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        sa.CheckConstraint("version >= 1", name="department_debit_account_version"),
        schema="custodian",
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON custodian.department_debit_accounts TO custodian_app"
    )


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration; retain department bank settings")
