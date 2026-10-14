"""
Stage 9 Regression and Feature Tests:
1. Double-entry payment balance consistency (3x ₹500 leaving ₹48,500).
2. Database as source of truth across server reloads/re-seeds.
3. Idempotency replay and duplicate submission prevention.
4. Cancelled, failed, or unauthorized payments do not modify balances.
5. Customer-managed contacts creation, listing, customer ownership isolation.
6. Validation, self-payee rejection, duplicate payee conflict rejection.
7. New payee mandatory PIN step-up verification.
8. Ambiguous/missing payee clarification (never guessing).
"""

import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.seed import seed_database
from app.models.account import Account
from app.models.contact import Contact
from app.models.ledger import LedgerEntry
from app.models.session import PaymentSession
from app.schemas.turn import DialogueAction, DialogueState
from app.services.payment_service import PaymentLedgerService
from tests.conftest import make_auth_headers


def test_three_payments_leave_exact_reconciled_balance_and_survive_reseed(
    client: TestClient, db_session: Session
):
    """
    Regression Test (Part A):
    Three successful ₹500 payments from a ₹50,000 starting balance must leave ₹48,500.
    The database must be the source of truth, and seed_database (server reloads) must
    preserve and reconcile the authoritative balance rather than resetting it.
    """
    seed_database(db_session, force_reset_balances=True)

    priya = db_session.query(Account).filter(Account.id == "acc_priya").first()
    ramesh = db_session.query(Account).filter(Account.id == "acc_ramesh").first()
    assert float(priya.balance) == 50000.00
    assert float(ramesh.balance) == 25000.00

    # Payment 1: ₹500
    res1 = PaymentLedgerService.execute_payment(
        db=db_session,
        sender_id="acc_priya",
        receiver_id="acc_ramesh",
        amount=500.00,
        description="Tx 1: 500 to Ramesh",
        idempotency_key="tx_stage9_seq_01",
    )
    assert res1.success is True
    assert res1.sender_balance_after == 49500.00

    # Payment 2: ₹500
    res2 = PaymentLedgerService.execute_payment(
        db=db_session,
        sender_id="acc_priya",
        receiver_id="acc_ramesh",
        amount=500.00,
        description="Tx 2: 500 to Ramesh",
        idempotency_key="tx_stage9_seq_02",
    )
    assert res2.success is True
    assert res2.sender_balance_after == 49000.00

    # Payment 3: ₹500
    res3 = PaymentLedgerService.execute_payment(
        db=db_session,
        sender_id="acc_priya",
        receiver_id="acc_ramesh",
        amount=500.00,
        description="Tx 3: 500 to Ramesh",
        idempotency_key="tx_stage9_seq_03",
    )
    assert res3.success is True
    assert res3.sender_balance_after == 48500.00

    # Verify Account Table Balances
    db_session.refresh(priya)
    db_session.refresh(ramesh)
    assert float(priya.balance) == 48500.00
    assert float(ramesh.balance) == 26500.00

    # Verify Double-Entry Ledger Count and Integrity
    entries = db_session.query(LedgerEntry).filter(
        LedgerEntry.transaction_id.in_(["tx_stage9_seq_01", "tx_stage9_seq_02", "tx_stage9_seq_03"])
    ).all()
    assert len(entries) == 6  # 3 Debits + 3 Credits

    debits = [e for e in entries if e.entry_type == "DEBIT"]
    credits = [e for e in entries if e.entry_type == "CREDIT"]
    assert sum(e.amount for e in debits) == 1500.00
    assert sum(e.amount for e in credits) == 1500.00

    # Critical Root Cause Regression Check:
    # Simulates server reload (uvicorn --reload) where lifespan calls seed_database(db)
    seed_database(db_session, force_reset_balances=False)

    db_session.refresh(priya)
    db_session.refresh(ramesh)
    assert float(priya.balance) == 48500.00, "Server reload must NOT reset Priya's balance back to 50,000!"
    assert float(ramesh.balance) == 26500.00, "Server reload must NOT reset Ramesh's balance back to 25,000!"


