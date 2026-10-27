# 1. Python standard library
# (None)

# 2. Third-party installed packages
import pytest
from fastapi.testclient import TestClient

# 3. Code-level (our own) imports
from app.core.lifespan import set_service_ready
from main import app


def test_health_check_returns_200_when_ready():
    """Verify /health returns 200 OK when service is marked ready."""
    set_service_ready(True)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_health_check_returns_503_when_not_ready():
    """Verify /health returns 503 Service Unavailable when service is not ready."""
    with TestClient(app) as client:
        set_service_ready(False)
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "initializing"

