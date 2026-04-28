"""add author summary stats

Revision ID: 20260428_0012
Revises: 20260428_0011
Create Date: 2026-04-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260428_0012"
down_revision: Union[str, None] = "20260428_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publication_author_country_year_stats",
        sa.Column("country_code", sa.String(length=5), nullable=False),
        sa.Column("author_id", sa.String(length=20), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("institution_name", sa.String(length=300), nullable=True),
        sa.Column("contributions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_paper_citations", sa.Float(), nullable=False, server_default="0"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("country_code", "author_id", "year", name="pk_publication_author_country_year_stats"),
    )
    op.create_index(
        "ix_pacys_country_year",
        "publication_author_country_year_stats",
        ["country_code", "year"],
    )
    op.create_index(
        "ix_pacys_country_year_contributions",
        "publication_author_country_year_stats",
        ["country_code", "year", "contributions"],
    )
    op.create_index(
        "ix_pacys_author",
        "publication_author_country_year_stats",
        ["author_id"],
    )

    op.create_table(
        "publication_author_facet_year_stats",
        sa.Column("country_code", sa.String(length=5), nullable=False),
        sa.Column("facet_type", sa.String(length=32), nullable=False),
        sa.Column("facet_value", sa.String(length=255), nullable=False),
        sa.Column("author_id", sa.String(length=20), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("institution_name", sa.String(length=300), nullable=True),
        sa.Column("contributions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("papers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_citations", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_paper_citations", sa.Float(), nullable=False, server_default="0"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint(
            "country_code",
            "facet_type",
            "facet_value",
            "author_id",
            "year",
            name="pk_publication_author_facet_year_stats",
        ),
    )
    op.create_index(
        "ix_pafys_country_facet_year",
        "publication_author_facet_year_stats",
        ["country_code", "facet_type", "facet_value", "year"],
    )
    op.create_index(
        "ix_pafys_country_facet_year_contributions",
        "publication_author_facet_year_stats",
        ["country_code", "facet_type", "facet_value", "year", "contributions"],
    )
    op.create_index(
        "ix_pafys_author",
        "publication_author_facet_year_stats",
        ["author_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pafys_author", table_name="publication_author_facet_year_stats")
    op.drop_index("ix_pafys_country_facet_year_contributions", table_name="publication_author_facet_year_stats")
    op.drop_index("ix_pafys_country_facet_year", table_name="publication_author_facet_year_stats")
    op.drop_table("publication_author_facet_year_stats")
    op.drop_index("ix_pacys_author", table_name="publication_author_country_year_stats")
    op.drop_index("ix_pacys_country_year_contributions", table_name="publication_author_country_year_stats")
    op.drop_index("ix_pacys_country_year", table_name="publication_author_country_year_stats")
    op.drop_table("publication_author_country_year_stats")
