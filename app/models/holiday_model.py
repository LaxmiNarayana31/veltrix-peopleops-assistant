from typing import Optional

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class HolidayModel(Base):
    """SQLAlchemy model representing an extracted public holiday entity in SQLite."""

    __tablename__ = "holidays"
    __table_args__ = (
        Index("idx_holidays_region_date", "region", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    region: Mapped[str] = mapped_column(String(10), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_doc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_date: Mapped[str] = mapped_column(String(10), nullable=False)
