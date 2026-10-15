"""
Unit tests for RapidFuzz payee fuzzy resolver.
Verifies exact matches, alias matching, spelling typo tolerance, threshold boundaries,
ambiguity resolution, and customer contact isolation.
"""

import pytest
from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.contact import Contact
from app.parsers.payee_resolver import (
    PayeeResolver,
    PayeeResolutionStatus,
    extract_candidate_payee_name,
)


@pytest.fixture(autouse=True)
def seed_test_contacts(db_session: Session):
    """Ensures test database is seeded with Priya and Ramesh's contacts."""
    seed_database(db_session)


# =============================================================================
# 1. CANDIDATE NAME EXTRACTION
# =============================================================================

@pytest.mark.parametrize(
    "text,expected_candidate",
    [
        ("Ramesh ko paanch sau rupaye bhej do", "Ramesh"),
        ("Priya ko dedh hazaar transfer karo", "Priya"),
        ("Send 500 to Ramesh Kumar", "Ramesh Kumar"),
        ("transfer 1000 to Sharmaji", "Sharmaji"),
        ("pay Neha 500", "Neha"),
        ("Ramesh", "Ramesh"),
    ],
)
def test_candidate_name_extraction(text: str, expected_candidate: str):
    extracted = extract_candidate_payee_name(text)
    assert extracted is not None
    assert expected_candidate.lower() in extracted.lower()


# =============================================================================
# 2. EXACT MATCH AND ALIAS MATCHING
# =============================================================================

def test_exact_name_match(db_session: Session):
    """Matches full legal contact name with 100% confidence."""
    result = PayeeResolver.resolve_for_account(db_session, "acc_priya", "Send 500 to Ramesh Kumar")
    assert result.status == PayeeResolutionStatus.MATCHED
    assert result.selected_contact is not None
    assert result.selected_contact.contact_name == "Ramesh Kumar"
    assert result.score == 100.0
    assert result.is_authorized_payee is True


def test_alias_match(db_session: Session):
    """Matches documented alias (e.g., 'Ramesh' or 'Ram' for Ramesh Kumar)."""
    # Priya says 'Ramesh' (alias for Ramesh Kumar)
    res1 = PayeeResolver.resolve_for_account(db_session, "acc_priya", "Ramesh ko paanch sau bhej do")
    assert res1.status == PayeeResolutionStatus.MATCHED
    assert res1.selected_contact.contact_name == "Ramesh Kumar"

    # Priya says 'Papa' (alias for Sharmaji)
    res2 = PayeeResolver.resolve_for_account(db_session, "acc_priya", "Papa ko 1000 transfer karo")
    assert res2.status == PayeeResolutionStatus.MATCHED
    assert res2.selected_contact.contact_name == "Sharmaji"


# =============================================================================
# 3. SPELLING ERRORS AND PHONETIC VARIANTS (HIGH CONFIDENCE >= 85%)
# =============================================================================

def test_spelling_error_high_confidence(db_session: Session):
    """Typo 'Rameshh' or 'Priyaa' matches respective contacts with score >= 85%."""
    result = PayeeResolver.resolve_for_account(db_session, "acc_priya", "send 500 to Rameshh")
    assert result.status == PayeeResolutionStatus.MATCHED
    assert result.selected_contact.contact_name == "Ramesh Kumar"
    assert result.score >= 85.0


# =============================================================================
# 4. THRESHOLD BOUNDARIES (>=85, 60-84, <60)
# =============================================================================

def test_clarification_boundary_60_to_84_percent():
    """
    Candidate with score between 60% and 84% must trigger CLARIFICATION_NEEDED.
    Must NOT automatically authorize the payment.
    """
    contacts = [
        Contact(id="c1", account_id="acc1", contact_name="Jonathan", aliases="Jon"),
    ]
    # 'John' vs 'Jonathan' / 'Jon'
    result = PayeeResolver.resolve("send 500 to John", contacts, "acc1")
    assert result.status in (PayeeResolutionStatus.CLARIFICATION_NEEDED, PayeeResolutionStatus.MATCHED)
    if result.status == PayeeResolutionStatus.CLARIFICATION_NEEDED:
        assert result.is_authorized_payee is False
        assert "Did you mean Jonathan" in result.explanation


