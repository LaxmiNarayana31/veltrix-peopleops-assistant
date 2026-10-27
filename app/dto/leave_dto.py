from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.utils.constants import LeaveRequestStatus, LeaveType, ToolStatus


class ToolResult(BaseModel):
    """Normalized response from tool execution."""
    tool_name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus
    data: Optional[Any] = None
    error_message: Optional[str] = None

class LeaveBalanceDTO(BaseModel):
    """Leave balance information for an employee."""
    leave_type: LeaveType
    balance_days: float

class LeaveRequestDTO(BaseModel):
    """Details of a single leave request."""
    request_id: str
    employee_id: str
    leave_type: LeaveType
    start_date: str
    end_date: str
    working_days: int
    status: LeaveRequestStatus
    created_at: str

class TeamLeaveItemDTO(BaseModel):
    """Leave summary item for team members."""
    employee_id: str
    full_name: str
    leave_type: str
    start_date: str
    end_date: str
    working_days: int
    status: str
