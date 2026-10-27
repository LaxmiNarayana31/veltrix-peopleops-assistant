import logging
from datetime import date
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.dto.chat_dto import RequestContext
from app.dto.leave_dto import ToolResult
from app.exceptions.custom_exceptions import AppException, LeaveRuleViolationException
from app.models.leave_model import LeaveBalanceModel, LeaveRequestModel
from app.helper.access.access_helper import AccessService
from app.helper.leave.leave_helper import LeaveService
from app.utils.constants import (
    CROSS_EMPLOYEE_REFUSAL_MESSAGE,
    ToolStatus,
    UserRole,
)
from config.database import get_db_session

logger = logging.getLogger(__name__)


# LangChain Structured Tool Definitions
@tool
def get_leave_balance_tool(employee_id: str, leave_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve leave balance records for an employee."""
    with get_db_session() as session:
        stmt = select(LeaveBalanceModel.leave_type, LeaveBalanceModel.balance_days).where(
            LeaveBalanceModel.employee_id == employee_id
        )
        if leave_type:
            lt = leave_type.lower().strip()
            if any(k in lt for k in ("annual", "vacation", "earned", "casual", "pto")):
                normalized_type = "annual"
            elif any(k in lt for k in ("sick", "medical")):
                normalized_type = "sick"
            else:
                normalized_type = lt
            target_stmt = stmt.where(LeaveBalanceModel.leave_type == normalized_type)
            rows = session.execute(target_stmt).all()
            if not rows:
                rows = session.execute(stmt.order_by(LeaveBalanceModel.leave_type)).all()
        else:
            rows = session.execute(stmt.order_by(LeaveBalanceModel.leave_type)).all()

        return [
            {
                "leave_type": r.leave_type.value if hasattr(r.leave_type, "value") else str(r.leave_type),
                "balance_days": float(r.balance_days),
            }
            for r in rows
        ]


@tool
def list_leave_requests_tool(employee_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List historical or active leave requests for an employee."""
    with get_db_session() as session:
        stmt = select(LeaveRequestModel).where(LeaveRequestModel.employee_id == employee_id)
        if status:
            stmt = stmt.where(LeaveRequestModel.status == status.lower().strip())
        stmt = stmt.order_by(LeaveRequestModel.start_date.desc())

        rows = session.scalars(stmt).all()
        return [
            {
                "request_id": r.request_id,
                "employee_id": r.employee_id,
                "leave_type": r.leave_type.value if hasattr(r.leave_type, "value") else str(r.leave_type),
                "start_date": str(r.start_date),
                "end_date": str(r.end_date),
                "working_days": r.working_days,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "created_at": str(r.created_at),
            }
            for r in rows
        ]


@tool
def get_team_leave_tool(start_date: str, end_date: str, report_ids: List[str], emp_name_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetch leave requests of direct reports overlapping a date range."""
    if not report_ids:
        return []

    with get_db_session() as session:
        stmt = (
            select(LeaveRequestModel)
            .where(
                LeaveRequestModel.employee_id.in_(report_ids),
                LeaveRequestModel.status.in_(["pending", "approved"]),
                LeaveRequestModel.start_date <= end_date,
                LeaveRequestModel.end_date >= start_date,
            )
            .order_by(LeaveRequestModel.start_date.asc())
        )
        rows = session.scalars(stmt).all()
        return [
            {
                "request_id": r.request_id,
                "employee_id": r.employee_id,
                "full_name": emp_name_map.get(r.employee_id, "Unknown"),
                "leave_type": r.leave_type.value if hasattr(r.leave_type, "value") else str(r.leave_type),
                "start_date": str(r.start_date),
                "end_date": str(r.end_date),
                "working_days": r.working_days,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            }
            for r in rows
        ]


class ToolGraphState(TypedDict, total=False):
    """LangGraph execution state for tool invocation."""
    tool_name: str
    args: Dict[str, Any]
    ctx: RequestContext
    today: Optional[date]
    execute: bool
    is_authorized: bool
    status: ToolStatus
    error_message: Optional[str]
    data: Optional[Any]
    tool_result: Optional[ToolResult]


def authorize_node(state: ToolGraphState) -> Dict[str, Any]:
    """Validate caller authorization and role-based permissions in LangGraph."""
    tool_name = state["tool_name"]
    ctx = state["ctx"]
    args = state["args"]

    if tool_name in ("get_leave_balance", "list_leave_requests"):
        target_employee = args.get("employee_id", ctx.employee_id)
        if not AccessService.can_view_employee(ctx, target_employee):
            logger.warning("Permission denied: %s cannot access records of %s", ctx.employee_id, target_employee)
            return {
                "is_authorized": False,
                "status": ToolStatus.ERROR,
                "error_message": CROSS_EMPLOYEE_REFUSAL_MESSAGE,
            }

    if tool_name == "get_team_leave":
        if ctx.role != UserRole.MANAGER:
            logger.warning("Unauthorized get_team_leave attempt by non-manager %s", ctx.employee_id)
            return {
                "is_authorized": False,
                "status": ToolStatus.ERROR,
                "error_message": "Only managers can view team leave.",
            }

    return {"is_authorized": True}


def route_tool_execution(state: ToolGraphState) -> str:
    """Conditional router directing graph execution based on authorization and tool name."""
    if not state.get("is_authorized", False):
        return "unauthorized_node"

    tool_name = state.get("tool_name")
    if tool_name == "get_leave_balance":
        return "balance_node"
    elif tool_name == "list_leave_requests":
        return "requests_node"
    elif tool_name == "get_team_leave":
        return "team_leave_node"
    elif tool_name == "apply_leave":
        return "apply_leave_node"
    elif tool_name == "cancel_leave":
        return "cancel_leave_node"
    return "unauthorized_node"


def unauthorized_node(state: ToolGraphState) -> Dict[str, Any]:
    """Handle unauthorized requests."""
    return {
        "status": state.get("status", ToolStatus.ERROR),
        "error_message": state.get("error_message", "Permission denied"),
    }


def balance_node(state: ToolGraphState) -> Dict[str, Any]:
    """Execute get_leave_balance tool within LangGraph."""
    args = state["args"]
    try:
        data = get_leave_balance_tool.invoke({
            "employee_id": args["employee_id"],
            "leave_type": args.get("leave_type"),
        })
        return {"status": ToolStatus.SUCCESS, "data": data}
    except Exception as exc:
        logger.exception("Error executing get_leave_balance in LangGraph")
        return {"status": ToolStatus.ERROR, "error_message": "Could not retrieve leave balance"}


def requests_node(state: ToolGraphState) -> Dict[str, Any]:
    """Execute list_leave_requests tool within LangGraph."""
    args = state["args"]
    try:
        data = list_leave_requests_tool.invoke({
            "employee_id": args["employee_id"],
            "status": args.get("status"),
        })
        return {"status": ToolStatus.SUCCESS, "data": data}
    except Exception as exc:
        logger.exception("Error executing list_leave_requests in LangGraph")
        return {"status": ToolStatus.ERROR, "error_message": "Could not list leave requests"}


def team_leave_node(state: ToolGraphState) -> Dict[str, Any]:
    """Execute get_team_leave tool within LangGraph."""
    args = state["args"]
    ctx = state["ctx"]
    try:
        direct_reports = AccessService.get_direct_reports(ctx.employee_id)
        if not direct_reports:
            return {"status": ToolStatus.SUCCESS, "data": []}

        report_ids = [emp.employee_id for emp in direct_reports]
        emp_name_map = {emp.employee_id: emp.full_name for emp in direct_reports}

        data = get_team_leave_tool.invoke({
            "start_date": args["start_date"],
            "end_date": args["end_date"],
            "report_ids": report_ids,
            "emp_name_map": emp_name_map,
        })
        return {"status": ToolStatus.SUCCESS, "data": data}
    except Exception as exc:
        logger.exception("Error executing get_team_leave in LangGraph")
        return {"status": ToolStatus.ERROR, "error_message": "Could not retrieve team leave"}


def apply_leave_node(state: ToolGraphState) -> Dict[str, Any]:
    """Execute or propose apply_leave within LangGraph."""
    args = state["args"]
    ctx = state["ctx"]
    execute = state.get("execute", False)
    today = state.get("today")

    try:
        parsed_start = date.fromisoformat(args["start_date"])
        parsed_end = date.fromisoformat(args["end_date"])
    except ValueError:
        return {
            "status": ToolStatus.ERROR,
            "error_message": "Invalid date format. Dates must follow YYYY-MM-DD.",
        }

    try:
        if not execute:
            working_days = LeaveService.validate_apply(ctx, args["leave_type"], parsed_start, parsed_end, today=today)
            summary_text = (
                f"Apply for {working_days} working day(s) of {args['leave_type'].lower()} leave "
                f"from {args['start_date']} to {args['end_date']}."
            )
            return {
                "status": ToolStatus.PENDING_CONFIRMATION,
                "data": {"working_days": working_days, "summary": summary_text},
            }
        else:
            req_model = LeaveService.apply_leave_transaction(ctx, args["leave_type"], parsed_start, parsed_end, today=today)
            return {
                "status": ToolStatus.SUCCESS,
                "data": {
                    "request_id": req_model.request_id,
                    "employee_id": req_model.employee_id,
                    "leave_type": req_model.leave_type.value if hasattr(req_model.leave_type, "value") else str(req_model.leave_type),
                    "start_date": str(req_model.start_date),
                    "end_date": str(req_model.end_date),
                    "working_days": int(req_model.working_days),
                    "status": req_model.status.value if hasattr(req_model.status, "value") else str(req_model.status),
                    "created_at": str(req_model.created_at),
                },
            }
    except LeaveRuleViolationException as exc:
        return {"status": ToolStatus.ERROR, "error_message": exc.message}
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Error in apply_leave within LangGraph")
        return {"status": ToolStatus.ERROR, "error_message": "An unexpected error occurred while applying for leave"}


def cancel_leave_node(state: ToolGraphState) -> Dict[str, Any]:
    """Execute or propose cancel_leave within LangGraph."""
    args = state["args"]
    ctx = state["ctx"]
    execute = state.get("execute", False)
    today = state.get("today")

    try:
        if not execute:
            req_model = LeaveService.validate_cancel(ctx, args["request_id"], today=today)
            leave_type_str = req_model.leave_type.value if hasattr(req_model.leave_type, "value") else str(req_model.leave_type)
            summary_text = (
                f"Cancel {leave_type_str} leave request {args['request_id']} "
                f"({req_model.start_date} to {req_model.end_date}, {req_model.working_days} days)."
            )
            return {
                "status": ToolStatus.PENDING_CONFIRMATION,
                "data": {"request_id": args["request_id"], "summary": summary_text},
            }
        else:
            req_model = LeaveService.cancel_leave_transaction(ctx, args["request_id"], today=today)
            return {
                "status": ToolStatus.SUCCESS,
                "data": {
                    "request_id": req_model.request_id,
                    "employee_id": req_model.employee_id,
                    "leave_type": req_model.leave_type.value if hasattr(req_model.leave_type, "value") else str(req_model.leave_type),
                    "start_date": str(req_model.start_date),
                    "end_date": str(req_model.end_date),
                    "working_days": int(req_model.working_days),
                    "status": req_model.status.value if hasattr(req_model.status, "value") else str(req_model.status),
                    "created_at": str(req_model.created_at),
                },
            }
    except LeaveRuleViolationException as exc:
        return {"status": ToolStatus.ERROR, "error_message": exc.message}
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Error in cancel_leave within LangGraph")
        return {"status": ToolStatus.ERROR, "error_message": "An unexpected error occurred while cancelling leave"}


def finalize_node(state: ToolGraphState) -> Dict[str, Any]:
    """Construct final normalized ToolResult from LangGraph execution state."""
    tool_result = ToolResult(
        tool_name=state["tool_name"],
        args=state["args"],
        status=state.get("status", ToolStatus.ERROR),
        data=state.get("data"),
        error_message=state.get("error_message"),
    )
    return {"tool_result": tool_result}


def _build_tool_graph():
    """Compile LangGraph StateGraph workflow for deterministic tool execution."""
    workflow = StateGraph(ToolGraphState)

    workflow.add_node("authorize_node", authorize_node)
    workflow.add_node("unauthorized_node", unauthorized_node)
    workflow.add_node("balance_node", balance_node)
    workflow.add_node("requests_node", requests_node)
    workflow.add_node("team_leave_node", team_leave_node)
    workflow.add_node("apply_leave_node", apply_leave_node)
    workflow.add_node("cancel_leave_node", cancel_leave_node)
    workflow.add_node("finalize_node", finalize_node)

    workflow.add_edge(START, "authorize_node")
    workflow.add_conditional_edges(
        "authorize_node",
        route_tool_execution,
        {
            "unauthorized_node": "unauthorized_node",
            "balance_node": "balance_node",
            "requests_node": "requests_node",
            "team_leave_node": "team_leave_node",
            "apply_leave_node": "apply_leave_node",
            "cancel_leave_node": "cancel_leave_node",
        },
    )

    workflow.add_edge("unauthorized_node", "finalize_node")
    workflow.add_edge("balance_node", "finalize_node")
    workflow.add_edge("requests_node", "finalize_node")
    workflow.add_edge("team_leave_node", "finalize_node")
    workflow.add_edge("apply_leave_node", "finalize_node")
    workflow.add_edge("cancel_leave_node", "finalize_node")
    workflow.add_edge("finalize_node", END)

    return workflow.compile()


# Compiled Singleton Graph
tool_graph_executor = _build_tool_graph()


def run_tool_graph(
    tool_name: str,
    args: Dict[str, Any],
    ctx: RequestContext,
    today: Optional[date] = None,
    execute: bool = False,
) -> ToolResult:
    """Execute a tool through the compiled LangGraph workflow graph."""
    initial_state: ToolGraphState = {
        "tool_name": tool_name,
        "args": args,
        "ctx": ctx,
        "today": today,
        "execute": execute,
    }
    result_state = tool_graph_executor.invoke(initial_state)
    return result_state["tool_result"]

