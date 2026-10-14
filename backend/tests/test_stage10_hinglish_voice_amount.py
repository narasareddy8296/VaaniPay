"""
Stage 10: Hinglish & Devanagari Voice Amount Recognition Integration Tests.
Comprehensive validation of:
1. Exact required Hinglish & Devanagari amount phrases.
2. Colloquial fractions (dedh, dhai, sawa, paune, saade) & spellings/ASR variants.
3. Disentanglement of payee names from amount and payment intent verbs.
4. Transaction limit enforcement (₹10,000 limit: "sawa do lakh" = ₹225,000 -> HANDOFF).
5. Independent two-method extraction consensus and mismatch handling.
6. Full multi-turn conversational API flows.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.account import Account
from app.models.session import PaymentSession
from app.models.handoff import HandoffCase
from app.schemas.turn import DialogueState, DialogueAction
from tests.conftest import make_auth_headers
from app.parsers.number_parser import parse_amount, ParseStatus
from app.parsers.payee_resolver import PayeeResolver, PayeeResolutionStatus
from app.core.cross_check import (
    CrossCheckEngine,
    ConservativeSecondaryExtractor,
    CrossCheckStatus,
    SecondaryExtractor,
    SecondaryExtractionResult,
)


def test_stage10_exact_required_phrases():
    """Validates the exact amount phrases required by the assignment demo."""
    # 1. "dedh hazaar" = ₹1,500
    r1 = parse_amount("dedh hazaar")
    assert r1.status == ParseStatus.SUCCESS
    assert r1.amount == 1500
    assert r1.limit_exceeded is False

    # 2. "डेढ़ हज़ार" = ₹1,500
    r2 = parse_amount("डेढ़ हज़ार")
    assert r2.status == ParseStatus.SUCCESS
    assert r2.amount == 1500
    assert r2.limit_exceeded is False

    # 3. "dhai sau" = ₹250
    r3 = parse_amount("dhai sau")
    assert r3.status == ParseStatus.SUCCESS
    assert r3.amount == 250
    assert r3.limit_exceeded is False

    # 4. "ढाई सौ" = ₹250
    r4 = parse_amount("ढाई सौ")
    assert r4.status == ParseStatus.SUCCESS
    assert r4.amount == 250
    assert r4.limit_exceeded is False

    # 5. "paanch sau" = ₹500
    r5 = parse_amount("paanch sau")
    assert r5.status == ParseStatus.SUCCESS
    assert r5.amount == 500
    assert r5.limit_exceeded is False

    # 6. "sawa do lakh" = ₹225,000 (must be parsed accurately, then flagged as exceeding limit)
    r6 = parse_amount("sawa do lakh")
    assert r6.status == ParseStatus.SUCCESS
    assert r6.amount == 225000
    assert r6.limit_exceeded is True

    # 7. "sawa do lakh rupaye" = ₹225,000
    r7 = parse_amount("sawa do lakh rupaye")
    assert r7.status == ParseStatus.SUCCESS
    assert r7.amount == 225000
    assert r7.limit_exceeded is True

    # 8. "dedh hazaar rupaye bhej do" = ₹1,500
    r8 = parse_amount("dedh hazaar rupaye bhej do")
    assert r8.status == ParseStatus.SUCCESS
    assert r8.amount == 1500
    assert r8.limit_exceeded is False

    # 9. Mixed numeric and word "1500 rupaye" = ₹1,500
    r9 = parse_amount("1500 rupaye")
    assert r9.status == ParseStatus.SUCCESS
    assert r9.amount == 1500
    assert r9.limit_exceeded is False


def test_stage10_common_asr_and_spelling_variants():
    """Supports diverse phonetic, transcription, and Devanagari variants."""
    # Dedh variants
    assert parse_amount("dhedh hazaar").amount == 1500
    assert parse_amount("derh hazaar").amount == 1500
    assert parse_amount("dedh hazar").amount == 1500
    assert parse_amount("derh hazar").amount == 1500
    assert parse_amount("1.5 hazaar").amount == 1500
    assert parse_amount("1.5 thousand").amount == 1500
    assert parse_amount("डेढ़ हजार").amount == 1500
    assert parse_amount("डेढ़ सौ").amount == 150

    # Dhai variants
    assert parse_amount("dhaai sau").amount == 250
    assert parse_amount("dhai so").amount == 250
    assert parse_amount("dhaai so").amount == 250
    assert parse_amount("dhai hazaar").amount == 2500
    assert parse_amount("dhaai hazar").amount == 2500
    assert parse_amount("ढाई हजार").amount == 2500

    # Sawa variants
    assert parse_amount("sava do lakh").amount == 225000
    assert parse_amount("sawa do lac").amount == 225000
    assert parse_amount("सवा दो लाख").amount == 225000
    assert parse_amount("सवा लाख").amount == 125000
    assert parse_amount("sawa hazaar").amount == 1250

    # Paune variants
    assert parse_amount("paune do hazaar").amount == 1750
    assert parse_amount("paune teen hazaar").amount == 2750
    assert parse_amount("pone teen hazaar").amount == 2750
    assert parse_amount("पौने तीन हज़ार").amount == 2750

    # Saade variants
    assert parse_amount("saade teen hazaar").amount == 3500
    assert parse_amount("sadhe chaar sau").amount == 450
    assert parse_amount("साढ़े चार सौ").amount == 450

    # Devanagari numerals
    assert parse_amount("१५०० रुपये").amount == 1500
    assert parse_amount("५०० रुपये").amount == 500


def test_stage10_disentangle_payee_and_amount(db_session: Session):
    """Verifies that recipient names and payment intent words do not corrupt amount or payee parsing."""
    seed_database(db_session)

    # 1. Amount first, then payee before 'ko'
    q1 = "dedh hazaar rupaye Ramesh ko bhej do"
    amt1 = parse_amount(q1)
    payee1 = PayeeResolver.resolve_for_account(db_session, "acc_priya", q1)
    assert amt1.amount == 1500
    assert payee1.status == PayeeResolutionStatus.MATCHED
    assert payee1.selected_contact.contact_name == "Ramesh Kumar"

    # 2. Payee first before 'ko', then amount
    q2 = "Ramesh ko paanch sau rupaye bhej do"
    amt2 = parse_amount(q2)
    payee2 = PayeeResolver.resolve_for_account(db_session, "acc_priya", q2)
    assert amt2.amount == 500
    assert payee2.status == PayeeResolutionStatus.MATCHED
    assert payee2.selected_contact.contact_name == "Ramesh Kumar"

    # 3. Devanagari amount and payee
    q3 = "डेढ़ हज़ार Ramesh ko bhej do"
    amt3 = parse_amount(q3)
    payee3 = PayeeResolver.resolve_for_account(db_session, "acc_priya", q3)
    assert amt3.amount == 1500
    assert payee3.status == PayeeResolutionStatus.MATCHED
    assert payee3.selected_contact.contact_name == "Ramesh Kumar"

    # 4. English order
    q4 = "send 1500 to Ramesh"
    amt4 = parse_amount(q4)
    payee4 = PayeeResolver.resolve_for_account(db_session, "acc_priya", q4)
    assert amt4.amount == 1500
    assert payee4.status == PayeeResolutionStatus.MATCHED
    assert payee4.selected_contact.contact_name == "Ramesh Kumar"

    # 5. Missing payee phrases must NOT treat 'bhej do' or currency as payee
    q5 = "dedh hazaar rupaye bhej do"
    payee5 = PayeeResolver.resolve_for_account(db_session, "acc_priya", q5)
    assert payee5.status == PayeeResolutionStatus.NOT_FOUND


def test_stage10_independent_secondary_extraction():
    """Ensures ConservativeSecondaryExtractor independently processes transcripts."""
    sec = ConservativeSecondaryExtractor()

    r1 = sec.extract("dedh hazaar")
    assert r1.amount == 1500

    r2 = sec.extract("डेढ़ हज़ार")
    assert r2.amount == 1500

    r3 = sec.extract("dhai sau")
    assert r3.amount == 250

    r4 = sec.extract("ढाई सौ")
    assert r4.amount == 250

    r5 = sec.extract("sawa do lakh")
    assert r5.amount == 225000

    r6 = sec.extract("dedh hazaar rupaye Ramesh ko bhej do")
    assert r6.amount == 1500
    assert r6.payee_name.lower() == "ramesh"

    r7 = sec.extract("1500 rupaye")
    assert r7.amount == 1500
    assert r7.payee_name is None


def test_stage10_cross_check_limit_enforcement(db_session: Session):
    """
    Requirement 7: For 'sawa do lakh', parse as ₹225,000, then reject/hand off
    because it exceeds the ₹10,000 limit. Never truncate or reinterpret as ₹2,250.
    """
    seed_database(db_session)
    engine = CrossCheckEngine()

    # 1. Standalone "sawa do lakh" without payee
    p1 = "sawa do lakh"
    amt1 = parse_amount(p1)
    assert amt1.amount == 225000
    assert amt1.limit_exceeded is True
    payee1 = PayeeResolver.resolve_for_account(db_session, "acc_priya", p1)
    res1 = engine.reconcile(p1, amt1, payee1)
    assert res1.status == CrossCheckStatus.LIMIT_EXCEEDED
    assert res1.recommended_action == "ROUTE_TO_HANDOFF"
    assert res1.can_proceed_to_readback is False

    # 2. "sawa do lakh rupaye"
    p2 = "sawa do lakh rupaye"
    amt2 = parse_amount(p2)
    payee2 = PayeeResolver.resolve_for_account(db_session, "acc_priya", p2)
    res2 = engine.reconcile(p2, amt2, payee2)
    assert res2.status == CrossCheckStatus.LIMIT_EXCEEDED
    assert res2.recommended_action == "ROUTE_TO_HANDOFF"

    # 3. With payee "Ramesh ko sawa do lakh bhej do"
    p3 = "Ramesh ko sawa do lakh bhej do"
    amt3 = parse_amount(p3)
    payee3 = PayeeResolver.resolve_for_account(db_session, "acc_priya", p3)
    res3 = engine.reconcile(p3, amt3, payee3)
    assert res3.status == CrossCheckStatus.LIMIT_EXCEEDED
    assert res3.recommended_action == "ROUTE_TO_HANDOFF"


def test_stage10_cross_check_disagreement_halts_and_clarifies(db_session: Session):
    """If primary and secondary extraction disagree, halt execution and request clarification."""
    seed_database(db_session)

    class MockConflictingSecondary(SecondaryExtractor):
        def extract(self, transcript: str) -> SecondaryExtractionResult:
            # Secondary extracts a conflicting amount of ₹2,000 instead of ₹1,500
            return SecondaryExtractionResult(
                amount=2000,
                payee_name="Ramesh",
                confidence=0.90,
                is_valid=True,
                raw_transcript=transcript,
            )

    engine = CrossCheckEngine(secondary_extractor=MockConflictingSecondary())
    q = "dedh hazaar rupaye Ramesh ko bhej do"
    amt = parse_amount(q)  # Primary extracts 1500
    payee = PayeeResolver.resolve_for_account(db_session, "acc_priya", q)  # Ramesh Kumar

    res = engine.reconcile(q, amt, payee)
    assert res.status == CrossCheckStatus.AMOUNT_MISMATCH
    assert res.is_agreed is False
    assert res.can_proceed_to_readback is False
    assert res.recommended_action == "CLARIFY_AMOUNT"
    assert "Amount disagreement" in res.explanation


def test_stage10_full_turn_direct_hinglish_payment(client: TestClient, db_session: Session):
    """
    Full end-to-end multi-turn flow:
    'dedh hazaar rupaye Ramesh ko bhej do' -> READBACK -> LIVENESS -> STEP_UP_PIN (manual) -> RECEIPT.
    """
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    # Turn 1: Initial Spoken Request
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "dedh hazaar rupaye Ramesh ko bhej do",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["state"] == DialogueState.READBACK.value
    assert d1["readback_card"]["amount_digits"] == 1500
    assert d1["readback_card"]["payee_name"] == "Ramesh Kumar"
    session_id = d1["session_id"]

    # Turn 2: Spoken Confirmation
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Haan confirm karo",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["state"] == DialogueState.LIVENESS.value
    challenge_digits = d2["liveness_challenge"]

    # Turn 3: Spoken Liveness
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

    # Turn 4: Manual PIN submission via Keypad
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
    assert d4["receipt"]["amount"] == 1500.0
    assert d4["receipt"]["payee_name"] == "Ramesh Kumar"


def test_stage10_full_turn_amount_without_payee_clarification(client: TestClient, db_session: Session):
    """
    'dedh hazaar rupaye bhej do' (no payee) -> prompts for beneficiary -> 'Ramesh' -> READBACK -> RECEIPT.
    """
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    # Turn 1: Utterance with amount and intent but no recipient
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "dedh hazaar rupaye bhej do",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["state"] == DialogueState.CLARIFY_PAYEE.value
    assert "beneficiary" in d1["prompt_text"].lower()
    session_id = d1["session_id"]

    # Turn 2: Customer specifies payee name "Ramesh"
    r2 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Ramesh",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["state"] == DialogueState.READBACK.value
    assert d2["readback_card"]["amount_digits"] == 1500
    assert d2["readback_card"]["payee_name"] == "Ramesh Kumar"


def test_stage10_full_turn_sawa_do_lakh_immediate_handoff(client: TestClient, db_session: Session):
    """
    'sawa do lakh' exceeds the ₹10,000 limit -> immediately escalates to HANDOFF.
    Does not ask for confirmation or truncate amount.
    """
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    r = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "sawa do lakh",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == DialogueState.HANDOFF.value
    assert d["handoff_case_id"] is not None
    assert "escalated to a human banking agent" in d["prompt_text"].lower()

    # Verify handoff record in database
    case = db_session.query(HandoffCase).filter(HandoffCase.id == d["handoff_case_id"]).first()
    assert case is not None
    assert case.escalation_reason == "LIMIT_EXCEEDED"
