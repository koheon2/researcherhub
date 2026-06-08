from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from app.db.database import Base


class Paper(Base):
    __tablename__ = "papers"

    id = Column(String(20), primary_key=True)
    title = Column(Text)
    doi = Column(String(200), index=True)
    year = Column(SmallInteger, index=True)
    citations = Column(Integer, default=0, index=True)
    fwci = Column(Float)
    subfield = Column(String(100), index=True)
    topic = Column(String(200))
    abstract = Column(Text)
    open_access = Column(Boolean, default=False)
    type = Column(String(50))

    authors = relationship(
        "PaperAuthor", back_populates="paper", cascade="all, delete-orphan"
    )
    facets = relationship(
        "PaperFacet", back_populates="paper", cascade="all, delete-orphan"
    )
    quality_flags = relationship(
        "PaperQualityFlag", back_populates="paper", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_papers_topic_year_citations", "topic", "year", "citations"),
        Index("ix_papers_year_citations", "year", "citations"),
    )


class PaperAuthor(Base):
    __tablename__ = "paper_authors"

    paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    author_id = Column(String(20), primary_key=True, index=True)
    author_name = Column(String(200))
    position = Column(SmallInteger)
    institution_name = Column(String(300))
    country = Column(String(5))

    paper = relationship("Paper", back_populates="authors")

    __table_args__ = (
        Index("ix_pa_paper_position", "paper_id", "position"),
    )


class PaperAuthorAffiliation(Base):
    __tablename__ = "paper_author_affiliations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id = Column(String(20), nullable=False)
    author_name = Column(String(200))
    position = Column(SmallInteger, nullable=False, default=0)
    institution_name = Column(String(300), nullable=False)
    institution_ror_id = Column(String(100))
    raw_affiliation = Column(Text)
    country_code = Column(String(5), nullable=False)
    publication_year = Column(SmallInteger)
    source = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=False, default=0.6)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "author_id",
            "position",
            "institution_name",
            "country_code",
            "source",
            name="uq_paper_author_affiliation_source",
        ),
        Index("ix_paa_country_year", "country_code", "publication_year"),
        Index("ix_paa_institution_year", "institution_name", "publication_year"),
        Index("ix_paa_paper_id", "paper_id"),
        Index("ix_paa_author_id", "author_id"),
    )


class InstitutionNameMatch(Base):
    __tablename__ = "institution_name_matches"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_institution_name = Column(String(300), nullable=False)
    country_code = Column(String(5), nullable=False)
    canonical_name = Column(String(300))
    institution_ror_id = Column(String(100))
    openalex_institution_id = Column(String(32))
    match_source = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    status = Column(String(16), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "raw_institution_name",
            "country_code",
            name="uq_institution_name_matches_identity",
        ),
        Index("ix_inm_status", "status"),
        Index("ix_inm_ror_id", "institution_ror_id"),
        Index("ix_inm_canonical_name", "canonical_name"),
        Index("ix_inm_country_status", "country_code", "status"),
    )


class PaperFacet(Base):
    __tablename__ = "paper_facets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    facet_type = Column(String(32), nullable=False)
    facet_value = Column(String(255), nullable=False)
    source = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=False, default=0.55)
    rank = Column(SmallInteger, nullable=False, default=1)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    paper = relationship("Paper", back_populates="facets")

    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "facet_type",
            "facet_value",
            "source",
            name="uq_paper_facets_identity",
        ),
        Index("ix_pf_type_value", "facet_type", "facet_value"),
        Index("ix_pf_paper_id", "paper_id"),
        Index("ix_pf_type_source", "facet_type", "source"),
    )


class PaperQualityFlag(Base):
    __tablename__ = "paper_quality_flags"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    flag_type = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    reason = Column(Text, nullable=False)
    source = Column(String(64), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    paper = relationship("Paper", back_populates="quality_flags")

    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "flag_type",
            "source",
            name="uq_paper_quality_flags_identity",
        ),
        Index("ix_pqf_severity", "severity"),
        Index("ix_pqf_flag_type", "flag_type"),
        Index("ix_pqf_paper_id", "paper_id"),
        Index("ix_pqf_paper_severity", "paper_id", "severity"),
    )


class PaperEnrichmentStatus(Base):
    __tablename__ = "paper_enrichment_status"

    paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    source = Column(String(64), primary_key=True, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    candidate_bucket = Column(String(128))
    candidate_score = Column(Float)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempted_at = Column(DateTime(timezone=True))
    fetched_at = Column(DateTime(timezone=True))
    error = Column(Text)
    referenced_works_count = Column(Integer, nullable=False, default=0)
    related_works_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_pes_status_source", "source", "status"),
        Index("ix_pes_candidate_score", "candidate_score"),
    )


