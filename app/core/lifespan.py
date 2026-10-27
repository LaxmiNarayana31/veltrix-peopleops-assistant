import asyncio
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator

from fastapi import FastAPI

from app.models.employee_model import EmployeeModel
from app.models.holiday_model import HolidayModel
from app.models.ingestion_meta_model import IngestionMetaModel
from app.models.leave_model import LeaveBalanceModel, LeaveRequestModel
from app.core.service_state import is_service_ready, service_state, set_service_ready
from app.helper.ingestion.ingestion_helper import IngestionService
from config.database import get_db_manager

logger = logging.getLogger(__name__)

_ingestion_task: asyncio.Task | None = None


async def _run_startup_ingestion() -> None:
    """Background startup runner for database setup and document ingestion."""
    try:
        # Initialize application database tables via SQLAlchemy metadata
        db_mgr = get_db_manager()
        db_mgr.init_database()

        # Ingestion service background execution
        await asyncio.to_thread(IngestionService.run)

        service_state.is_ready = True
        logger.info("Startup initialization and ingestion completed successfully")
    except Exception as exc:
        logger.exception("Startup ingestion background task failed")
        service_state.is_ready = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI application lifespan managing background initialization."""
    global _ingestion_task
    logger.info("Starting up Veltrix PeopleOps Assistant application")
    _ingestion_task = asyncio.create_task(_run_startup_ingestion())
    yield
    logger.info("Shutting down Veltrix PeopleOps Assistant application")
    if _ingestion_task and not _ingestion_task.done():
        _ingestion_task.cancel()
