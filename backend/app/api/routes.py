import logging

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.health import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=request.app.state.settings.app_name,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    tags=["health"],
    responses={503: {"description": "A required dependency is unavailable"}},
)
def readiness(request: Request) -> ReadinessResponse:
    try:
        with request.app.state.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except SQLAlchemyError as exc:
        logger.warning("Readiness check failed: database unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": {"database": "unavailable"}},
        ) from exc

    return ReadinessResponse(status="ready", checks={"database": "ok"})
