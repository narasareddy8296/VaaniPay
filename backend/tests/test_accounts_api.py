"""Unit tests for Accounts, Profile, and Demo Login endpoints."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.account import Account
from tests.conftest import make_auth_headers


def test_list_accounts(client: TestClient, db_session: Session):
    """Verifies listing seeded accounts."""
    seed_database(db_session)
    response = client.get("/api/v1/accounts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    account_ids = [a["id"] for a in data]
    assert "acc_priya" in account_ids
    assert "acc_ramesh" in account_ids
    assert "acc_agent" in account_ids


def test_get_account_detail_and_contacts(client: TestClient, db_session: Session):
    """Verifies fetching account details, balance, and contacts with session auth."""
    seed_database(db_session)
    response = client.get("/api/v1/accounts/acc_priya", headers=make_auth_headers("acc_priya"))
    assert response.status_code == 200
    data = response.json()
    assert data["holder_name"] == "Priya Sharma"
    assert data["balance"] == 50000.0
    assert len(data["contacts"]) >= 3


def test_demo_login_success(client: TestClient, db_session: Session):
    """Verifies demo-safe authentication returns account profile, session token, and demo notice."""
    seed_database(db_session)
    response = client.post(
        "/api/v1/accounts/demo-login",
        json={"account_id": "acc_priya"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "customer"
    assert data["is_demo"] is True
    assert "session_token" in data
    assert len(data["session_token"]) > 20
    assert data["token_type"] == "Bearer"
    assert "DEMO EVALUATION MODE" in data["auth_notice"]


def test_demo_login_locked_account_rejected(client: TestClient, db_session: Session):
    """Locked accounts are blocked from logging in."""
    seed_database(db_session)
    priya = db_session.query(Account).filter(Account.id == "acc_priya").first()
    priya.is_locked = True
    db_session.commit()

    response = client.post(
        "/api/v1/accounts/demo-login",
        json={"account_id": "acc_priya"},
    )
    assert response.status_code == 403
    assert "locked" in response.json()["detail"].lower()


def test_get_account_transactions(client: TestClient, db_session: Session):
    """Verifies fetching mock ledger transactions with session auth."""
    seed_database(db_session)
    response = client.get("/api/v1/accounts/acc_priya/transactions", headers=make_auth_headers("acc_priya"))
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
