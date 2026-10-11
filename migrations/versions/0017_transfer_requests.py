"""Company debit profiles and one automatic bank instruction per approved revision."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_debit_accounts",
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.entities.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        sa.CheckConstraint("version >= 1", name="debit_account_version"),
        schema="custodian",
    )
    op.add_column(
        "requisition_exports",
        sa.Column("document_type", sa.String(), nullable=False, server_default="requisition"),
        schema="custodian",
    )
    op.create_check_constraint(
        "export_document_type",
        "requisition_exports",
        "document_type IN ('requisition', 'bank_transfer')",
        schema="custodian",
    )
    op.create_index(
        "uq_transfer_revision",
        "requisition_exports",
        ["revision_id"],
        unique=True,
        schema="custodian",
        postgresql_where=sa.text("document_type = 'bank_transfer'"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON custodian.company_debit_accounts TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration; retain signed transfer instructions")
