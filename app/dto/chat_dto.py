from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.utils.constants import ChatRoute, ToolStatus, UserRole


class RequestContext(BaseModel):
    """Context extracted from authentication header and database lookup."""
    employee_id: str
    role: UserRole
    region: str
    full_name: str
    email: str

class CitationDTO(BaseModel):
    """Citation referencing a specific document section or page."""
    doc_id: str
    locator: str

class ToolCallDTO(BaseModel):
    """Executed or planned tool invocation details."""
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus

class ChatRequest(BaseModel):
    """Incoming request payload for POST /chat."""
    session_id: str = Field(min_length=1, description="Unique identifier for the user session")
    message: str = Field(min_length=1, description="User prompt message")

class ChatResponse(BaseModel):
    """Response payload for POST /chat complying with the exact API contract."""
    request_id: str
    answer: str
    route: ChatRoute
    citations: List[CitationDTO] = Field(default_factory=list)
    tool_calls: List[ToolCallDTO] = Field(default_factory=list)
    pending_confirmation: bool = False
