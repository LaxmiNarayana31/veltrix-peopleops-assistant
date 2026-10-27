from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class EmployeeModel(Base):
    """SQLAlchemy model representing an employee entity in SQLite."""

    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint("region IN ('IN', 'US', 'DE')", name="check_employee_region"),
        CheckConstraint("level IN ('L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7')", name="check_employee_level"),
        CheckConstraint("role IN ('employee', 'manager', 'hr')", name="check_employee_role"),
    )

    employee_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(10), nullable=False)
    join_date: Mapped[str] = mapped_column(String(10), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    manager_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("employees.employee_id"),
        nullable=True,
    )
