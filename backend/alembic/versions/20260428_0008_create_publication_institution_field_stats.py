"""create publication institution field stats table

Revision ID: 20260428_0008
Revises: 20260428_0007
Create Date: 2026-04-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260428_0008"
down_revision: Union[str, None] = "20260428_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publication_institution_field_stats",
        sa.Column("institution_name", sa.String(length=300), primary_key=True),
        sa.Column("subfield", sa.String(length=100), primary_key=True),
        sa.Column("institution_ror_id", sa.String(length=100), nullable=True),
        sa.Column("institution_match_confidence", sa.Float(), nullable=True),
        sa.Column(
            "institution_normalized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("contributions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_paper_citations", sa.Float(), nullable=False, server_default="0"),
        sa.Column("min_year", sa.Integer(), nullable=True),
        sa.Column("max_year", sa.Integer(), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_pifs_subfield_contributions",
        "publication_institution_field_stats",
        ["subfield", "contributions"],
    )
    op.create_index(
        "ix_pifs_institution_ror_id",
        "publication_institution_field_stats",
        ["institution_ror_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pifs_institution_ror_id",
        table_name="publication_institution_field_stats",
    )
    op.drop_index(
        "ix_pifs_subfield_contributions",
        table_name="publication_institution_field_stats",
    )
    op.drop_table("publication_institution_field_stats")
