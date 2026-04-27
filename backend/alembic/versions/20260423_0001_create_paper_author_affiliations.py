"""create paper author affiliations

Revision ID: 20260423_0001
Revises:
Create Date: 2026-04-23
"""

from alembic import context, op
import sqlalchemy as sa


revision = "20260423_0001"
down_revision = None
branch_labels = None
depends_on = None


def _create_papers_table() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(length=200), nullable=True),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("citations", sa.Integer(), nullable=True),
        sa.Column("fwci", sa.Float(), nullable=True),
        sa.Column("subfield", sa.String(length=100), nullable=True),
        sa.Column("topic", sa.String(length=200), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("open_access", sa.Boolean(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_papers_year", "papers", ["year"], unique=False)
    op.create_index("ix_papers_subfield", "papers", ["subfield"], unique=False)
    op.create_index("ix_papers_citations", "papers", ["citations"], unique=False)
    op.create_index("ix_papers_doi", "papers", ["doi"], unique=False)


def _create_paper_authors_table() -> None:
    op.create_table(
        "paper_authors",
        sa.Column("paper_id", sa.String(length=20), nullable=False),
        sa.Column("author_id", sa.String(length=20), nullable=False),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("institution_name", sa.String(length=300), nullable=True),
        sa.Column("country", sa.String(length=5), nullable=True),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("paper_id", "author_id"),
    )
    op.create_index("ix_paper_authors_author_id", "paper_authors", ["author_id"], unique=False)


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if not inspector.has_table("papers"):
            _create_papers_table()
        if not inspector.has_table("paper_authors"):
            _create_paper_authors_table()
        if inspector.has_table("paper_author_affiliations"):
            existing_indexes = {
                idx["name"]
                for idx in inspector.get_indexes("paper_author_affiliations")
            }
            if "ix_paa_country_year" not in existing_indexes:
                op.create_index(
                    "ix_paa_country_year",
                    "paper_author_affiliations",
                    ["country_code", "publication_year"],
                    unique=False,
                )
            if "ix_paa_institution_year" not in existing_indexes:
                op.create_index(
                    "ix_paa_institution_year",
                    "paper_author_affiliations",
                    ["institution_name", "publication_year"],
                    unique=False,
                )
            if "ix_paa_paper_id" not in existing_indexes:
                op.create_index("ix_paa_paper_id", "paper_author_affiliations", ["paper_id"], unique=False)
            if "ix_paa_author_id" not in existing_indexes:
                op.create_index("ix_paa_author_id", "paper_author_affiliations", ["author_id"], unique=False)
            return
    else:
        _create_papers_table()
        _create_paper_authors_table()

    op.create_table(
        "paper_author_affiliations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paper_id", sa.String(length=20), nullable=False),
        sa.Column("author_id", sa.String(length=20), nullable=False),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("institution_name", sa.String(length=300), nullable=False),
        sa.Column("institution_ror_id", sa.String(length=100), nullable=True),
        sa.Column("raw_affiliation", sa.Text(), nullable=True),
        sa.Column("country_code", sa.String(length=5), nullable=False),
        sa.Column("publication_year", sa.SmallInteger(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
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
            "author_id",
            "position",
            "institution_name",
            "country_code",
            "source",
            name="uq_paper_author_affiliation_source",
        ),
    )
    op.create_index(
        "ix_paa_country_year",
        "paper_author_affiliations",
        ["country_code", "publication_year"],
        unique=False,
    )
    op.create_index(
        "ix_paa_institution_year",
        "paper_author_affiliations",
        ["institution_name", "publication_year"],
        unique=False,
    )
    op.create_index("ix_paa_paper_id", "paper_author_affiliations", ["paper_id"], unique=False)
    op.create_index("ix_paa_author_id", "paper_author_affiliations", ["author_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_paa_author_id", table_name="paper_author_affiliations")
    op.drop_index("ix_paa_paper_id", table_name="paper_author_affiliations")
    op.drop_index("ix_paa_institution_year", table_name="paper_author_affiliations")
    op.drop_index("ix_paa_country_year", table_name="paper_author_affiliations")
    op.drop_table("paper_author_affiliations")
    op.drop_index("ix_paper_authors_author_id", table_name="paper_authors")
    op.drop_table("paper_authors")
    op.drop_index("ix_papers_doi", table_name="papers")
    op.drop_index("ix_papers_citations", table_name="papers")
    op.drop_index("ix_papers_subfield", table_name="papers")
    op.drop_index("ix_papers_year", table_name="papers")
    op.drop_table("papers")