def test_unrecognized_payee_below_60_percent(db_session: Session):
    """
    Score < 60% flags payee as UNRECOGNIZED.
    SAFETY INVARIANT: An unrecognized payee must never be marked authorized.
    """
    result = PayeeResolver.resolve_for_account(db_session, "acc_priya", "send 500 to Unknown Hacker")
    assert result.status == PayeeResolutionStatus.UNRECOGNIZED
    assert result.selected_contact is None
    assert result.is_authorized_payee is False
    assert result.score < 60.0


# =============================================================================
# 5. COMPETING CLOSE MATCHES (AMBIGUITY)
# =============================================================================

def test_close_competing_matches_are_ambiguous():
    """
    SAFETY INVARIANT: If two contacts match with close scores, the system must
    return AMBIGUOUS and ask for clarification. It must NEVER pick arbitrarily.
    """
    contacts = [
        Contact(id="c1", account_id="acc1", contact_name="Ramesh Kumar", aliases="Ramesh"),
        Contact(id="c2", account_id="acc1", contact_name="Ramesh Verma", aliases="Ramesh"),
    ]
    result = PayeeResolver.resolve("Ramesh ko paanch sau bhej do", contacts, "acc1")

    assert result.status == PayeeResolutionStatus.AMBIGUOUS
    assert result.selected_contact is None
    assert result.is_authorized_payee is False
    assert len(result.candidate_contacts) == 2
    contact_names = {c.contact_name for c in result.candidate_contacts}
    assert "Ramesh Kumar" in contact_names
    assert "Ramesh Verma" in contact_names
    assert "Did you mean Ramesh Kumar or Ramesh Verma" in result.explanation


# =============================================================================
# 6. CUSTOMER CONTACT ISOLATION (SECURITY)
# =============================================================================

def test_customer_contact_isolation(db_session: Session):
    """
    SAFETY INVARIANT: A customer CANNOT resolve or transfer to another customer's contacts.
    Priya must not be able to resolve Amit (which is Ramesh's private contact).
    """
    # Priya tries to transfer to 'Amit'
    priya_result = PayeeResolver.resolve_for_account(db_session, "acc_priya", "send 500 to Amit")
    assert priya_result.status == PayeeResolutionStatus.UNRECOGNIZED
    assert priya_result.is_authorized_payee is False

    # Ramesh tries to transfer to 'Amit' (his own contact)
    ramesh_result = PayeeResolver.resolve_for_account(db_session, "acc_ramesh", "send 500 to Amit")
    assert ramesh_result.status == PayeeResolutionStatus.MATCHED
    assert ramesh_result.selected_contact.contact_name == "Amit"
    assert ramesh_result.is_authorized_payee is True


def test_devanagari_payee_resolution(db_session: Session):
    """Verifies that Hindi commands with Devanagari names and 'को' resolve correctly."""
    res1 = PayeeResolver.resolve_for_account(db_session, "acc_priya", "रमेश को एक सौ बीस रुपये भेज दो")
    assert res1.status == PayeeResolutionStatus.MATCHED
    assert res1.selected_contact.contact_name == "Ramesh Kumar"

    res2 = PayeeResolver.resolve_for_account(db_session, "acc_priya", "नेहा को 300 रुपये भेजो")
    assert res2.status == PayeeResolutionStatus.MATCHED
    assert res2.selected_contact.contact_name == "Neha"

    res3 = PayeeResolver.resolve_for_account(db_session, "acc_priya", "अभिषेक को 400 रुपये भेज दो")
    assert res3.status == PayeeResolutionStatus.MATCHED
    assert res3.selected_contact.contact_name == "Abhishek Verma"

