"""create paper facet year summary table

Revision ID: 20260427_0004
Revises: 20260427_0003
Create Date: 2026-04-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_0004"
down_revision: Union[str, None] = "20260427_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_facet_year_summary",
        sa.Column("facet_type", sa.String(), primary_key=True),
        sa.Column("facet_value", sa.String(), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("paper_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_paper_citations", sa.Float(), nullable=False, server_default="0"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_paper_facet_year_summary_lookup",
        "paper_facet_year_summary",
        ["facet_type", "facet_value", "year"],
    )


def downgrade() -> None:
    op.drop_index("ix_paper_facet_year_summary_lookup", table_name="paper_facet_year_summary")
    op.drop_table("paper_facet_year_summary")
