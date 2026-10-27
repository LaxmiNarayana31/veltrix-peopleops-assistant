from enum import Enum


class ChatRoute(str, Enum):
    """Allowed chat response routes."""

    RAG = "rag"
    TOOL = "tool"
    HYBRID = "hybrid"
    CLARIFY = "clarify"
    NO_ANSWER = "no_answer"
    REFUSE = "refuse"


class ToolStatus(str, Enum):
    """Allowed tool call statuses."""

    PENDING_CONFIRMATION = "pending_confirmation"
    SUCCESS = "success"
    ERROR = "error"


class UserRole(str, Enum):
    """Employee role levels in Veltrix."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR = "hr"


class LeaveType(str, Enum):
    """Valid leave categories."""

    ANNUAL = "annual"
    SICK = "sick"


class LeaveRequestStatus(str, Enum):
    """Status of leave requests."""

    PENDING = "pending"
    APPROVED = "approved"
    CANCELLED = "cancelled"


# Standardized fixed messages
CROSS_EMPLOYEE_REFUSAL_MESSAGE = "I can't share information about that employee."
BULK_REQUEST_REFUSAL_MESSAGE = "I cannot provide bulk employee data."
OFF_TOPIC_REFUSAL_MESSAGE = (
    "I am the Veltrix PeopleOps Assistant. I can only assist with Veltrix HR policies and leave operations."
)
INJECTION_REFUSAL_MESSAGE = "I cannot fulfill this request as it violates operational security guidelines."
NO_ANSWER_FALLBACK_MESSAGE = (
    "The available HR policy documents do not cover this topic. Please contact the HR department for further assistance."
)

# Limits and token budgets
MAX_CORPUS_TOKENS_BUDGET = 3000
TARGET_CORPUS_PACKING_BUDGET = 2700
LEAVE_YEAR = 2026

# Calendar month name to integer mapping (full and 3-letter abbreviations)
MONTH_MAP: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

MAX_SESSION_HISTORY_TURNS = 20
DEFAULT_CHUNK_SIZE_TOKENS = 350
DEFAULT_CHUNK_OVERLAP_TOKENS = 40
