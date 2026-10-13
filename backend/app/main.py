"""
FastAPI application entrypoint for VaaniPay.
Configures middleware, routes, database lifespan events, and interactive documentation.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.db.database import Base, engine, SessionLocal
from app.db.seed import seed_database
from app.api.routes.health import router as health_router
from app.api.routes.turn import router as turn_router
from app.api.routes.handoff import router as handoff_router
from app.api.routes.accounts import router as accounts_router
from app.schemas.health import HealthResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    Initializes database schema and ensures baseline synthetic accounts exist.
    """
    # 1. Create database tables if they do not exist
    Base.metadata.create_all(bind=engine)

    # 2. Automatically ensure demo seeds are populated
    with SessionLocal() as session:
        seed_database(session)

    yield


# FastAPI Application Instance
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="VaaniPay Voice Banking Agent Backend — Fail-Safe Mock Payment Engine.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Cross-Origin Resource Sharing (CORS) Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root Health Route (Direct compliance with REQ-02 /health requirement)
@app.get("/health", response_model=HealthResponse, tags=["Health"])
def root_health() -> HealthResponse:
    """Root health check endpoint returning status, version, and active environment."""
    return HealthResponse(
        status="healthy",
        app=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
    )


# API Version 1 Routers
app.include_router(health_router, prefix=settings.API_V1_STR)
app.include_router(turn_router, prefix=settings.API_V1_STR)
app.include_router(handoff_router, prefix=settings.API_V1_STR)
app.include_router(accounts_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Root"])
def root_index():
    """Service metadata and documentation pointers."""
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/health",
    }
