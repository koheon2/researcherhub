"""create publication summary tables

Revision ID: 20260427_0003
Revises: 20260424_0002
Create Date: 2026-04-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_0003"
down_revision: Union[str, None] = "20260424_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publication_country_stats",
        sa.Column("country_code", sa.String(length=2), primary_key=True),
        sa.Column("contributions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_paper_citations", sa.Float(), nullable=False, server_default="0"),
        sa.Column("top_field", sa.String(), nullable=True),
        sa.Column("min_year", sa.Integer(), nullable=True),
        sa.Column("max_year", sa.Integer(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_publication_country_stats_contributions",
        "publication_country_stats",
        ["contributions"],
    )

    op.create_table(
        "publication_institution_stats",
        sa.Column("institution_name", sa.String(), primary_key=True),
        sa.Column("contributions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_paper_citations", sa.Float(), nullable=False, server_default="0"),
        sa.Column("top_field", sa.String(), nullable=True),
        sa.Column("min_year", sa.Integer(), nullable=True),
        sa.Column("max_year", sa.Integer(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_publication_institution_stats_contributions",
        "publication_institution_stats",
        ["contributions"],
    )

    op.create_table(
        "paper_facet_summary",
        sa.Column("facet_type", sa.String(), primary_key=True),
        sa.Column("facet_value", sa.String(), primary_key=True),
        sa.Column("paper_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("recent_papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("previous_papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("growth_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_paper_facet_summary_trending",
        "paper_facet_summary",
        ["facet_type", "growth_pct", "paper_count"],
    )


def downgrade() -> None:
    op.drop_index("ix_paper_facet_summary_trending", table_name="paper_facet_summary")
    op.drop_table("paper_facet_summary")
    op.drop_index("ix_publication_institution_stats_contributions", table_name="publication_institution_stats")
    op.drop_table("publication_institution_stats")
    op.drop_index("ix_publication_country_stats_contributions", table_name="publication_country_stats")
    op.drop_table("publication_country_stats")
