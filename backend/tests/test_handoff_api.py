"""
Unit tests for Human Handoff queue, agent resolution endpoints, and audit security.
Verifies agent authorization via server-validated session tokens, mandatory operator notes,
and the safety invariant that agent approval does NOT execute payments or bypass safeguards.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.account import Account
from app.models.session import PaymentSession
from app.models.handoff import HandoffCase
from app.models.ledger import LedgerEntry
from app.models.audit import AuditEvent
from app.schemas.handoff import HandoffAction
from tests.conftest import make_auth_headers


def test_list_and_get_handoff_cases(client: TestClient, db_session: Session):
    """Verifies listing and viewing cases in the human handoff queue with agent session."""
    seed_database(db_session)
    session = PaymentSession(id="sess_h_1", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(
        id="case_test_101",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="DISAGREEMENT_AMOUNT",
        uncertain_field="amount",
        context_data='{"transcript": "Ramesh ko dedh hazaar bhej do"}',
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    agent_headers = make_auth_headers("acc_agent", role="agent")

    # List cases
    r_list = client.get("/api/v1/handoff/cases", headers=agent_headers)
    assert r_list.status_code == 200
    cases_data = r_list.json()
    assert len(cases_data) >= 1
    assert any(c["id"] == "case_test_101" for c in cases_data)

    # Get single case
    r_single = client.get(f"/api/v1/handoff/cases/{case.id}", headers=agent_headers)
    assert r_single.status_code == 200
    assert r_single.json()["id"] == "case_test_101"
    assert r_single.json()["customer_name"] == "Priya Sharma"


def test_agent_resolution_requires_agent_role(client: TestClient, db_session: Session):
    """Customers cannot resolve handoff cases; server rejects customer session with 403."""
    seed_database(db_session)
    session = PaymentSession(id="sess_h_2", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(id="case_test_102", session_id=session.id, account_id="acc_priya", escalation_reason="SPOOF_RISK_HIGH")
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    # Priya presents her customer session token
    customer_headers = make_auth_headers("acc_priya", role="customer")
    response = client.post(
        f"/api/v1/handoff/cases/{case.id}/resolve",
        json={
            "action": HandoffAction.APPROVE.value,
            "agent_id": "acc_priya",
            "notes": "Trying to self-approve",
        },
        headers=customer_headers,
    )
    assert response.status_code == 403
    assert "agent credentials required" in response.json()["detail"].lower()


def test_agent_resolution_requires_mandatory_explanation_note(client: TestClient, db_session: Session):
    """
    AUDIT COMPLIANCE REQUIREMENT: Operators cannot resolve a case without
    providing a non-empty explanation note.
    """
    seed_database(db_session)
    session = PaymentSession(id="sess_h_3", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(id="case_test_103", session_id=session.id, account_id="acc_priya", escalation_reason="USER_REQUESTED")
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    agent_headers = make_auth_headers("acc_agent", role="agent")

    # Agent submits empty note
    response = client.post(
        f"/api/v1/handoff/cases/{case.id}/resolve",
        json={
            "action": HandoffAction.APPROVE.value,
            "agent_id": "acc_agent",
            "notes": "   ",  # Blank note!
        },
        headers=agent_headers,
    )
    assert response.status_code == 422


def test_agent_approval_does_not_bypass_safeguards_or_execute_ledger(client: TestClient, db_session: Session):
    """
    CRITICAL SAFETY INVARIANT: An agent approval is an audit decision, NOT a payment execution command.
    A high-risk spoof result or blocked case must NEVER become executable or move funds
    solely because an agent clicks Approve!
    """
    seed_database(db_session)
    initial_priya_bal = db_session.query(Account).filter(Account.id == "acc_priya").first().balance
    initial_ledger_count = db_session.query(LedgerEntry).count()

    session = PaymentSession(id="sess_h_4", account_id="acc_priya", current_state="HANDOFF", pending_amount=500.0)
    case = HandoffCase(
        id="case_test_104",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="SPOOF_RISK_HIGH",
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    agent_headers = make_auth_headers("acc_agent", role="agent")

    # Agent approves the case with required note
    response = client.post(
        f"/api/v1/handoff/cases/{case.id}/resolve",
        json={
            "action": HandoffAction.APPROVE.value,
            "agent_id": "acc_agent",
            "notes": "Reviewed audio anomalies with customer over outbound call; approved case file.",
        },
        headers=agent_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"

    # Verify that balances and ledger entries remained completely UNTOUCHED
    db_session.expire_all()
    final_priya_bal = db_session.query(Account).filter(Account.id == "acc_priya").first().balance
    final_ledger_count = db_session.query(LedgerEntry).count()

    assert final_priya_bal == initial_priya_bal
    assert final_ledger_count == initial_ledger_count


def test_audit_logs_contain_zero_raw_audio_and_zero_plaintext_pins(db_session: Session):
    """
    PRIVACY & SECURITY INVARIANT: System audit logs must NEVER contain
    plaintext customer PINs or binary audio data.
    """
    seed_database(db_session)
    audit_records = db_session.query(AuditEvent).all()

    for record in audit_records:
        if record.details:
            assert "1234" not in record.details
            assert "5678" not in record.details
            assert "raw_audio" not in record.details
