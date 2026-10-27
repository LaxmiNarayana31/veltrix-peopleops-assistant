# 1. Python standard library
# (None)

# 2. Third-party installed packages
import pytest
from fastapi.testclient import TestClient

# 3. Code-level (our own) imports
from app.core.lifespan import set_service_ready
from app.helper.session.session_helper import SessionService
from main import app


@pytest.fixture(autouse=True)
def setup_test_env():
    """Reset service ready flag and session store before each test."""
    set_service_ready(True)
    SessionService.clear_all()


def test_chat_missing_auth_header_returns_401():
    """Verify missing X-Employee-Id returns 401 Unauthorized."""
    with TestClient(app) as client:
        response = client.post("/chat", json={"session_id": "s1", "message": "hello"})
        assert response.status_code == 401
        assert response.json()["error_code"] == "UNAUTHORIZED"


def test_chat_invalid_employee_id_returns_401():
    """Verify non-existent employee ID returns 401 Unauthorized."""
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"X-Employee-Id": "NON_EXISTENT_EMP"},
            json={"session_id": "s1", "message": "hello"},
        )
        assert response.status_code == 401
        assert response.json()["error_code"] == "UNAUTHORIZED"


def test_chat_invalid_payload_returns_400():
    """Verify malformed or missing body returns 400 Bad Request."""
    with TestClient(app) as client:
        # Missing message
        response = client.post(
            "/chat",
            headers={"X-Employee-Id": "E1001"},
            json={"session_id": "s1"},
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "BAD_REQUEST"

        # Empty session_id
        response_empty = client.post(
            "/chat",
            headers={"X-Employee-Id": "E1001"},
            json={"session_id": "", "message": "hello"},
        )
        assert response_empty.status_code == 400


def test_session_ownership_conflict_returns_403():
    """Verify access to session owned by another employee returns 403 Forbidden."""
    with TestClient(app) as client:
        # First call by E1001 establishes ownership of s1
        res1 = client.post(
            "/chat",
            headers={"X-Employee-Id": "E1001"},
            json={"session_id": "s1", "message": "Hello from Meera"},
        )
        assert res1.status_code == 200

        # Second call with same session_id by E1002 (different employee)
        res2 = client.post(
            "/chat",
            headers={"X-Employee-Id": "E1002"},
            json={"session_id": "s1", "message": "Hello from Rohan"},
        )
        assert res2.status_code == 403
        assert res2.json()["error_code"] == "FORBIDDEN"


def test_valid_chat_call_returns_contract_compliant_response():
    """Verify successful /chat call produces all required contract fields."""
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"X-Employee-Id": "E1001"},
            json={"session_id": "s_valid", "message": "ping"},
        )
        assert response.status_code == 200
        data = response.json()

        # Contract keys check
        assert "request_id" in data
        assert "answer" in data
        assert "route" in data
        assert "citations" in data
        assert "tool_calls" in data
        assert "pending_confirmation" in data

        assert isinstance(data["citations"], list)
        assert isinstance(data["tool_calls"], list)
        assert isinstance(data["pending_confirmation"], bool)
