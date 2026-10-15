"""
Unit tests for deterministic Hinglish and English amount parsing.
Covers the 6 required assignment phrases, numeric INR formats, spelling variants,
ambiguity detection, negative/zero rejection, and transaction limit validation.
"""

import pytest
from app.parsers.number_parser import parse_amount, ParseStatus, DeterministicNumberParser


# =============================================================================
# 1. SIX MANDATORY ASSIGNMENT BENCHMARK PHRASES
# =============================================================================

@pytest.mark.parametrize(
    "phrase,expected_amount",
    [
        ("paanch sau", 500),
        ("dedh hazaar", 1500),
        ("dhai sau", 250),
        ("sawa do lakh", 225000),
        ("paune teen hazaar", 2750),
        ("two thousand paanch sau", 2500),
    ],
)
def test_six_mandatory_benchmark_phrases(phrase: str, expected_amount: int):
    """Verifies exact integer parsing for the 6 core assignment Hinglish phrases."""
    result = parse_amount(phrase)
    assert result.status == ParseStatus.SUCCESS
    assert result.amount == expected_amount
    assert result.currency == "INR"


# =============================================================================
# 2. NUMERIC AND STANDARD INR FORMATS
# =============================================================================

@pytest.mark.parametrize(
    "phrase,expected_amount",
    [
        ("1500 rupees", 1500),
        ("\u20b91,500", 1500),         # ₹1,500
        ("\u20b9 1,500", 1500),        # ₹ 1,500
        ("rs 500", 500),
        ("rs. 500", 500),
        ("500 inr", 500),
        ("send 500 to Ramesh", 500),
        ("Ramesh ko 500 bhejo", 500),
        ("transfer 2500 rupees to Priya", 2500),
        ("1000/-", 1000),
        ("10k", 10000),
    ],
)
def test_numeric_inr_formats(phrase: str, expected_amount: int):
    """Verifies direct numeric formats, currency tags, and transfer phrasings."""
    result = parse_amount(phrase)
    assert result.status == ParseStatus.SUCCESS
    assert result.amount == expected_amount


# =============================================================================
# 3. PHONETIC VARIANTS, EXTRA WHITESPACE, PUNCTUATION & CAPITALIZATION
# =============================================================================

@pytest.mark.parametrize(
    "phrase,expected_amount",
    [
        ("  DEDH   HAZAAR  ", 1500),
        ("dhedh hazaar", 1500),
        ("panch sau", 500),
        ("PAANCH SAU!!", 500),
        ("dhaai sau", 250),
        ("dhaee sau", 250),
        ("sava do lakh", 225000),
        ("sawwa do lakh", 225000),
        ("pone teen hazaar", 2750),
        ("pawne teen hazaar", 2750),
        ("two   thousand    paanch    sau", 2500),
        ("Ramesh ko paanch sau rupaye bhej do.", 500),
        ("Priya ko dedh hazaar transfer karo!", 1500),
    ],
)
def test_spelling_variants_and_formatting(phrase: str, expected_amount: int):
    """Verifies resilience to case variations, whitespace, and documented Hindi transliterations."""
    result = parse_amount(phrase)
    assert result.status == ParseStatus.SUCCESS
    assert result.amount == expected_amount


# =============================================================================
# 4. AMBIGUOUS MULTIPLE AMOUNTS
# =============================================================================

@pytest.mark.parametrize(
    "phrase",
    [
        "send 500 or 1000 rupees",
        "dedh hazaar ya do hazaar",
        "transfer 500 nahi 1000 bhejo",
        "send 500 wait no 600",
    ],
)
def test_ambiguous_multiple_amounts_rejected(phrase: str):
    """
    SAFETY INVARIANT: System must NEVER silently choose between competing amounts.
    Must return AMBIGUOUS status requesting explicit customer clarification.
    """
    result = parse_amount(phrase)
    assert result.status == ParseStatus.AMBIGUOUS
    assert result.amount is None
    assert len(result.candidate_amounts) >= 2


# =============================================================================
# 5. ZERO, NEGATIVE, MISSING, AND UNSUPPORTED PHRASES
# =============================================================================

