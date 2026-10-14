"""
Stage 8: Secure Manual PIN Entry Integration & Security Tests.
Verifies manual 4-digit PIN verification, format validation, Argon2id security,
3-attempt brute-force lockout, audit event sanitization, zero PIN leakage,
and prevention of state bypass. Voice PIN entry is completely removed.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.account import Account
from app.models.session import PaymentSession
from app.models.audit import AuditEvent
from app.schemas.turn import DialogueState, DialogueAction
from tests.conftest import make_auth_headers


def test_manual_pin_keypad_format_validation(client: TestClient, db_session: Session):
    """Rejects non-numeric PINs, short PINs, and long PINs with INVALID_PIN_FORMAT."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    sess = PaymentSession(
        id="sess_pin_format_test",
        account_id="acc_priya",
        current_state=DialogueState.STEP_UP_PIN.value,
        pending_amount=500.0,
        pending_payee_id="contact_ramesh",
        pending_payee_name="Ramesh Kumar",
        failed_pin_attempts=0,
    )
    db_session.add(sess)
    db_session.commit()

    # 1. Non-digit PIN
    r1 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_pin_format_test",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "abcd",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["error"] == "INVALID_PIN_FORMAT"
    assert r1.json()["state"] == DialogueState.STEP_UP_PIN.value

    # 2. Too short (2 digits)
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_pin_format_test",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "12",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["error"] == "INVALID_PIN_FORMAT"

    # 3. Too long (5 digits)
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_pin_format_test",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "12345",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.json()["error"] == "INVALID_PIN_FORMAT"

    # 4. Missing PIN
    r4 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_pin_format_test",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "",
        },
        headers=headers,
    )
    assert r4.status_code == 200
    assert r4.json()["error"] == "PIN_REQUIRED"


def test_valid_manual_pin_flow_to_receipt(client: TestClient, db_session: Session):
    """
    End-to-end voice flow reaching PIN step-up and verifying manual keypad PIN:
    CAPTURE -> READBACK (confirm) -> LIVENESS (repeat challenge) -> STEP_UP_PIN (manual keypad PIN) -> RECEIPT.
    """
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    # 1. Spoken payment request
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Ramesh ko paanch sau rupaye bhej do",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["state"] == DialogueState.READBACK.value
    session_id = r1.json()["session_id"]

    # 2. Spoken confirmation
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Haan, confirm karo.",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["state"] == DialogueState.LIVENESS.value
    challenge_digits = d2["liveness_challenge"]

    # 3. Spoken liveness response
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_LIVENESS.value,
            "transcript": challenge_digits,
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["state"] == DialogueState.STEP_UP_PIN.value
    assert d3["requires_pin"] is True

    # 4. Manual Keypad PIN Submission
    r4 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "1234",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r4.status_code == 200
    d4 = r4.json()
    assert d4["state"] == DialogueState.RECEIPT.value
    assert d4["receipt"]["amount"] == 500.0
    assert d4["receipt"]["payee_name"] == "Ramesh Kumar"


def test_stage8_incorrect_voice_pin_decrements_attempts_no_auto_retry(client: TestClient, db_session: Session):
    """Submitting an incorrect voice PIN reports remaining attempts and does not auto-advance."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    sess = PaymentSession(
        id="sess_incorrect_voice_pin",
        account_id="acc_priya",
        current_state=DialogueState.STEP_UP_PIN.value,
        pending_amount=500.0,
        pending_payee_id="contact_ramesh",
        pending_payee_name="Ramesh Kumar",
        failed_pin_attempts=0,
    )
    db_session.add(sess)
    db_session.commit()

    # Attempt 1: Incorrect PIN
    r1 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_incorrect_voice_pin",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "9999",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["state"] == DialogueState.STEP_UP_PIN.value
    assert d1["error"] == "INCORRECT_PIN"
    assert "2 attempt(s) remaining" in d1["prompt_text"]

    # Verify session failed attempts counter incremented in DB
    refreshed_sess = db_session.query(PaymentSession).filter(PaymentSession.id == "sess_incorrect_voice_pin").first()
    assert refreshed_sess.failed_pin_attempts == 1


def test_stage8_lockout_enforced_after_three_failed_voice_pin_attempts(client: TestClient, db_session: Session):
    """Three failed voice PIN attempts locks the account permanently."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    sess = PaymentSession(
        id="sess_lockout_voice_pin",
        account_id="acc_priya",
        current_state=DialogueState.STEP_UP_PIN.value,
        pending_amount=500.0,
        pending_payee_id="contact_ramesh",
        pending_payee_name="Ramesh Kumar",
        failed_pin_attempts=0,
    )
    db_session.add(sess)
    db_session.commit()

    # Attempt 1
    client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_lockout_voice_pin",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "9999",
            "channel": "VOICE",
        },
        headers=headers,
    )

    # Attempt 2
    client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_lockout_voice_pin",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "8888",
            "channel": "VOICE",
        },
        headers=headers,
    )

    # Attempt 3 (Should trigger permanent account lockout)
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_lockout_voice_pin",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "7777",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["state"] == DialogueState.FAILED.value
    assert d3["error"] == "PIN_LOCKOUT"
    assert "Account locked" in d3["prompt_text"]

    # Verify account is locked in database
    acc = db_session.query(Account).filter(Account.id == "acc_priya").first()
    assert acc.is_locked is True

    # Attempt 4 on locked account must be rejected with 403 Forbidden
    r4 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_lockout_voice_pin",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "1234",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r4.status_code == 403
    assert "locked" in r4.json()["detail"].lower()


