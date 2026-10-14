"""
Stage 12 Tests: Robust Natural Hinglish Speech Understanding for VaaniPay.
Verifies:
1. Natural Hinglish amount recognition variants ("sava do lakh", "sawa 2 lakh", "sava do laakh rupaye",
   "dedh hazaar", "dhai sau", "paanch sau rupaye bhej do", "1500 rupaye Abhishek ko bhejo").
2. Recipient recognition against customer's saved contacts, aliases, and typo tolerance.
3. Safe transcript repair stage: preserves raw transcript while normalizing ASR errors and spacing.
4. Independent dual-engine extraction and targeted clarification on disagreement.
5. Strict limit enforcement: ₹225,000 parsed correctly, blocked by ₹10,000 limit, and clearly explained.
6. Full turn dialogue progression with clarification, confirmation, liveness, and manual PIN.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.cross_check import (
    CrossCheckEngine,
    CrossCheckStatus,
    SecondaryExtractor,
    SecondaryExtractionResult,
    ConservativeSecondaryExtractor,
)
from app.db.seed import seed_database
from app.models.account import Account
from app.models.contact import Contact
from app.models.handoff import HandoffCase
from app.models.session import PaymentSession
from app.parsers.number_parser import DeterministicNumberParser, ParseStatus, parse_amount
from app.parsers.payee_resolver import PayeeResolver, PayeeResolutionStatus
from app.parsers.transcript_repair import TranscriptRepairService
from app.schemas.turn import DialogueAction, DialogueState
from tests.conftest import make_auth_headers


def test_stage12_exact_required_phrases(db_session: Session):
    """
    Requirement 1: Support all required spoken Hinglish amount phrases and numeric combinations.
    Expected values:
    - paanch sau = ₹500
    - dhai sau = ₹250
    - dedh hazaar = ₹1,500
    - sawa do lakh / sava do lakh / sava do laakh = ₹225,000
    """
    seed_database(db_session)
    parser = DeterministicNumberParser()
    sec = ConservativeSecondaryExtractor()

    test_cases = [
        ("Abhishek ko sava do lakh bhejo", 225000, True, "Abhishek"),
        ("Abhishek ko sawa 2 lakh bhejo", 225000, True, "Abhishek"),
        ("Abhishek ko sava do laakh rupaye bhej do", 225000, True, "Abhishek"),
        ("Abhishek ko dedh hazaar bhejo", 1500, False, "Abhishek"),
        ("Abhishek ko dhai sau bhejo", 250, False, "Abhishek"),
        ("Abhishek ko paanch sau rupaye bhej do", 500, False, "Abhishek"),
        ("1500 rupaye Abhishek ko bhejo", 1500, False, "Abhishek"),
    ]

    for phrase, expected_amount, should_exceed_limit, expected_payee in test_cases:
        # Primary parser
        p_res = parser.parse(phrase)
        assert p_res.status == ParseStatus.SUCCESS, f"Failed on '{phrase}': {p_res.explanation}"
        assert p_res.amount == expected_amount, f"Amount mismatch for '{phrase}': {p_res.amount} != {expected_amount}"
        assert p_res.limit_exceeded is should_exceed_limit, f"Limit exceeded flag wrong for '{phrase}'"

        # Secondary independent extractor
        s_res = sec.extract(phrase)
        assert s_res.is_valid is True, f"Secondary extractor failed on '{phrase}'"
        assert s_res.amount == expected_amount, f"Secondary amount mismatch for '{phrase}': {s_res.amount}"
        assert s_res.payee_name is not None and expected_payee.lower() in s_res.payee_name.lower()

        # Payee Resolver
        payee_res = PayeeResolver.resolve_for_account(db_session, "acc_priya", phrase)
        assert payee_res.status == PayeeResolutionStatus.MATCHED
        assert payee_res.selected_contact is not None
        assert payee_res.selected_contact.contact_name == "Abhishek Verma"


def test_stage12_common_asr_misspellings_and_spacing(db_session: Session):
    """
    Requirement 1 & 2: Support minor spelling variations and ASR token spacing merges.
    """
    seed_database(db_session)
    parser = DeterministicNumberParser()

    # Spacing merges
    assert parser.parse("Abhishek ko sawa2 lakh bhejo").amount == 225000
    assert parser.parse("Abhishek ko dedhhazaar bhejo").amount == 1500
    assert parser.parse("Abhishek ko dhaisau bhejo").amount == 250
    assert parser.parse("Abhishek ko paanchsau rupaye bhej do").amount == 500

    # Phonetic recipient spelling variations
    res1 = PayeeResolver.resolve_for_account(db_session, "acc_priya", "Abhishekk ko 500 bhej do")
    assert res1.status == PayeeResolutionStatus.MATCHED
    assert res1.selected_contact.contact_name == "Abhishek Verma"

    res2 = PayeeResolver.resolve_for_account(db_session, "acc_priya", "Abishek ko dedh hazaar bhejo")
    assert res2.status == PayeeResolutionStatus.MATCHED
    assert res2.selected_contact.contact_name == "Abhishek Verma"


def test_stage12_safe_transcript_repair_invariants():
    """
    Requirement 3: Safe transcript-repair stage.
    Preserves raw transcript untouched, applies deterministic dictionary for known numbers/spacing,
    and NEVER invents numbers or amounts for uncertain gibberish.
    """
    # 1. Spacing repair
    t1, rep1 = TranscriptRepairService.repair("sawa2lakh")
    assert t1 == "sawa 2 lakh"
    assert len(rep1) > 0

    # 2. Phonetic ASR repair
    t2, rep2 = TranscriptRepairService.repair("Abhishek ko sava do laakh rupaye bhej do")
    assert "lakh" in t2
    assert "laakh" not in t2

    # 3. Gibberish / non-number input must NOT invent numbers
    t3, rep3 = TranscriptRepairService.repair("kuch bhi transfer kar dena")
    assert parse_amount(t3).status == ParseStatus.NOT_FOUND

    t4, rep4 = TranscriptRepairService.repair("unknown person ko bhej do")
    assert parse_amount(t4).status == ParseStatus.NOT_FOUND


def test_stage12_ambiguous_recipients_clarification(db_session: Session):
    """
    Requirement 2 & 4: If multiple contacts match closely, ask customer which contact they mean.
    Do not guess or route to a default recipient.
    """
    seed_database(db_session)

    # Add a second contact with competing name "Abhishek Sharma"
    competing_contact = Contact(
        id="cnt_priya_abhishek_2",
        account_id="acc_priya",
        contact_name="Abhishek Sharma",
        aliases="Abhishek,Sharma",
        phone_number="+919876543216",
        is_frequent=False,
    )
    db_session.add(competing_contact)
    db_session.commit()

    # Query with ambiguous name "Abhishek"
    query = "Abhishek ko 500 bhejo"
    res = PayeeResolver.resolve_for_account(db_session, "acc_priya", query)
    assert res.status == PayeeResolutionStatus.AMBIGUOUS
    assert len(res.candidate_contacts) >= 2
    assert "Did you mean" in res.explanation
    assert "Abhishek Verma" in res.explanation
    assert "Abhishek Sharma" in res.explanation


def test_stage12_extraction_disagreement_halts_and_clarifies(db_session: Session):
    """
    Requirement 4: If extraction methods disagree, ask targeted clarification:
    'Did you mean ₹1,500 or another amount?' Do not execute payment.
    """
    seed_database(db_session)

    class ConflictingSecondary(SecondaryExtractor):
        def extract(self, transcript: str) -> SecondaryExtractionResult:
            return SecondaryExtractionResult(
                amount=2000,  # Disagrees with primary parser (1500)
                payee_name="Abhishek Verma",
                confidence=0.88,
                is_valid=True,
                raw_transcript=transcript,
            )

    engine = CrossCheckEngine(secondary_extractor=ConflictingSecondary())
    phrase = "Abhishek ko dedh hazaar bhejo"
    amt_res = parse_amount(phrase)
    payee_res = PayeeResolver.resolve_for_account(db_session, "acc_priya", phrase)

    res = engine.reconcile(phrase, amt_res, payee_res)
    assert res.status == CrossCheckStatus.AMOUNT_MISMATCH
    assert res.can_proceed_to_readback is False
    assert res.recommended_action == "CLARIFY_AMOUNT"
    assert "Did you mean ₹1,500 or another amount?" in res.explanation


def test_stage12_full_turn_sawa_do_lakh_limit_blocked(client: TestClient, db_session: Session):
    """
    Requirement 5: 'sawa do lakh' must resolve to ₹225,000, block payment exceeding ₹10,000,
    clearly explain the limit, and not ask for PIN.
    """
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    r = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Abhishek ko sava do lakh bhejo",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == DialogueState.HANDOFF.value
    assert data["handoff_case_id"] is not None
    # Must clearly explain the ₹10,000 limit and mention escalation
    assert "exceeds" in data["prompt_text"].lower()
    assert "10,000" in data["prompt_text"] or "10000" in data["prompt_text"]
    assert "225,000" in data["prompt_text"] or "225000" in data["prompt_text"]

    # Verify handoff record in database
    case = db_session.query(HandoffCase).filter(HandoffCase.id == data["handoff_case_id"]).first()
    assert case is not None
    assert case.escalation_reason == "LIMIT_EXCEEDED"


def test_stage12_full_turn_valid_payment_to_abhishek(client: TestClient, db_session: Session):
    """
    Requirement 1, 5 & 6: 'Abhishek ko dedh hazaar bhejo' parses to ₹1,500 to Abhishek Verma,
    advances to READBACK, completes liveness, enters manual PIN, and moves double-entry ledger.
    """
    seed_database(db_session)
    headers = make_auth_headers("acc_priya")

    priya = db_session.query(Account).filter(Account.id == "acc_priya").first()
    abhishek = db_session.query(Account).filter(Account.id == "acc_abhishek").first()
    start_priya_bal = priya.balance
    start_abhi_bal = abhishek.balance

    # 1. Turn 1: Spoken command
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_TRANSCRIPT.value,
            "transcript": "Abhishek ko dedh hazaar bhejo",
            "channel": "VOICE",
        },
        headers=headers,
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["state"] == DialogueState.READBACK.value
    assert d1["readback_card"]["amount_digits"] == 1500
    assert d1["readback_card"]["payee_name"] == "Abhishek Verma"
    session_id = d1["session_id"]

    # 2. Turn 2: Confirm Readback
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
    d2 = r2.json()
    assert d2["state"] == DialogueState.LIVENESS.value
    challenge = d2["liveness_challenge"]

    # 3. Turn 3: Typed fallback for liveness (triggers mandatory PIN step-up)
    r3 = client.post(
        "/api/v1/turn",
        json={
            "session_id": session_id,
            "account_id": "acc_priya",
            "action": DialogueAction.SUBMIT_LIVENESS.value,
            "liveness_response": challenge,
            "channel": "TYPED",
        },
        headers=headers,
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["state"] == DialogueState.STEP_UP_PIN.value
    assert d3["requires_pin"] is True

    # 4. Turn 4: Submit 4-digit manual PIN
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
    assert d4["receipt"]["amount"] == 1500.0
    assert d4["receipt"]["payee_name"] == "Abhishek Verma"

    # Verify atomic balance update in database
    db_session.refresh(priya)
    db_session.refresh(abhishek)
    assert float(priya.balance) == float(start_priya_bal) - 1500.0
    assert float(abhishek.balance) == float(start_abhi_bal) + 1500.0
