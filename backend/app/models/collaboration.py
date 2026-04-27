from sqlalchemy import String, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class Collaboration(Base):
    __tablename__ = "collaborations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 항상 researcher_a < researcher_b (알파벳 순) 로 저장 → 중복 방지
    researcher_a: Mapped[str] = mapped_column(String, nullable=False, index=True)
    researcher_b: Mapped[str] = mapped_column(String, nullable=False, index=True)
    paper_count: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint("researcher_a", "researcher_b", name="uq_collab_pair"),
    )