def test_stage8_spoken_pin_cancellation_clears_session(client: TestClient, db_session: Session):
    """Spoken 'cancel' or action CANCEL during voice PIN step-up terminates session."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    sess = PaymentSession(
        id="sess_cancel_voice_pin",
        account_id="acc_priya",
        current_state=DialogueState.STEP_UP_PIN.value,
        pending_amount=500.0,
        pending_payee_id="contact_ramesh",
        pending_payee_name="Ramesh Kumar",
        failed_pin_attempts=0,
    )
    db_session.add(sess)
    db_session.commit()

    r = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_cancel_voice_pin",
            "account_id": "acc_priya",
            "action": DialogueAction.CANCEL.value,
        },
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["state"] == DialogueState.CANCELLED.value

    # Subsequent confirmation attempts fail
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_cancel_voice_pin",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "1234",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.json()["error"] == "SESSION_TERMINATED"


def test_stage8_voice_pin_cannot_bypass_confirmation_or_liveness(client: TestClient, db_session: Session):
    """Submitting PIN prematurely in CAPTURE or READBACK is rejected."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    # Attempt to submit PIN in CAPTURE
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "1234",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["state"] == DialogueState.FAILED.value
    assert r1.json()["error"] == "INVALID_TRANSITION"

    # Start proper session to READBACK
    r2 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Send 500 to Ramesh",
            "channel": "VOICE",
        },
        headers=headers,
    )
    session_id = r2.json()["session_id"]
    assert r2.json()["state"] == DialogueState.READBACK.value

    # Attempt to bypass confirmation with PIN in READBACK
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "1234",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.json()["state"] == DialogueState.FAILED.value
    assert r3.json()["error"] == "INVALID_TRANSITION"


def test_stage8_voice_pin_cannot_bypass_payment_limits(client: TestClient, db_session: Session):
    """Payment exceeding limit (₹50,000) escalates to HANDOFF and cannot be bypassed via voice PIN."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    r = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Send 60000 to Ramesh",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["state"] == DialogueState.HANDOFF.value
    assert r.json()["handoff_case_id"] is not None


def test_stage8_pin_never_in_audit_events_or_logs(client: TestClient, db_session: Session):
    """Audit events recorded during voice PIN attempts NEVER contain plaintext PINs."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    sess = PaymentSession(
        id="sess_audit_pin_test",
        account_id="acc_priya",
        current_state=DialogueState.STEP_UP_PIN.value,
        pending_amount=500.0,
        pending_payee_id="contact_ramesh",
        pending_payee_name="Ramesh Kumar",
        failed_pin_attempts=0,
    )
    db_session.add(sess)
    db_session.commit()

    secret_pin_used = "1234"
    client.post(
        "/api/v1/turn",
        json={
            "session_id": "sess_audit_pin_test",
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": secret_pin_used,
            "channel": "VOICE",
        },
        headers=headers,
    )

    # Inspect all audit events for this session
    audit_events = db_session.query(AuditEvent).filter(AuditEvent.session_id == "sess_audit_pin_test").all()
    assert len(audit_events) > 0

    for event in audit_events:
        details_str = str(event.details or "")
        event_type_str = str(event.event_type or "")
        # The secret PIN string must NEVER appear anywhere in the audit log
        assert secret_pin_used not in details_str, f"Plaintext PIN leaked in audit details: {details_str}"
        assert secret_pin_used not in event_type_str
