"""Health check API route."""

from fastapi import APIRouter
from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Returns application health status, version, and active environment."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        app=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
    )
