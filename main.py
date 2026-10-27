import os

os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import datetime
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.lifespan import is_service_ready, lifespan
from app.core.middlewares import RequestContextMiddleware
from app.core.status_codes import StatusCode
from app.exceptions.custom_exceptions import AppException, InternalServerException
from app.exceptions.exception_handlers import register_exception_handlers
from app.route.chat_route import router as chat_router
from config.app_config import validate_api_configuration
from config.logger import setup_logging

# Configure logging before application initialization
setup_logging()
validate_api_configuration()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Veltrix PeopleOps Assistant",
    description="AI HR assistant for policy Q&A and leave operations",
    version="0.1.0",
    lifespan=lifespan,
)

# Register centralized custom exception handlers
register_exception_handlers(app)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)


@app.get("/")
def root() -> JSONResponse:
    """Root endpoint confirming server status."""
    return JSONResponse(
        status_code=StatusCode.OK,
        content={
            "status": "online",
            "message": "Veltrix PeopleOps Assistant is running successfully",
            "health": "/health",
            "chat": "/chat",
            "docs": "/docs",
        },
    )


@app.get("/health")
def health_check() -> JSONResponse:
    """Return service health status with current UTC timestamp. Returns 200 when ready, 503 during ingestion."""
    try:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if not is_service_ready():
            return JSONResponse(
                status_code=StatusCode.SERVICE_UNAVAILABLE,
                content={
                    "status": "initializing",
                    "timestamp": now_iso,
                    "message": "Corpus ingestion in progress",
                },
            )
        return JSONResponse(
            status_code=StatusCode.OK,
            content={"status": "ok"},
        )
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Health check failed unexpectedly")
        raise InternalServerException("Health check encountered internal error") from exc


# Register Chat router
app.include_router(chat_router)

logger.info("FastAPI application initialized and root routes registered")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
