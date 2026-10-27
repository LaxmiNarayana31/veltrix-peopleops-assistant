# 1. Python standard library
import sqlite3
from datetime import date
from typing import Generator

# 2. Third-party installed packages
import pytest

# 3. Code-level (our own) imports
from app.dto.chat_dto import RequestContext
from app.exceptions.custom_exceptions import LeaveRuleViolationException
from app.helper.access.access_helper import AccessService
from app.helper.leave.leave_helper import LeaveService
from app.helper.leave.tool_helper import ToolService
from app.models.employee_model import EmployeeModel
from app.utils.constants import (
    CROSS_EMPLOYEE_REFUSAL_MESSAGE,
    LeaveType,
    ToolStatus,
    UserRole,
)
from config.database import get_db_connection, get_db_manager


@pytest.fixture(autouse=True)
def init_test_db() -> Generator[None, None, None]:
    """Ensure extra tables are initialized and cleanup leave state before and after tests."""
    get_db_manager().init_extra_tables()
    conn = get_db_manager().get_connection()
    try:
        conn.execute("DELETE FROM leave_requests WHERE employee_id IN ('E1001', 'E1002')")
        conn.execute("UPDATE leave_balances SET balance_days = 20.0 WHERE employee_id = 'E1002' AND leave_type = 'annual'")
        conn.commit()
    finally:
        conn.close()

    yield

    conn = get_db_manager().get_connection()
    try:
        conn.execute("DELETE FROM leave_requests WHERE employee_id IN ('E1001', 'E1002')")
        conn.execute("UPDATE leave_balances SET balance_days = 20.0 WHERE employee_id = 'E1002' AND leave_type = 'annual'")
        conn.commit()
    finally:
        conn.close()


def test_working_days_excludes_weekends_and_holidays():
    """Verify working days calculation accurately skips Saturday, Sunday and regional public holidays."""
    # Week of 2026-04-27 (Monday) to 2026-05-03 (Sunday)
    # Friday 2026-05-01 is May Day holiday in India (CAL-HOL-IN-2026), but not in US
    start = date(2026, 4, 27)
    end = date(2026, 5, 3)

    # For region IN: 5 weekdays - 1 holiday (May Day) = 4 working days
    days_in = LeaveService.compute_working_days(start, end, "IN", reference_date=date(2026, 1, 1))
    assert days_in == 4

    # For region US: 5 weekdays, no May Day holiday = 5 working days
    days_us = LeaveService.compute_working_days(start, end, "US", reference_date=date(2026, 1, 1))
    assert days_us == 5

    # Weekend only: 2026-05-02 (Sat) to 2026-05-03 (Sun) = 0 working days
    days_weekend = LeaveService.compute_working_days(date(2026, 5, 2), date(2026, 5, 3), "IN")
    assert days_weekend == 0


def test_apply_leave_validation_rejections():
    """Verify all business rule rejections for apply_leave."""
    ctx = RequestContext(
        employee_id="E1001",
        role=UserRole.HR,
        region="IN",
        full_name="Meera Krishnan",
        email="m***@veltrix.example",
    )
    today = date(2026, 5, 1)

    # 1. Invalid leave type
    with pytest.raises(LeaveRuleViolationException, match="Leave type must be either 'annual' or 'sick'"):
        LeaveService.validate_apply(ctx, "paternity", date(2026, 6, 1), date(2026, 6, 2), today)

    # 2. Year not 2026
    with pytest.raises(LeaveRuleViolationException, match="must be within the calendar year 2026"):
        LeaveService.validate_apply(ctx, "annual", date(2027, 1, 4), date(2027, 1, 5), today)

    # 3. Start date in past
    with pytest.raises(LeaveRuleViolationException, match="cannot be in the past"):
        LeaveService.validate_apply(ctx, "annual", date(2026, 4, 1), date(2026, 4, 5), today)

    # 4. End date before start date
    with pytest.raises(LeaveRuleViolationException, match="earlier than start date"):
        LeaveService.validate_apply(ctx, "annual", date(2026, 6, 10), date(2026, 6, 5), today)

    # 5. Weekend only range (0 working days)
    with pytest.raises(LeaveRuleViolationException, match="zero working days"):
        LeaveService.validate_apply(ctx, "annual", date(2026, 6, 6), date(2026, 6, 7), today)


