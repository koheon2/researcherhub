"""add author leaderboard indexes

Revision ID: 20260428_0011
Revises: 20260428_0010
Create Date: 2026-04-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260428_0011"
down_revision: Union[str, None] = "20260428_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_paa_country_year_author_paper",
        "paper_author_affiliations",
        ["country_code", "publication_year", "author_id", "paper_id"],
    )
    op.create_index(
        "ix_paa_year_author_paper",
        "paper_author_affiliations",
        ["publication_year", "author_id", "paper_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_paa_year_author_paper", table_name="paper_author_affiliations")
    op.drop_index("ix_paa_country_year_author_paper", table_name="paper_author_affiliations")
