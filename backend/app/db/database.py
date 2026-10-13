"""
Database initialization, connection pooling, and session lifecycle management.
Supports local SQLite with strict foreign key enforcement and PostgreSQL for cloud deployments.
"""

import sqlite3
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy 2.x models."""
    pass


settings = get_settings()

# Normalize database URL (cloud providers like Render/Supabase often output postgres://)
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Engine connection arguments
connect_args = {}
if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# SQLAlchemy 2.0 Engine
engine = create_engine(
    db_url,
    connect_args=connect_args,
    echo=settings.DEBUG,
    future=True,
)


@event.listens_for(Engine, "connect")
def enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    """
    Ensures SQLite rigorously enforces foreign key integrity constraints.
    SQLite disables foreign key checks by default; this listener enables them on connect.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Database Session Factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session and ensures it is safely closed
    after the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
