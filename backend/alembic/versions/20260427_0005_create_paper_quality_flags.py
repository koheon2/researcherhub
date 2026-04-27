"""create paper quality flags table

Revision ID: 20260427_0005
Revises: 20260427_0004
Create Date: 2026-04-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_0005"
down_revision: Union[str, None] = "20260427_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_quality_flags",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "paper_id",
            sa.String(length=20),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flag_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('exclude', 'warning', 'info')",
            name="ck_paper_quality_flags_severity",
        ),
        sa.UniqueConstraint(
            "paper_id",
            "flag_type",
            "source",
            name="uq_paper_quality_flags_identity",
        ),
    )
    op.create_index("ix_pqf_severity", "paper_quality_flags", ["severity"])
    op.create_index("ix_pqf_flag_type", "paper_quality_flags", ["flag_type"])
    op.create_index("ix_pqf_paper_id", "paper_quality_flags", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_pqf_paper_id", table_name="paper_quality_flags")
    op.drop_index("ix_pqf_flag_type", table_name="paper_quality_flags")
    op.drop_index("ix_pqf_severity", table_name="paper_quality_flags")
    op.drop_table("paper_quality_flags")
