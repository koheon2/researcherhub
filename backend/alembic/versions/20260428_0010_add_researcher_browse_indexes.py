"""add researcher browse indexes

Revision ID: 20260428_0010
Revises: 20260428_0009
Create Date: 2026-04-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260428_0010"
down_revision: Union[str, None] = "20260428_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_researchers_citations_desc",
        "researchers",
        ["citations"],
        postgresql_ops={"citations": "DESC"},
    )
    op.create_index(
        "ix_researchers_field_citations",
        "researchers",
        ["field", "citations"],
        postgresql_ops={"citations": "DESC"},
    )
    op.create_index(
        "ix_researchers_country_citations",
        "researchers",
        ["country", "citations"],
        postgresql_ops={"citations": "DESC"},
    )
    op.create_index(
        "ix_researchers_lat_lng",
        "researchers",
        ["lat", "lng"],
    )


def downgrade() -> None:
    op.drop_index("ix_researchers_lat_lng", table_name="researchers")
    op.drop_index("ix_researchers_country_citations", table_name="researchers")
    op.drop_index("ix_researchers_field_citations", table_name="researchers")
    op.drop_index("ix_researchers_citations_desc", table_name="researchers")
