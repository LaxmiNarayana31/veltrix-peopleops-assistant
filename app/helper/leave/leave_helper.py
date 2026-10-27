"""Leave management service implementing working days, validations, and transactions."""

import datetime
from datetime import date, timedelta
import logging
from typing import Optional, Set
import uuid

from sqlalchemy import case, select

from app.dto.chat_dto import RequestContext
from app.exceptions.custom_exceptions import AppException, DatabaseException, LeaveRuleViolationException
from app.models.holiday_model import HolidayModel
from app.models.leave_model import LeaveBalanceModel, LeaveRequestModel
from app.utils.constants import LEAVE_YEAR, LeaveRequestStatus, LeaveType
from config.app_config import REFERENCE_DATE
from config.database import get_db_session

logger = logging.getLogger(__name__)


class LeaveService:
    """Implements leave business logic: working days, validation, application, and cancellation."""

    @classmethod
    def normalize_leave_type(cls, leave_type_str: str) -> LeaveType:
        """Normalize common phrases ('annual leave', 'vacation', 'sick leave') into LeaveType enum."""
        lt = (leave_type_str or "").lower().strip()
        if any(k in lt for k in ("annual", "vacation", "earned", "casual", "pto")):
            return LeaveType.ANNUAL
        if any(k in lt for k in ("sick", "medical")):
            return LeaveType.SICK
        try:
            return LeaveType(lt)
        except ValueError:
            raise LeaveRuleViolationException("Leave type must be either 'annual' or 'sick'")

    @classmethod
    def get_public_holidays(cls, region: str, reference_date: Optional[date] = None) -> Set[str]:
        """Fetch active public holiday dates (YYYY-MM-DD) for a region based on Section 5 calendar selection."""
        try:
            ref_date = reference_date or REFERENCE_DATE
            ref_str = ref_date.isoformat()

            with get_db_session() as session:
                stmt = (
                    select(HolidayModel.source_doc_id, HolidayModel.region, HolidayModel.effective_date)
                    .where(
                        HolidayModel.region.in_([region, "GLOBAL"]),
                        HolidayModel.effective_date <= ref_str,
                    )
                    .distinct()
                    .order_by(
                        case((HolidayModel.region == region, 1), else_=0).desc(),
                        HolidayModel.effective_date.desc(),
                    )
                )
                calendars = session.execute(stmt).all()

                if not calendars:
                    fallback_stmt = select(HolidayModel.date).where(HolidayModel.region == region)
                    return set(session.scalars(fallback_stmt).all())

                winning_calendar_id = calendars[0][0]
                win_stmt = select(HolidayModel.date).where(HolidayModel.source_doc_id == winning_calendar_id)
                return set(session.scalars(win_stmt).all())
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed fetching holidays for region %s", region)
            raise DatabaseException("Error retrieving public holidays") from exc

    @classmethod
    def compute_working_days(
        cls,
        start_date: date,
        end_date: date,
        region: str,
        reference_date: Optional[date] = None,
    ) -> int:
        """Calculate working days between start_date and end_date (inclusive), excluding weekends and holidays."""
        try:
            if end_date < start_date:
                return 0

            holidays = cls.get_public_holidays(region, reference_date)
            current = start_date
            working_days = 0

            while current <= end_date:
                if current.weekday() < 5:
                    date_str = current.isoformat()
                    if date_str not in holidays:
                        working_days += 1
                current += timedelta(days=1)

            return working_days
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed computing working days between %s and %s", start_date, end_date)
            raise LeaveRuleViolationException("Could not compute working days") from exc

    @classmethod
    def get_balance(cls, employee_id: str, leave_type: LeaveType) -> float:
        """Fetch current remaining balance for employee and leave type using SQLAlchemy ORM."""
        try:
            with get_db_session() as session:
                stmt = select(LeaveBalanceModel.balance_days).where(
                    LeaveBalanceModel.employee_id == employee_id,
                    LeaveBalanceModel.leave_type == leave_type.value,
                )
                val = session.scalar(stmt)
                return float(val) if val is not None else 0.0
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed retrieving balance for emp=%s type=%s", employee_id, leave_type.value)
            raise DatabaseException("Could not read leave balance") from exc

    @classmethod
    def validate_apply(
        cls,
        ctx: RequestContext,
        leave_type_str: str,
        start_date: date,
        end_date: date,
        today: Optional[date] = None,
    ) -> int:
        """Validate leave application rules and return calculated working days."""
        try:
            ref_today = today or REFERENCE_DATE

            leave_type = cls.normalize_leave_type(leave_type_str)

            if start_date.year != LEAVE_YEAR or end_date.year != LEAVE_YEAR:
                raise LeaveRuleViolationException(f"Leave requests must be within the calendar year {LEAVE_YEAR}")

            if start_date < ref_today:
                raise LeaveRuleViolationException(f"Start date cannot be in the past (today is {ref_today})")
            if end_date < start_date:
                raise LeaveRuleViolationException("End date cannot be earlier than start date")

            working_days = cls.compute_working_days(start_date, end_date, ctx.region, ref_today)
            if working_days <= 0:
                raise LeaveRuleViolationException("Selected date range contains zero working days (weekends or public holidays)")

            current_balance = cls.get_balance(ctx.employee_id, leave_type)
            if working_days > current_balance:
                raise LeaveRuleViolationException(
                    f"Insufficient {leave_type.value} leave balance: requested {working_days} working days, "
                    f"but current balance is {current_balance} days"
                )

            start_str = start_date.isoformat()
            end_str = end_date.isoformat()

            with get_db_session() as session:
                overlap_stmt = select(LeaveRequestModel).where(
                    LeaveRequestModel.employee_id == ctx.employee_id,
                    LeaveRequestModel.status.in_(["pending", "approved"]),
                    LeaveRequestModel.start_date <= end_str,
                    LeaveRequestModel.end_date >= start_str,
                )
                overlapping = session.scalar(overlap_stmt)
                if overlapping:
                    raise LeaveRuleViolationException(
                        f"Requested dates overlap with existing {overlapping.status} request "
                        f"({overlapping.start_date} to {overlapping.end_date})"
                    )

            return working_days
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed validating leave apply for emp=%s", ctx.employee_id)
            raise LeaveRuleViolationException("Leave application validation failed") from exc

    @classmethod
    def apply_leave_transaction(
        cls,
        ctx: RequestContext,
        leave_type_str: str,
        start_date: date,
        end_date: date,
        today: Optional[date] = None,
    ) -> LeaveRequestModel:
        """Execute leave application in a single immediate transaction using SQLAlchemy ORM."""
        try:
            ref_today = today or REFERENCE_DATE
            leave_type = cls.normalize_leave_type(leave_type_str)
            start_str = start_date.isoformat()
            end_str = end_date.isoformat()
            new_request_id = str(uuid.uuid4())
            created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

            with get_db_session() as session:
                working_days = cls.compute_working_days(start_date, end_date, ctx.region, ref_today)
                if working_days <= 0:
                    raise LeaveRuleViolationException("Selected date range contains zero working days")

                bal_stmt = select(LeaveBalanceModel).where(
                    LeaveBalanceModel.employee_id == ctx.employee_id,
                    LeaveBalanceModel.leave_type == leave_type.value,
                )
                bal_obj = session.scalar(bal_stmt)
                current_bal = float(bal_obj.balance_days) if bal_obj else 0.0

                if working_days > current_bal:
                    raise LeaveRuleViolationException("Insufficient leave balance")

                overlap_stmt = select(LeaveRequestModel.request_id).where(
                    LeaveRequestModel.employee_id == ctx.employee_id,
                    LeaveRequestModel.status.in_(["pending", "approved"]),
                    LeaveRequestModel.start_date <= end_str,
                    LeaveRequestModel.end_date >= start_str,
                )
                if session.scalar(overlap_stmt):
                    raise LeaveRuleViolationException("Requested dates overlap with existing leave request")

                new_req = LeaveRequestModel(
                    request_id=new_request_id,
                    employee_id=ctx.employee_id,
                    leave_type=leave_type.value,
                    start_date=start_str,
                    end_date=end_str,
                    working_days=working_days,
                    status=LeaveRequestStatus.PENDING.value,
                    created_at=created_at,
                )
                session.add(new_req)

                if bal_obj:
                    bal_obj.balance_days = bal_obj.balance_days - working_days

                session.commit()

            logger.info("Successfully applied leave for emp=%s req=%s days=%d", ctx.employee_id, new_request_id, working_days)
            return LeaveRequestModel(
                request_id=new_request_id,
                employee_id=ctx.employee_id,
                leave_type=leave_type.value,
                start_date=start_str,
                end_date=end_str,
                working_days=working_days,
                status=LeaveRequestStatus.PENDING.value,
                created_at=created_at,
            )
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed executing apply_leave transaction for emp=%s", ctx.employee_id)
            raise DatabaseException("Error recording leave request") from exc

    @classmethod
    def validate_cancel(cls, ctx: RequestContext, request_id: str, today: Optional[date] = None) -> LeaveRequestModel:
        """Validate cancellation rules for a given leave request ID using SQLAlchemy ORM."""
        try:
            ref_today = today or REFERENCE_DATE
            with get_db_session() as session:
                req = session.get(LeaveRequestModel, request_id)
                if not req:
                    raise LeaveRuleViolationException(f"Leave request '{request_id}' not found")

                if req.employee_id != ctx.employee_id:
                    raise LeaveRuleViolationException("You can only cancel your own leave requests")

                if req.status not in ("pending", "approved"):
                    raise LeaveRuleViolationException(f"Cannot cancel a request that is already '{req.status}'")

                start_date = date.fromisoformat(req.start_date)
                if start_date <= ref_today:
                    raise LeaveRuleViolationException(
                        f"Cannot cancel leave that has already started or begins today (start date: {start_date}, today: {ref_today})"
                    )

                session.expunge(req)
                return req
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed validating leave cancellation for req=%s", request_id)
            raise LeaveRuleViolationException("Cancellation validation failed") from exc

    @classmethod
    def cancel_leave_transaction(
        cls,
        ctx: RequestContext,
        request_id: str,
        today: Optional[date] = None,
    ) -> LeaveRequestModel:
        """Cancel leave request and refund working days in a single immediate transaction using SQLAlchemy ORM."""
        try:
            ref_today = today or REFERENCE_DATE

            with get_db_session() as session:
                req = session.get(LeaveRequestModel, request_id)
                if not req:
                    raise LeaveRuleViolationException(f"Leave request '{request_id}' not found")
                if req.employee_id != ctx.employee_id:
                    raise LeaveRuleViolationException("You can only cancel your own leave requests")
                if req.status not in ("pending", "approved"):
                    raise LeaveRuleViolationException(f"Cannot cancel a request with status '{req.status}'")

                start_date = date.fromisoformat(req.start_date)
                if start_date <= ref_today:
                    raise LeaveRuleViolationException("Cannot cancel leave that has already started or begins today")

                req.status = LeaveRequestStatus.CANCELLED.value
                restored_days = req.working_days

                bal_stmt = select(LeaveBalanceModel).where(
                    LeaveBalanceModel.employee_id == ctx.employee_id,
                    LeaveBalanceModel.leave_type == req.leave_type,
                )
                bal_obj = session.scalar(bal_stmt)
                if bal_obj:
                    bal_obj.balance_days = bal_obj.balance_days + restored_days

                session.commit()
                session.expunge(req)

            logger.info("Successfully cancelled leave req=%s for emp=%s restored=%d", request_id, ctx.employee_id, restored_days)
            return req
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed executing cancel_leave transaction for req=%s", request_id)
            raise DatabaseException("Error cancelling leave request") from exc


# Module-level singleton
_leave_service: Optional[LeaveService] = None


def get_leave_service() -> LeaveService:
    """Return singleton LeaveService instance."""
    global _leave_service
    if _leave_service is None:
        _leave_service = LeaveService()
    return _leave_service

# Aliases for helper usage
LeaveHelper = LeaveService
get_leave_helper = get_leave_service
