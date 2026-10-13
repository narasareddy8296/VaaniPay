"""Pytest configuration and test fixtures for VaaniPay."""

import os
import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine
import sqlite3

# Set environment before importing app settings
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_vaanipay.db"

from app.db.database import Base
from app.core.config import get_settings, Settings
from app.main import app

# Create test engine with SQLite foreign key enforcement
TEST_DATABASE_URL = "sqlite:///./test_vaanipay.db"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(test_engine, "connect")
def enforce_sqlite_fk_test(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
    future=True,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Initializes schema before test run and cleans up SQLite test file afterwards."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists("./test_vaanipay.db"):
        try:
            os.remove("./test_vaanipay.db")
        except OSError:
            pass


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Provides a fresh isolated database transaction for each test function."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Test client for invoking FastAPI endpoints."""
    from app.db.database import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_auth_headers(account_id: str = "acc_priya", role: str = "customer", expires_in_seconds: int = 3600) -> dict:
    """Helper to generate Authorization header with a valid server-signed session token."""
    from app.core.session import create_session_token
    token = create_session_token(account_id=account_id, role=role, expires_in_seconds=expires_in_seconds)
    return {"Authorization": f"Bearer {token}"}
