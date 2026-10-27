"""Session management service tracking conversation turns and pending proposals."""

import logging
import threading
from typing import Dict, List, Optional

from app.dto.session_dto import PendingProposal, SessionData
from app.exceptions.custom_exceptions import AppException, ForbiddenException, InternalServerException
from app.utils.constants import MAX_SESSION_HISTORY_TURNS

logger = logging.getLogger(__name__)


class SessionService:
    """Thread-safe in-memory session manager enforcing session ownership and proposal states."""

    _sessions: Dict[str, SessionData] = {}
    _lock = threading.Lock()

    @classmethod
    def get_or_create_session(cls, session_id: str, employee_id: str) -> SessionData:
        """Retrieve existing session or create a new one, validating employee ownership."""
        try:
            with cls._lock:
                if session_id in cls._sessions:
                    existing = cls._sessions[session_id]
                    if existing.owner_employee_id != employee_id:
                        logger.warning(
                            "Session ownership mismatch for %s: owner is %s, requester is %s",
                            session_id,
                            existing.owner_employee_id,
                            employee_id,
                        )
                        raise ForbiddenException("Session belongs to another employee")
                    return existing

                new_session = SessionData(
                    session_id=session_id,
                    owner_employee_id=employee_id,
                )
                cls._sessions[session_id] = new_session
                logger.info("Created new session %s for employee %s", session_id, employee_id)
                return new_session
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to access session %s for employee %s", session_id, employee_id)
            raise InternalServerException("Could not manage session") from exc

    @classmethod
    def get_pending_proposal(cls, session_id: str) -> Optional[PendingProposal]:
        """Return currently pending confirmation proposal for session if present."""
        try:
            with cls._lock:
                session = cls._sessions.get(session_id)
                return session.pending_proposal if session else None
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to read pending proposal for session %s", session_id)
            raise InternalServerException("Could not retrieve proposal state") from exc

    @classmethod
    def set_pending_proposal(cls, session_id: str, proposal: Optional[PendingProposal]) -> None:
        """Set or update pending confirmation proposal for a session."""
        try:
            with cls._lock:
                session = cls._sessions.get(session_id)
                if session:
                    session.pending_proposal = proposal
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to set pending proposal for session %s", session_id)
            raise InternalServerException("Could not update proposal state") from exc

    @classmethod
    def clear_pending_proposal(cls, session_id: str) -> None:
        """Clear any pending proposal from session."""
        try:
            cls.set_pending_proposal(session_id, None)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to clear pending proposal for session %s", session_id)
            raise InternalServerException("Could not clear proposal state") from exc

    @classmethod
    def add_turn(cls, session_id: str, user_message: str, assistant_message: str) -> None:
        """Append user and assistant messages to session history while respecting turn limit."""
        try:
            with cls._lock:
                session = cls._sessions.get(session_id)
                if session:
                    session.history.append({"role": "user", "content": user_message})
                    session.history.append({"role": "assistant", "content": assistant_message})
                    if len(session.history) > MAX_SESSION_HISTORY_TURNS * 2:
                        session.history = session.history[-(MAX_SESSION_HISTORY_TURNS * 2):]
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to record conversation turn for session %s", session_id)
            raise InternalServerException("Could not record conversation turn") from exc

    @classmethod
    def get_history(cls, session_id: str) -> List[Dict[str, str]]:
        """Return conversation history list for session."""
        try:
            with cls._lock:
                session = cls._sessions.get(session_id)
                return list(session.history) if session else []
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to fetch history for session %s", session_id)
            raise InternalServerException("Could not fetch conversation history") from exc

    @classmethod
    def clear_all(cls) -> None:
        """Reset all in-memory sessions (used for test teardown)."""
        try:
            with cls._lock:
                cls._sessions.clear()
        except Exception as exc:
            logger.exception("Failed to clear session store")
            raise InternalServerException("Could not clear session store") from exc


# Module-level singleton
_session_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """Return singleton SessionService instance."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service

# Aliases for helper usage
SessionHelper = SessionService
get_session_helper = get_session_service