def test_apply_leave_transaction_and_cancel_lifecycle():
    """Verify apply_leave transaction deducts balance and cancel_leave restores it atomically."""
    ctx = RequestContext(
        employee_id="E1002",
        role=UserRole.HR,
        region="IN",
        full_name="Rohan Bhat",
        email="r***@veltrix.example",
    )
    today = date(2026, 6, 1)

    # Check initial balance
    initial_balance = LeaveService.get_balance(ctx.employee_id, LeaveType.ANNUAL)
    assert initial_balance > 0

    # Step 1: Propose apply (should not alter database)
    prop_res = ToolService.apply_leave(ctx, "annual", "2026-07-06", "2026-07-08", execute=False, today=today)
    assert prop_res.status == ToolStatus.PENDING_CONFIRMATION
    assert prop_res.data["working_days"] == 3
    # Balance should be unchanged
    assert LeaveService.get_balance(ctx.employee_id, LeaveType.ANNUAL) == initial_balance

    # Step 2: Execute apply
    exec_res = ToolService.apply_leave(ctx, "annual", "2026-07-06", "2026-07-08", execute=True, today=today)
    assert exec_res.status == ToolStatus.SUCCESS
    req_id = exec_res.data["request_id"]
    new_balance = LeaveService.get_balance(ctx.employee_id, LeaveType.ANNUAL)
    assert new_balance == initial_balance - 3

    # Step 3: Overlapping apply must be rejected
    overlap_res = ToolService.apply_leave(ctx, "annual", "2026-07-07", "2026-07-10", execute=False, today=today)
    assert overlap_res.status == ToolStatus.ERROR
    assert "overlap" in overlap_res.error_message.lower()

    # Step 4: Propose cancel
    cancel_prop = ToolService.cancel_leave(ctx, req_id, execute=False, today=today)
    assert cancel_prop.status == ToolStatus.PENDING_CONFIRMATION
    assert cancel_prop.data["request_id"] == req_id

    # Step 5: Execute cancel
    cancel_exec = ToolService.cancel_leave(ctx, req_id, execute=True, today=today)
    assert cancel_exec.status == ToolStatus.SUCCESS
    assert cancel_exec.data["status"] == "cancelled"

    # Balance must be restored to initial
    restored_balance = LeaveService.get_balance(ctx.employee_id, LeaveType.ANNUAL)
    assert restored_balance == initial_balance


def test_tool_access_control_permissions():
    """Verify tool access control rules: employee (own), manager (reports), HR (any one)."""
    emp_ctx = RequestContext(
        employee_id="E1002",
        role=UserRole.EMPLOYEE,
        region="IN",
        full_name="Standard Employee",
        email="s***@veltrix.example",
    )

    # 1. Employee viewing own balance -> allowed
    res_own = ToolService.get_leave_balance(emp_ctx, employee_id="E1002")
    assert res_own.status == ToolStatus.SUCCESS

    # 2. Employee viewing another existing employee -> fixed refusal
    res_other = ToolService.get_leave_balance(emp_ctx, employee_id="E1001")
    assert res_other.status == ToolStatus.ERROR
    assert res_other.error_message == CROSS_EMPLOYEE_REFUSAL_MESSAGE

    # 3. Employee viewing non-existent employee -> EXACT SAME fixed refusal
    res_nonexistent = ToolService.get_leave_balance(emp_ctx, employee_id="DOES_NOT_EXIST")
    assert res_nonexistent.status == ToolStatus.ERROR
    assert res_nonexistent.error_message == CROSS_EMPLOYEE_REFUSAL_MESSAGE

    # 4. Non-manager calling get_team_leave -> error
    res_team = ToolService.get_team_leave(emp_ctx, "2026-06-01", "2026-06-30")
    assert res_team.status == ToolStatus.ERROR
    assert "Only managers" in res_team.error_message