def test_duplicate_submission_and_idempotency_replay(
    client: TestClient, db_session: Session
):
    """
    Ensures network retries and duplicate submissions with the same idempotency key
    do not perform multiple debits.
    """
    seed_database(db_session, force_reset_balances=True)
    priya_initial = float(db_session.query(Account).filter(Account.id == "acc_priya").first().balance)

    key = "tx_idempotent_test_key_999"

    # First execution
    res1 = PaymentLedgerService.execute_payment(
        db_session, "acc_priya", "acc_ramesh", 1000.00, idempotency_key=key
    )
    assert res1.success is True
    assert res1.is_idempotent_replay is False
    assert res1.sender_balance_after == priya_initial - 1000.00

    # Duplicate execution attempt with same idempotency key
    res2 = PaymentLedgerService.execute_payment(
        db_session, "acc_priya", "acc_ramesh", 1000.00, idempotency_key=key
    )
    assert res2.success is True
    assert res2.is_idempotent_replay is True
    assert res2.sender_balance_after == priya_initial - 1000.00

    # Priya's balance must only be debited once
    priya_after = float(db_session.query(Account).filter(Account.id == "acc_priya").first().balance)
    assert priya_after == priya_initial - 1000.00

    # Exactly 1 debit entry for this transaction key
    debit_count = db_session.query(LedgerEntry).filter(
        LedgerEntry.transaction_id == key,
        LedgerEntry.account_id == "acc_priya",
        LedgerEntry.entry_type == "DEBIT",
    ).count()
    assert debit_count == 1


def test_cancelled_or_failed_payment_leaves_balances_unchanged(
    client: TestClient, db_session: Session
):
    """
    Cancelled, unauthorized, or failed payment attempts must never alter balances or post debits.
    """
    seed_database(db_session, force_reset_balances=True)
    priya_initial = float(db_session.query(Account).filter(Account.id == "acc_priya").first().balance)
    headers = make_auth_headers("acc_priya")

    # 1. Start dialogue turn and cancel in READBACK
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Send 500 to Ramesh",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    session_id = r1.json()["session_id"]

    # Explicit cancel
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.CANCEL.value,
            "channel": "TYPED",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == DialogueState.CANCELLED.value

    # Balance must remain completely unchanged
    priya_current = float(db_session.query(Account).filter(Account.id == "acc_priya").first().balance)
    assert priya_current == priya_initial

    # 2. Insufficient funds failure
    priya = db_session.query(Account).filter(Account.id == "acc_priya").first()
    priya.balance = 200.00
    db_session.commit()

    res_fail = PaymentLedgerService.execute_payment(
        db_session, "acc_priya", "acc_ramesh", 500.00
    )
    assert res_fail.success is False
    assert "Insufficient funds" in res_fail.explanation

    priya_after_fail = float(db_session.query(Account).filter(Account.id == "acc_priya").first().balance)
    assert priya_after_fail == 200.00


def test_contacts_crud_and_customer_isolation(client: TestClient, db_session: Session):
    """
    Part B Test:
    - Customer can list and create contacts.
    - Identity isolation enforced: Priya cannot access or modify Ramesh's contacts.
    - Adding a contact does NOT authorize any payment.
    """
    seed_database(db_session, force_reset_balances=True)
    priya_headers = make_auth_headers("acc_priya")
    ramesh_headers = make_auth_headers("acc_ramesh")

    # 1. List Priya's seeded contacts
    r_list = client.get("/api/v1/accounts/acc_priya/contacts", headers=priya_headers)
    assert r_list.status_code == 200
    contacts = r_list.json()
    assert len(contacts) >= 3
    names = [c["contact_name"] for c in contacts]
    assert "Ramesh Kumar" in names

    # 2. Add a new contact for Priya with mock account
    payload = {
        "contact_name": "Vikram Verma",
        "beneficiary_account_id": "acc_vikram",
        "phone_number": "+919876543290",
        "aliases": "Vikram,Vicky",
    }
    r_create = client.post(
        "/api/v1/accounts/acc_priya/contacts",
        json=payload,
        headers=priya_headers,
    )
    assert r_create.status_code == 201
    created = r_create.json()
    assert created["contact_name"] == "Vikram Verma"
    assert created["beneficiary_account_id"] == "acc_vikram"
    assert created["is_frequent"] is False  # Enforced to mandate step-up PIN!

    # 3. Verify newly added contact persists in list
    r_list2 = client.get("/api/v1/accounts/acc_priya/contacts", headers=priya_headers)
    assert r_list2.status_code == 200
    assert any(c["contact_name"] == "Vikram Verma" for c in r_list2.json())

    # 4. Identity isolation: Priya cannot view Ramesh's contacts
    r_forbidden_get = client.get("/api/v1/accounts/acc_ramesh/contacts", headers=priya_headers)
    assert r_forbidden_get.status_code == 403

    # 5. Identity isolation: Priya cannot create contacts on Ramesh's account
    r_forbidden_post = client.post(
        "/api/v1/accounts/acc_ramesh/contacts",
        json={"contact_name": "Hacker Contact", "beneficiary_account_id": "acc_priya"},
        headers=priya_headers,
    )
    assert r_forbidden_post.status_code == 403


