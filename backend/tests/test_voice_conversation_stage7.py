"""
Stage 7: End-to-End Voice-Driven Payment Conversation Tests.
Verifies multi-turn voice workflows, deterministic English/Hinglish confirmation
and cancellation intents, anti-feedback loop invariants, liveness challenge
spoken verification, and PIN step-up boundaries.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.session import PaymentSession
from app.schemas.turn import DialogueState, DialogueAction
from tests.conftest import make_auth_headers
from app.parsers.intent_parser import parse_confirmation_intent, ConfirmationIntent


def test_stage7_deterministic_intent_parser():
    """Unit tests for English & Hinglish confirmation and cancellation intents."""
    # Affirmative English
    assert parse_confirmation_intent("Yes, confirm.").intent == ConfirmationIntent.CONFIRM
    assert parse_confirmation_intent("confirm").intent == ConfirmationIntent.CONFIRM
    assert parse_confirmation_intent("proceed").intent == ConfirmationIntent.CONFIRM
    assert parse_confirmation_intent("yes please").intent == ConfirmationIntent.CONFIRM

    # Affirmative Hinglish
    assert parse_confirmation_intent("Haan, confirm karo.").intent == ConfirmationIntent.CONFIRM
    assert parse_confirmation_intent("haan").intent == ConfirmationIntent.CONFIRM
    assert parse_confirmation_intent("bhej do").intent == ConfirmationIntent.CONFIRM
    assert parse_confirmation_intent("kar do").intent == ConfirmationIntent.CONFIRM

    # Negative English
    assert parse_confirmation_intent("No, cancel.").intent == ConfirmationIntent.CANCEL
    assert parse_confirmation_intent("cancel").intent == ConfirmationIntent.CANCEL
    assert parse_confirmation_intent("stop payment").intent == ConfirmationIntent.CANCEL
    assert parse_confirmation_intent("do not send").intent == ConfirmationIntent.CANCEL

    # Negative Hinglish
    assert parse_confirmation_intent("Nahi, cancel karo.").intent == ConfirmationIntent.CANCEL
    assert parse_confirmation_intent("nahi").intent == ConfirmationIntent.CANCEL
    assert parse_confirmation_intent("mat bhejo").intent == ConfirmationIntent.CANCEL
    assert parse_confirmation_intent("ruk jao").intent == ConfirmationIntent.CANCEL

    # Ambiguous
    assert parse_confirmation_intent("yes but cancel").intent == ConfirmationIntent.AMBIGUOUS
    assert parse_confirmation_intent("haan nahi").intent == ConfirmationIntent.AMBIGUOUS
    assert parse_confirmation_intent("maybe").intent == ConfirmationIntent.AMBIGUOUS

    # Payment commands are NOT confirmation (SAFETY INVARIANT)
    assert parse_confirmation_intent("send 500 to Ramesh").intent == ConfirmationIntent.PAYMENT_REQUEST
    assert parse_confirmation_intent("dedh hazaar bhej do").intent == ConfirmationIntent.PAYMENT_REQUEST

    # Silence
    assert parse_confirmation_intent("").intent == ConfirmationIntent.SILENCE


def test_spoken_confirmation_advances_pending_transaction(client: TestClient, db_session: Session):
    """Spoken Hinglish confirmation 'Haan, confirm karo.' advances session from READBACK to LIVENESS."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    # Turn 1: Initial voice payment request
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
    d1 = r1.json()
    assert d1["state"] == DialogueState.READBACK.value
    session_id = d1["session_id"]
    assert d1["readback_card"]["amount_digits"] == 500

    # Turn 2: Spoken confirmation without clicking button
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
    assert d2["liveness_challenge"] is not None


def test_spoken_cancellation_permanently_stops_payment(client: TestClient, db_session: Session):
    """Spoken 'Nahi, cancel karo.' terminates session safely and blocks subsequent execution."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    # Turn 1: Enter READBACK
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

    # Turn 2: Spoken cancellation
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Nahi, cancel karo.",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["state"] == DialogueState.CANCELLED.value

    # Turn 3: Attempting to confirm a cancelled session must be rejected
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.CONFIRM_READBACK.value,
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.json()["error"] == "SESSION_TERMINATED"


def test_silence_and_unrelated_speech_do_not_confirm(client: TestClient, db_session: Session):
    """Silence, background noise, or unrelated utterances remain safely in READBACK."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

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
    session_id = r1.json()["session_id"]

    # Silence
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == DialogueState.READBACK.value

    # Unrelated speech
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "What is the weather outside today?",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.json()["state"] == DialogueState.READBACK.value
    assert "confirm" in r3.json()["prompt_text"].lower()


def test_payment_request_during_readback_does_not_confirm(client: TestClient, db_session: Session):
    """A new payment phrase (e.g. 'send 1000 to Priya') is rejected as confirmation."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

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
    session_id = r1.json()["session_id"]

    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Send 1000 to Priya",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    # Must NOT advance to LIVENESS or EXECUTE
    assert r2.json()["state"] == DialogueState.READBACK.value


def test_ambiguous_confirmation_requests_clarification(client: TestClient, db_session: Session):
    """Contradictory intent 'confirm but cancel' stays in READBACK and explains ambiguity."""
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

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
    session_id = r1.json()["session_id"]

    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "confirm but wait cancel",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == DialogueState.READBACK.value
    assert "tell if you wanted to confirm or cancel" in r2.json()["prompt_text"].lower()


def test_complete_voice_liveness_and_pin_step_up_flow(client: TestClient, db_session: Session):
    """Full voice flow: CAPTURE -> READBACK -> CONFIRM -> LIVENESS -> STEP_UP_PIN -> RECEIPT."""
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

    # 4. PIN Step-Up Verification (Masked Keypad entry)
    r4 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_PIN.value,
            "pin": "1234",
            "channel": "TYPED",
        },
        headers=headers,
    )
    assert r4.status_code == 200
    d4 = r4.json()
    assert d4["state"] == DialogueState.RECEIPT.value
    assert d4["receipt"]["amount"] == 500.0
    assert d4["receipt"]["payee_name"] == "Ramesh Kumar"
