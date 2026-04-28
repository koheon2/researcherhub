"""add progress query indexes

Revision ID: 20260428_0009
Revises: 20260428_0008
Create Date: 2026-04-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260428_0009"
down_revision: Union[str, None] = "20260428_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_pf_type_value_paper",
        "paper_facets",
        ["facet_type", "facet_value", "paper_id"],
    )
    op.create_index(
        "ix_paa_country_year_paper",
        "paper_author_affiliations",
        ["country_code", "publication_year", "paper_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_paa_country_year_paper", table_name="paper_author_affiliations")
    op.drop_index("ix_pf_type_value_paper", table_name="paper_facets")