class PaperOpenAlexEnrichment(Base):
    __tablename__ = "paper_openalex_enrichments"

    paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    openalex_id = Column(String(32), nullable=False)
    publication_date = Column(String(32))
    language = Column(String(16))
    source_id = Column(String(64))
    source_display_name = Column(String(500))
    source_type = Column(String(64))
    landing_page_url = Column(Text)
    pdf_url = Column(Text)
    best_oa_url = Column(Text)
    is_oa = Column(Boolean, nullable=False, default=False)
    ids = Column(JSON)
    primary_location = Column(JSON)
    best_oa_location = Column(JSON)
    referenced_works_count = Column(Integer, nullable=False, default=0)
    related_works_count = Column(Integer, nullable=False, default=0)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_poe_source_display_name", "source_display_name"),
        Index("ix_poe_source_type", "source_type"),
    )


class PaperReferenceEdge(Base):
    __tablename__ = "paper_reference_edges"

    source_paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    target_openalex_id = Column(String(32), primary_key=True, nullable=False)
    target_paper_id = Column(String(20), ForeignKey("papers.id", ondelete="SET NULL"))
    source = Column(String(64), primary_key=True, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_pre_source_paper", "source_paper_id"),
        Index("ix_pre_target_openalex", "target_openalex_id"),
        Index("ix_pre_target_paper", "target_paper_id"),
    )


class PaperRelatedEdge(Base):
    __tablename__ = "paper_related_edges"

    source_paper_id = Column(
        String(20),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    target_openalex_id = Column(String(32), primary_key=True, nullable=False)
    target_paper_id = Column(String(20), ForeignKey("papers.id", ondelete="SET NULL"))
    rank = Column(Integer, nullable=False)
    source = Column(String(64), primary_key=True, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_prel_source_paper", "source_paper_id"),
        Index("ix_prel_target_paper", "target_paper_id"),
    )


class PublicationInstitutionFieldStat(Base):
    __tablename__ = "publication_institution_field_stats"

    institution_name = Column(String(300), primary_key=True)
    subfield = Column(String(100), primary_key=True)
    institution_ror_id = Column(String(100))
    institution_match_confidence = Column(Float)
    institution_normalized = Column(Boolean, nullable=False, default=False)
    contributions = Column(BigInteger, nullable=False, default=0)
    papers = Column(BigInteger, nullable=False, default=0)
    total_citations = Column(BigInteger, nullable=False, default=0)
    avg_paper_citations = Column(Float, nullable=False, default=0)
    min_year = Column(Integer)
    max_year = Column(Integer)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index(
            "ix_pifs_subfield_contributions",
            "subfield",
            "contributions",
        ),
        Index("ix_pifs_institution_ror_id", "institution_ror_id"),
    )


class PublicationAuthorCountryYearStat(Base):
    __tablename__ = "publication_author_country_year_stats"

    country_code = Column(String(5), primary_key=True)
    author_id = Column(String(20), primary_key=True)
    year = Column(SmallInteger, primary_key=True)
    author_name = Column(String(200))
    institution_name = Column(String(300))
    contributions = Column(BigInteger, nullable=False, default=0)
    papers = Column(BigInteger, nullable=False, default=0)
    total_citations = Column(BigInteger, nullable=False, default=0)
    avg_paper_citations = Column(Float, nullable=False, default=0)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_pacys_country_year", "country_code", "year"),
        Index("ix_pacys_country_year_contributions", "country_code", "year", "contributions"),
        Index("ix_pacys_author", "author_id"),
    )


class PublicationAuthorFacetYearStat(Base):
    __tablename__ = "publication_author_facet_year_stats"

    country_code = Column(String(5), primary_key=True)
    facet_type = Column(String(32), primary_key=True)
    facet_value = Column(String(255), primary_key=True)
    author_id = Column(String(20), primary_key=True)
    year = Column(SmallInteger, primary_key=True)
    author_name = Column(String(200))
    institution_name = Column(String(300))
    contributions = Column(BigInteger, nullable=False, default=0)
    papers = Column(BigInteger, nullable=False, default=0)
    total_citations = Column(BigInteger, nullable=False, default=0)
    avg_paper_citations = Column(Float, nullable=False, default=0)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_pafys_country_facet_year", "country_code", "facet_type", "facet_value", "year"),
        Index(
            "ix_pafys_country_facet_year_contributions",
            "country_code",
            "facet_type",
            "facet_value",
            "year",
            "contributions",
        ),
        Index("ix_pafys_author", "author_id"),
    )
