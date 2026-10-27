"""Tool service providing execution of the 5 PeopleOps tools via LangGraph."""

from datetime import date
import logging
from typing import Any, Dict, Optional

from app.dto.chat_dto import RequestContext
from app.dto.leave_dto import ToolResult
from app.helper.leave.tool_graph import run_tool_graph

logger = logging.getLogger(__name__)


class ToolService:
    """Provides execution and permission enforcement for the 5 PeopleOps tools via LangGraph."""

    @classmethod
    def get_leave_balance(
        cls,
        ctx: RequestContext,
        employee_id: str,
        leave_type: Optional[str] = None,
    ) -> ToolResult:
        """Fetch leave balances for an employee subject to role-based visibility via LangGraph."""
        raw_args: Dict[str, Any] = {"employee_id": employee_id}
        if leave_type:
            raw_args["leave_type"] = leave_type
        return run_tool_graph(
            tool_name="get_leave_balance",
            args=raw_args,
            ctx=ctx,
        )

    @classmethod
    def list_leave_requests(
        cls,
        ctx: RequestContext,
        employee_id: str,
        status: Optional[str] = None,
    ) -> ToolResult:
        """List historical or active leave requests for an employee via LangGraph."""
        raw_args: Dict[str, Any] = {"employee_id": employee_id}
        if status:
            raw_args["status"] = status
        return run_tool_graph(
            tool_name="list_leave_requests",
            args=raw_args,
            ctx=ctx,
        )

    @classmethod
    def get_team_leave(
        cls,
        ctx: RequestContext,
        start_date: str,
        end_date: str,
    ) -> ToolResult:
        """Fetch leave requests of direct reports overlapping a date range via LangGraph."""
        raw_args: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
        return run_tool_graph(
            tool_name="get_team_leave",
            args=raw_args,
            ctx=ctx,
        )

    @classmethod
    def apply_leave(
        cls,
        ctx: RequestContext,
        leave_type: str,
        start_date: str,
        end_date: str,
        execute: bool = False,
        today: Optional[date] = None,
    ) -> ToolResult:
        """Propose or execute a leave application for the calling employee via LangGraph."""
        raw_args: Dict[str, Any] = {
            "leave_type": leave_type,
            "start_date": start_date,
            "end_date": end_date,
        }
        return run_tool_graph(
            tool_name="apply_leave",
            args=raw_args,
            ctx=ctx,
            today=today,
            execute=execute,
        )

    @classmethod
    def cancel_leave(
        cls,
        ctx: RequestContext,
        request_id: str,
        execute: bool = False,
        today: Optional[date] = None,
    ) -> ToolResult:
        """Propose or execute cancellation of an existing leave request via LangGraph."""
        raw_args: Dict[str, Any] = {"request_id": request_id}
        return run_tool_graph(
            tool_name="cancel_leave",
            args=raw_args,
            ctx=ctx,
            today=today,
            execute=execute,
        )


# Module-level singleton
_tool_service: Optional[ToolService] = None


def get_tool_service() -> ToolService:
    """Return singleton ToolService instance."""
    global _tool_service
    if _tool_service is None:
        _tool_service = ToolService()
    return _tool_service


# Aliases for helper usage
ToolHelper = ToolService
get_tool_helper = get_tool_service
