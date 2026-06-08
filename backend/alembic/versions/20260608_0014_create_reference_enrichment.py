"""create paper reference enrichment tables

Revision ID: 20260608_0014
Revises: 20260520_0013
Create Date: 2026-06-08 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260608_0014"
down_revision: Union[str, None] = "20260520_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_enrichment_status",
        sa.Column("paper_id", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("candidate_bucket", sa.String(length=128), nullable=True),
        sa.Column("candidate_score", sa.Float(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("referenced_works_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("related_works_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'fetched', 'failed', 'skipped')",
            name="ck_paper_enrichment_status_status",
        ),
        sa.PrimaryKeyConstraint("paper_id", "source", name="pk_paper_enrichment_status"),
    )
    op.create_index("ix_pes_status_source", "paper_enrichment_status", ["source", "status"])
    op.create_index("ix_pes_candidate_score", "paper_enrichment_status", ["candidate_score"])

    op.create_table(
        "paper_openalex_enrichments",
        sa.Column("paper_id", sa.String(length=20), nullable=False),
        sa.Column("openalex_id", sa.String(length=32), nullable=False),
        sa.Column("publication_date", sa.String(length=32), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("source_display_name", sa.String(length=500), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("landing_page_url", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("best_oa_url", sa.Text(), nullable=True),
        sa.Column("is_oa", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("primary_location", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("best_oa_location", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("referenced_works_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("related_works_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("paper_id", name="pk_paper_openalex_enrichments"),
    )
    op.create_index("ix_poe_source_display_name", "paper_openalex_enrichments", ["source_display_name"])
    op.create_index("ix_poe_source_type", "paper_openalex_enrichments", ["source_type"])

    op.create_table(
        "paper_reference_edges",
        sa.Column("source_paper_id", sa.String(length=20), nullable=False),
        sa.Column("target_openalex_id", sa.String(length=32), nullable=False),
        sa.Column("target_paper_id", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint(
            "source_paper_id",
            "target_openalex_id",
            "source",
            name="pk_paper_reference_edges",
        ),
    )
    op.create_index("ix_pre_source_paper", "paper_reference_edges", ["source_paper_id"])
    op.create_index("ix_pre_target_openalex", "paper_reference_edges", ["target_openalex_id"])
    op.create_index("ix_pre_target_paper", "paper_reference_edges", ["target_paper_id"])

    op.create_table(
        "paper_related_edges",
        sa.Column("source_paper_id", sa.String(length=20), nullable=False),
        sa.Column("target_openalex_id", sa.String(length=32), nullable=False),
        sa.Column("target_paper_id", sa.String(length=20), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint(
            "source_paper_id",
            "target_openalex_id",
            "source",
            name="pk_paper_related_edges",
        ),
    )
    op.create_index("ix_prel_source_paper", "paper_related_edges", ["source_paper_id"])
    op.create_index("ix_prel_target_paper", "paper_related_edges", ["target_paper_id"])


def downgrade() -> None:
    op.drop_index("ix_prel_target_paper", table_name="paper_related_edges")
    op.drop_index("ix_prel_source_paper", table_name="paper_related_edges")
    op.drop_table("paper_related_edges")
    op.drop_index("ix_pre_target_paper", table_name="paper_reference_edges")
    op.drop_index("ix_pre_target_openalex", table_name="paper_reference_edges")
    op.drop_index("ix_pre_source_paper", table_name="paper_reference_edges")
    op.drop_table("paper_reference_edges")
    op.drop_index("ix_poe_source_type", table_name="paper_openalex_enrichments")
    op.drop_index("ix_poe_source_display_name", table_name="paper_openalex_enrichments")
    op.drop_table("paper_openalex_enrichments")
    op.drop_index("ix_pes_candidate_score", table_name="paper_enrichment_status")
    op.drop_index("ix_pes_status_source", table_name="paper_enrichment_status")
    op.drop_table("paper_enrichment_status")
