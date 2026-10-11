"""Temporary owner-scoped supporting uploads before draft creation."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staged_uploads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "uploaded_by",
            sa.Uuid(),
            sa.ForeignKey("custodian.identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("custodian.entities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="custodian",
    )
    op.create_index(
        "ix_staged_uploads_expires_at", "staged_uploads", ["expires_at"], schema="custodian"
    )
    op.create_index(
        "ix_staged_uploads_uploaded_by", "staged_uploads", ["uploaded_by"], schema="custodian"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON custodian.staged_uploads TO custodian_app")


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration; protect pending documents")
