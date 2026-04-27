"""create paper facets

Revision ID: 20260424_0002
Revises: 20260423_0001
Create Date: 2026-04-24
"""

from alembic import context, op
import sqlalchemy as sa


revision = "20260424_0002"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if inspector.has_table("paper_facets"):
            existing_indexes = {idx["name"] for idx in inspector.get_indexes("paper_facets")}
            if "ix_pf_type_value" not in existing_indexes:
                op.create_index(
                    "ix_pf_type_value",
                    "paper_facets",
                    ["facet_type", "facet_value"],
                    unique=False,
                )
            if "ix_pf_paper_id" not in existing_indexes:
                op.create_index("ix_pf_paper_id", "paper_facets", ["paper_id"], unique=False)
            if "ix_pf_type_source" not in existing_indexes:
                op.create_index(
                    "ix_pf_type_source",
                    "paper_facets",
                    ["facet_type", "source"],
                    unique=False,
                )
            return

    op.create_table(
        "paper_facets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_id", sa.String(length=20), nullable=False),
        sa.Column("facet_type", sa.String(length=32), nullable=False),
        sa.Column("facet_value", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "paper_id",
            "facet_type",
            "facet_value",
            "source",
            name="uq_paper_facets_identity",
        ),
    )
    op.create_index("ix_pf_type_value", "paper_facets", ["facet_type", "facet_value"], unique=False)
    op.create_index("ix_pf_paper_id", "paper_facets", ["paper_id"], unique=False)
    op.create_index("ix_pf_type_source", "paper_facets", ["facet_type", "source"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pf_type_source", table_name="paper_facets")
    op.drop_index("ix_pf_paper_id", table_name="paper_facets")
    op.drop_index("ix_pf_type_value", table_name="paper_facets")
    op.drop_table("paper_facets")
