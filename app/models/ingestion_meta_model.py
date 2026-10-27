from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class IngestionMetaModel(Base):
    """SQLAlchemy model representing metadata key-value record in SQLite."""

    __tablename__ = "ingestion_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
