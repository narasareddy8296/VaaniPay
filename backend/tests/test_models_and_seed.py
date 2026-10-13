"""Tests for synthetic models, repeatable seed operation, and data integrity."""

from sqlalchemy.orm import Session
from app.models.account import Account
from app.models.contact import Contact
from app.models.session import PaymentSession
from app.models.handoff import HandoffCase
from app.models.audit import AuditEvent
from app.db.seed import seed_database


def test_seed_database_creates_synthetic_accounts_and_contacts(db_session: Session):
    """
    Verifies that the seed operation creates the exact required demo accounts
    (Priya Sharma, Ramesh Kumar, Support Agent) with contacts and initial balances.
    """
    result = seed_database(db_session)
    assert result["status"] == "seeded"

    # Verify Accounts
    priya = db_session.query(Account).filter(Account.id == "acc_priya").first()
    assert priya is not None
    assert priya.holder_name == "Priya Sharma"
    assert priya.account_number == "ACC_PRIYA_001"
    assert priya.balance == 50000.00
    assert priya.currency == "INR"
    assert priya.role == "customer"
    assert priya.is_active is True
    # Plaintext PIN must NEVER be stored
    assert priya.hashed_pin != "1234"
    assert priya.hashed_pin.startswith("$argon2id$")

    ramesh = db_session.query(Account).filter(Account.id == "acc_ramesh").first()
    assert ramesh is not None
    assert ramesh.holder_name == "Ramesh Kumar"
    assert ramesh.balance == 25000.00
    assert ramesh.role == "customer"

    agent = db_session.query(Account).filter(Account.id == "acc_agent").first()
    assert agent is not None
    assert agent.role == "agent"
    assert agent.balance == 0.00

    # Verify Priya's contacts
    priya_contacts = db_session.query(Contact).filter(Contact.account_id == "acc_priya").all()
    assert len(priya_contacts) == 3
    priya_contact_names = {c.contact_name for c in priya_contacts}
    assert "Ramesh Kumar" in priya_contact_names
    assert "Sharmaji" in priya_contact_names
    assert "Neha" in priya_contact_names

    # Verify Ramesh's contacts
    ramesh_contacts = db_session.query(Contact).filter(Contact.account_id == "acc_ramesh").all()
    assert len(ramesh_contacts) == 2
    ramesh_contact_names = {c.contact_name for c in ramesh_contacts}
    assert "Priya Sharma" in ramesh_contact_names
    assert "Amit" in ramesh_contact_names


def test_repeatable_seed_is_idempotent(db_session: Session):
    """
    Verifies that executing seed_database multiple times does NOT duplicate
    accounts or contacts.
    """
    # First execution
    seed_database(db_session)
    count_accounts_1 = db_session.query(Account).count()
    count_contacts_1 = db_session.query(Contact).count()
    assert count_accounts_1 == 3
    assert count_contacts_1 == 5

    # Second execution
    res2 = seed_database(db_session)
    count_accounts_2 = db_session.query(Account).count()
    count_contacts_2 = db_session.query(Contact).count()

    assert count_accounts_2 == count_accounts_1
    assert count_contacts_2 == count_contacts_1
    assert res2["newly_added_accounts"] == 0
    assert res2["newly_added_contacts"] == 0


def test_payment_session_and_handoff_case_lifecycle(db_session: Session):
    """Verifies creation and relationship linking for payment sessions and handoff cases."""
    seed_database(db_session)

    session = PaymentSession(
        id="sess_test_001",
        account_id="acc_priya",
        current_state="CAPTURE",
        channel="VOICE",
        raw_transcript="Ramesh ko paanch sau rupaye bhej do",
        pending_amount=500.0,
        pending_payee_name="Ramesh Kumar",
        liveness_challenge="4 7 2",
    )
    db_session.add(session)
    db_session.flush()

    assert session.current_state == "CAPTURE"
    assert session.account.holder_name == "Priya Sharma"

    handoff = HandoffCase(
        id="case_test_001",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="DISAGREEMENT_AMOUNT",
        uncertain_field="amount",
        context_data='{"parser_amount": 500, "secondary_amount": 5000}',
        status="PENDING",
    )
    db_session.add(handoff)
    db_session.flush()

    assert handoff.session.id == "sess_test_001"
    assert handoff.account.holder_name == "Priya Sharma"
    assert handoff.status == "PENDING"


def test_audit_event_logging_model(db_session: Session):
    """Verifies audit event records without logging sensitive data."""
    audit = AuditEvent(
        id="aud_test_001",
        session_id="sess_test_001",
        account_id="acc_priya",
        event_type="THRESHOLD_CHANGED",
        details='{"field": "PIN_STEP_UP_THRESHOLD", "old": 2000.0, "new": 1500.0}',
        client_ip="127.0.0.1",
    )
    db_session.add(audit)
    db_session.flush()

    retrieved = db_session.query(AuditEvent).filter(AuditEvent.id == "aud_test_001").first()
    assert retrieved is not None
    assert retrieved.event_type == "THRESHOLD_CHANGED"
    assert "2000.0" in retrieved.details
