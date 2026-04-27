from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
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
