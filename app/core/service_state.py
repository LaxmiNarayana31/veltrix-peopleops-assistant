import logging


logger = logging.getLogger(__name__)


class ServiceState:
    """Tracks application initialization and readiness state."""

    is_ready: bool = False


# Centralized application readiness state singleton
service_state = ServiceState()


def is_service_ready() -> bool:
    """Return whether backend service and corpus ingestion are ready."""
    return service_state.is_ready


def set_service_ready(ready: bool) -> None:
    """Update backend readiness status."""
    service_state.is_ready = ready
    logger.info("Service readiness state updated to: %s", ready)

