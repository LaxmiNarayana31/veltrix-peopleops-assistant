from typing import List, Optional

from pydantic import BaseModel, Field

from app.utils.constants import ChatRoute


class PlanExtractionDTO(BaseModel):
    """Structured output from LLM plan call (0 corpus tokens)."""
    intent: str = Field(default="policy_question", description="Detected intent: policy_question, leave_balance, leave_history, team_leave, apply_leave, cancel_leave, off_topic, manipulation")
    route_hint: Optional[str] = Field(default=None, description="Hinted route for orchestrator pipeline")
    leave_type: Optional[str] = None
    start_date_phrase: Optional[str] = None
    end_date_phrase: Optional[str] = None
    target_employee_id: Optional[str] = None
    reference_date_str: Optional[str] = None
    question_topic: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list, description="Fields required to proceed that are missing or ambiguous")

class RuleExtractionDTO(BaseModel):
    """Extracted policy value and citation from an individual document chunk."""
    doc_id: str
    locator: str
    value: str
    normalized_value: Optional[str] = None

class AnswerExtractionDTO(BaseModel):
    """Structured response from LLM answer generation turn."""
    answer: str
    used_doc_ids: List[str] = Field(default_factory=list)