def test_contact_validation_and_conflict_rejection(client: TestClient, db_session: Session):
    """
    Validates name length, beneficiary existence, self-payee rejection, and duplicate conflict.
    """
    seed_database(db_session, force_reset_balances=True)
    headers = make_auth_headers("acc_priya")

    # Name too short (< 2 chars)
    r_short = client.post(
        "/api/v1/accounts/acc_priya/contacts",
        json={"contact_name": "V", "beneficiary_account_id": "acc_ramesh"},
        headers=headers,
    )
    assert r_short.status_code == 400
    assert "at least 2 characters" in r_short.json()["detail"]

    # Missing mock account identifier
    r_no_acc = client.post(
        "/api/v1/accounts/acc_priya/contacts",
        json={"contact_name": "Anita Roy", "beneficiary_account_id": ""},
        headers=headers,
    )
    assert r_no_acc.status_code == 400

    # Cannot add own account as payee
    r_self = client.post(
        "/api/v1/accounts/acc_priya/contacts",
        json={"contact_name": "Priya Duplicate", "beneficiary_account_id": "acc_priya"},
        headers=headers,
    )
    assert r_self.status_code == 400
    assert "own account" in r_self.json()["detail"].lower()

    # Duplicate name conflict (Ramesh Kumar already in Priya's contacts)
    r_dup_name = client.post(
        "/api/v1/accounts/acc_priya/contacts",
        json={"contact_name": "Ramesh Kumar", "beneficiary_account_id": "acc_another_99"},
        headers=headers,
    )
    assert r_dup_name.status_code == 409
    assert "already exists" in r_dup_name.json()["detail"]

    # Duplicate account conflict (acc_ramesh already assigned to Ramesh Kumar)
    r_dup_acc = client.post(
        "/api/v1/accounts/acc_priya/contacts",
        json={"contact_name": "Another Ramesh", "beneficiary_account_id": "acc_ramesh"},
        headers=headers,
    )
    assert r_dup_acc.status_code == 409
    assert "already exists" in r_dup_acc.json()["detail"]


def test_voice_payment_to_new_contact_triggers_mandatory_pin_step_up(
    client: TestClient, db_session: Session
):
    """
    Security Invariant:
    A newly added contact has is_frequent=False.
    Making a voice payment to this contact must mandate step-up PIN verification
    before any debit occurs, even if amount <= ₹2,000.
    """
    seed_database(db_session, force_reset_balances=True)
    headers = make_auth_headers("acc_priya")

    # Create new contact "Sunil" pointing to mock account acc_sunil
    r_create = client.post(
        "/api/v1/accounts/acc_priya/contacts",
        json={
            "contact_name": "Sunil",
            "beneficiary_account_id": "acc_sunil",
            "aliases": "Sunil,Sunilji",
        },
        headers=headers,
    )
    assert r_create.status_code == 201

    # Turn 1: Voice request "Send 500 to Sunil"
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Send 500 to Sunil",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["state"] == DialogueState.READBACK.value
    session_id = r1.json()["session_id"]

    # Turn 2: Confirm Readback
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.CONFIRM_READBACK.value,
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == DialogueState.LIVENESS.value
    challenge = r2.json()["liveness_challenge"]

    # Turn 3: Repeat challenge
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_LIVENESS.value,
            "liveness_response": challenge,
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    # Mandatory PIN Step-Up because Sunil is a New Payee!
    assert r3.json()["state"] == DialogueState.STEP_UP_PIN.value
    assert r3.json()["requires_pin"] is True
    reasons = r3.json().get("context", {}).get("step_up_reasons", [])
    assert any("New Payee" in r for r in reasons)


def test_missing_or_ambiguous_payee_clarification_never_guesses(
    client: TestClient, db_session: Session
):
    """
    If a payee is missing or ambiguous, the state machine must transition
    to CLARIFY_PAYEE and prompt the customer, never silently guessing a recipient.
    """
    seed_database(db_session, force_reset_balances=True)
    headers = make_auth_headers("acc_priya")

    # Unrecognized payee
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Send 500 to UnknownStranger999",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["state"] == DialogueState.CLARIFY_PAYEE.value
    assert "not recognized" in r1.json()["prompt_text"].lower()

    # Payee omitted completely
    r2 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Please send 500 rupees",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == DialogueState.CLARIFY_PAYEE.value
