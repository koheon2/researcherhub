from sqlalchemy import String, Integer, Float, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class Researcher(Base):
    __tablename__ = "researchers"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # OpenAlex author ID
    name: Mapped[str] = mapped_column(String, nullable=False)
    institution: Mapped[str | None] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    citations: Mapped[int] = mapped_column(Integer, default=0)
    h_index: Mapped[int] = mapped_column(Integer, default=0)
    works_count: Mapped[int] = mapped_column(Integer, default=0)
    recent_papers: Mapped[int] = mapped_column(Integer, default=0)  # last 2yr

    field: Mapped[str | None] = mapped_column(String)       # primary field label
    umap_x: Mapped[float | None] = mapped_column(Float)     # 2D embedding x
    umap_y: Mapped[float | None] = mapped_column(Float)     # 2D embedding y

    openalex_url: Mapped[str | None] = mapped_column(Text)

    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