def test_zero_amount_rejected():
    result = parse_amount("0 rupees")
    assert result.status == ParseStatus.INVALID_VALUE
    assert "greater than zero" in result.explanation.lower()


def test_negative_amount_rejected():
    result = parse_amount("minus 500 rupees")
    assert result.status == ParseStatus.INVALID_VALUE
    assert "cannot be negative" in result.explanation.lower()


def test_hyphenated_negative_amount_rejected():
    result = parse_amount("-500")
    assert result.status == ParseStatus.INVALID_VALUE


def test_empty_and_whitespace_input():
    result = parse_amount("   ")
    assert result.status == ParseStatus.NOT_FOUND


def test_non_financial_text():
    result = parse_amount("Hello Ramesh how are you doing today")
    assert result.status == ParseStatus.NOT_FOUND
    assert result.amount is None


# =============================================================================
# 6. PAYEE NAME NUMBERS & ISOLATION
# =============================================================================

def test_number_in_payee_name_not_confused_with_amount():
    """
    Verifies that numbers embedded in payee names (e.g., 'Ramesh 2') or mobile numbers
    are NOT erroneously extracted as payment amounts.
    """
    res1 = parse_amount("Ramesh 2 ko paanch sau rupaye bhej do")
    assert res1.status == ParseStatus.SUCCESS
    assert res1.amount == 500

    res2 = parse_amount("Send 500 to Ramesh 2")
    assert res2.status == ParseStatus.SUCCESS
    assert res2.amount == 500

    res3 = parse_amount("Call Ramesh at 9876543210 and send 1000 rupees")
    assert res3.status == ParseStatus.SUCCESS
    assert res3.amount == 1000


# =============================================================================
# 7. TRANSACTION LIMIT VALIDATION LAYER (NO SILENT CLAMPING)
# =============================================================================

def test_transaction_limit_exceeded_not_silently_clamped():
    """
    SAFETY INVARIANT: Amounts exceeding the maximum single voice transaction limit
    (₹10,000) are flagged with limit_exceeded=True and NOT silently clamped or altered.
    """
    # 'sawa do lakh' = ₹225,000, which exceeds ₹10,000 limit
    parser = DeterministicNumberParser(max_limit=10000.0)
    result = parser.parse("sawa do lakh")

    assert result.status == ParseStatus.SUCCESS
    # Amount MUST remain exactly 225,000, NEVER clamped to 10,000!
    assert result.amount == 225000
    assert result.is_within_limit is False
    assert result.limit_exceeded is True
    assert "exceeds maximum voice transaction limit" in result.explanation


def test_amount_within_limit_passes_validation():
    parser = DeterministicNumberParser(max_limit=10000.0)
    result = parser.parse("paanch hazaar")  # ₹5,000 <= ₹10,000

    assert result.status == ParseStatus.SUCCESS
    assert result.amount == 5000
    assert result.is_within_limit is True
    assert result.limit_exceeded is False


def test_hindi_colloquial_and_random_numbers():
    """Verifies recognition of 120, 300, 400, 250 and random numbers in Hinglish and Devanagari."""
    test_cases = [
        ("120 rupaye", 120),
        ("300 rupaye", 300),
        ("400 rupaye", 400),
        ("250 rupaye", 250),
        ("ek sau bees rupaye", 120),
        ("sau bees", 120),
        ("teen sau", 300),
        ("chaar sau", 400),
        ("char sau", 400),
        ("dhai sau", 250),
        ("do sau pachaas", 250),
        ("एक सौ बीस रुपये", 120),
        ("तीन सौ", 300),
        ("चार सौ", 400),
        ("दो सौ पचास", 250),
        ("ढाई सौ", 250),
        ("ek sau pachees", 125),
        ("teen sau chaalees", 340),
        ("chaar sau pachaas", 450),
        ("pachattar", 75),
        ("ninyanve", 99),
        ("इक्कीस", 21),
        ("पैंतीस", 35),
    ]
    for phrase, expected in test_cases:
        res = parse_amount(phrase)
        assert res.status == ParseStatus.SUCCESS, f"Failed for '{phrase}': {res.explanation}"
        assert res.amount == expected, f"Failed for '{phrase}': expected {expected}, got {res.amount}"

