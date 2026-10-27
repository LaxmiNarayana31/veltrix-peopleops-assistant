"""DTO models for session management and pending tool proposals."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PendingProposal(BaseModel):
    """Details of a pending leave write operation awaiting confirmation."""

    tool_name: str
    args: Dict[str, Any]
    summary: str
    working_days: Optional[int] = None


class SessionData(BaseModel):
    """In-memory state preserved for an active user session."""

    session_id: str
    owner_employee_id: str
    history: List[Dict[str, str]] = Field(default_factory=list)
    pending_proposal: Optional[PendingProposal] = None
