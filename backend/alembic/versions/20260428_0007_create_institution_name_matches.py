"""create institution name matches table

Revision ID: 20260428_0007
Revises: 20260427_0006
Create Date: 2026-04-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260428_0007"
down_revision: Union[str, None] = "20260427_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "institution_name_matches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("raw_institution_name", sa.String(length=300), nullable=False),
        sa.Column("country_code", sa.String(length=5), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=True),
        sa.Column("institution_ror_id", sa.String(length=100), nullable=True),
        sa.Column("openalex_institution_id", sa.String(length=32), nullable=True),
        sa.Column("match_source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('matched', 'ambiguous', 'unmatched')",
            name="ck_institution_name_matches_status",
        ),
        sa.UniqueConstraint(
            "raw_institution_name",
            "country_code",
            name="uq_institution_name_matches_identity",
        ),
    )
    op.create_index("ix_inm_status", "institution_name_matches", ["status"])
    op.create_index("ix_inm_ror_id", "institution_name_matches", ["institution_ror_id"])
    op.create_index("ix_inm_canonical_name", "institution_name_matches", ["canonical_name"])
    op.create_index(
        "ix_inm_country_status",
        "institution_name_matches",
        ["country_code", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_inm_country_status", table_name="institution_name_matches")
    op.drop_index("ix_inm_canonical_name", table_name="institution_name_matches")
    op.drop_index("ix_inm_ror_id", table_name="institution_name_matches")
    op.drop_index("ix_inm_status", table_name="institution_name_matches")
    op.drop_table("institution_name_matches")
