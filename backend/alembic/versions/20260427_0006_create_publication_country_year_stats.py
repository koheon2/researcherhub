"""create publication country year stats table

Revision ID: 20260427_0006
Revises: 20260427_0005
Create Date: 2026-04-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_0006"
down_revision: Union[str, None] = "20260427_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publication_country_year_stats",
        sa.Column("country_code", sa.String(length=5), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("contributions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_paper_citations", sa.Float(), nullable=False, server_default="0"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_publication_country_year_stats_lookup",
        "publication_country_year_stats",
        ["country_code", "year"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publication_country_year_stats_lookup",
        table_name="publication_country_year_stats",
    )
    op.drop_table("publication_country_year_stats")
