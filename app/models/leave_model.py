from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class LeaveBalanceModel(Base):
    """SQLAlchemy model representing employee leave balance in SQLite."""

    __tablename__ = "leave_balances"
    __table_args__ = (
        CheckConstraint("leave_type IN ('annual', 'sick')", name="check_leave_type"),
    )

    employee_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("employees.employee_id"),
        primary_key=True,
    )
    leave_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    balance_days: Mapped[float] = mapped_column(Float, nullable=False)


class LeaveRequestModel(Base):
    """SQLAlchemy model representing a leave request record in SQLite."""

    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint("leave_type IN ('annual', 'sick')", name="check_request_leave_type"),
        CheckConstraint("status IN ('pending', 'approved', 'cancelled')", name="check_request_status"),
    )

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("employees.employee_id"),
        nullable=False,
    )
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    working_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
