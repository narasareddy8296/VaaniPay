"""
Deterministic Confirmation and Cancellation Intent Parser for VaaniPay.
Parses security-critical spoken and typed confirmation/cancellation intents
in English and Hinglish with zero external LLM dependencies.

SAFETY INVARIANTS:
- A payment request itself is NEVER confirmation.
- Silence, ambient noise, and unrelated speech are NEVER confirmation.
- Conflicting tokens (e.g. "yes but cancel", "haan nahi") are strictly AMBIGUOUS.
- Explicit cancellation immediately returns CANCEL.
"""

import re
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ConfirmationIntent(str, Enum):
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"
    AMBIGUOUS = "AMBIGUOUS"
    PAYMENT_REQUEST = "PAYMENT_REQUEST"
    SILENCE = "SILENCE"
    UNKNOWN = "UNKNOWN"


class IntentResult(BaseModel):
    """Result of deterministic intent parsing."""
    model_config = ConfigDict(from_attributes=True)

    intent: ConfirmationIntent
    confidence: float
    raw_text: str
    normalized_text: str
    explanation: str


# Affirmative English and Hinglish patterns
AFFIRMATIVE_EXACT = {
    "yes", "yep", "yeah", "sure", "proceed", "confirm", "confirmed",
    "haan", "han", "ha", "haanji", "haan ji", "sahi hai", "theek hai",
    "bhejo", "bhej do", "kar do", "kardo", "transfer karo", "chalega",
    "yes confirm", "yes please", "please confirm", "confirm payment",
    "haan confirm", "haan confirm karo", "ha confirm karo", "ha confirm",
    "sure confirm", "i confirm", "approved", "approve",
}

# Negative / Cancellation English and Hinglish patterns
NEGATIVE_EXACT = {
    "no", "nope", "cancel", "cancelled", "stop", "abort",
    "nahi", "nahin", "na", "mat bhejo", "ruk jao", "ruko",
    "no cancel", "no please cancel", "please cancel", "cancel payment",
    "nahi cancel", "nahi cancel karo", "nahin cancel karo", "mat karo",
    "do not send", "dont send", "don't send", "roko", "ruko mat bhejo",
}

# Regex tokens for substring detection
AFFIRMATIVE_TOKENS = [
    r"\byes\b", r"\bconfirm\b", r"\bproceed\b", r"\bhaan\b", r"\bhan\b",
    r"\btheek hai\b", r"\bapproved\b", r"\bapprove\b",
]

NEGATIVE_TOKENS = [
    r"\bno\b", r"\bcancel\b", r"\bstop\b", r"\babort\b", r"\bnahi\b", r"\bnahin\b",
    r"\bmat bhejo\b", r"\bruk jao\b", r"\bruko\b", r"\bdo not send\b", r"\bdont send\b",
    r"\bmat karo\b", r"\broko\b",
]

# Patterns indicating an attempt to state a financial payment request instead of confirming
PAYMENT_PATTERNS = [
    r"\b\d+\b",  # Any digits
    r"\b(?:send|transfer|pay|bhejo|bhej do|भेज|भेजो)\s+\d+",
    r"(?:sau|so|hazaar|hazar|lakh|lac|crore|dedh|dhai|sawa|paune|saade|rupaye|rupees|rs|inr|डेढ़|ढाई|सवा|पौने|साढ़े|सौ|हज़ार|हजार|लाख|करोड़|रुपये|रुपए|रु)",
]

AMBIGUOUS_PATTERNS = [
    r"\bmaybe\b", r"\bnot sure\b", r"\bwait\b", r"\bsoch raha\b",
    r"\bya\b", r"\beither\b", r"\bdoubt\b", r"\bconfusion\b",
]


def normalize_intent_text(text: Optional[str]) -> str:
    """Cleans punctuation, trims whitespace, and downcases."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s\-\u0900-\u097F]", " ", text.lower())
    return " ".join(cleaned.split())


def parse_confirmation_intent(raw_text: Optional[str]) -> IntentResult:
    """
    Deterministically evaluates customer utterance for confirmation or cancellation.
    Returns IntentResult with explicit ConfirmationIntent.
    """
    normalized = normalize_intent_text(raw_text)

    # 1. Silence check
    if not normalized:
        return IntentResult(
            intent=ConfirmationIntent.SILENCE,
            confidence=1.0,
            raw_text=raw_text or "",
            normalized_text="",
            explanation="No speech or empty utterance provided.",
        )

    # 2. Exact negative match
    if normalized in NEGATIVE_EXACT:
        return IntentResult(
            intent=ConfirmationIntent.CANCEL,
            confidence=1.0,
            raw_text=raw_text or "",
            normalized_text=normalized,
            explanation=f"Explicit cancellation matched: '{normalized}'.",
        )

    # 3. Exact affirmative match
    if normalized in AFFIRMATIVE_EXACT:
        return IntentResult(
            intent=ConfirmationIntent.CONFIRM,
            confidence=1.0,
            raw_text=raw_text or "",
            normalized_text=normalized,
            explanation=f"Explicit confirmation matched: '{normalized}'.",
        )

    has_payment_indicator = any(re.search(pat, normalized) for pat in PAYMENT_PATTERNS)
    has_neg_token = any(re.search(tok, normalized) for tok in NEGATIVE_TOKENS)
    has_aff_token = (
        any(re.search(tok, normalized) for tok in AFFIRMATIVE_TOKENS)
        or (not has_neg_token and bool(re.search(r"\b(?:bhejo|bhej do|kar do|kardo)\b", normalized)))
    )

    # 4. Payment phrase check (SAFETY INVARIANT: payment request is never confirmation)
    if has_payment_indicator:
        if has_neg_token:
            return IntentResult(
                intent=ConfirmationIntent.CANCEL,
                confidence=0.95,
                raw_text=raw_text or "",
                normalized_text=normalized,
                explanation=f"Cancellation associated with payment phrase: '{normalized}'.",
            )
        return IntentResult(
            intent=ConfirmationIntent.PAYMENT_REQUEST,
            confidence=0.95,
            raw_text=raw_text or "",
            normalized_text=normalized,
            explanation=f"Payment request detected instead of confirmation: '{normalized}'.",
        )

    # 5. Conflicting tokens
    if has_aff_token and has_neg_token:
        return IntentResult(
            intent=ConfirmationIntent.AMBIGUOUS,
            confidence=0.95,
            raw_text=raw_text or "",
            normalized_text=normalized,
            explanation="Conflicting affirmative and negative tokens detected.",
        )

    # 6. Ambiguous patterns
    for pat in AMBIGUOUS_PATTERNS:
        if re.search(pat, normalized):
            return IntentResult(
                intent=ConfirmationIntent.AMBIGUOUS,
                confidence=0.85,
                raw_text=raw_text or "",
                normalized_text=normalized,
                explanation=f"Ambiguity marker matched: '{pat}'.",
            )

    # 7. Token-level detection
    if has_neg_token:
        return IntentResult(
            intent=ConfirmationIntent.CANCEL,
            confidence=0.95,
            raw_text=raw_text or "",
            normalized_text=normalized,
            explanation=f"Cancellation intent identified from: '{normalized}'.",
        )

    if has_aff_token:
        return IntentResult(
            intent=ConfirmationIntent.CONFIRM,
            confidence=0.95,
            raw_text=raw_text or "",
            normalized_text=normalized,
            explanation=f"Confirmation intent identified from: '{normalized}'.",
        )

    # 8. Default
    return IntentResult(
        intent=ConfirmationIntent.UNKNOWN,
        confidence=0.5,
        raw_text=raw_text or "",
        normalized_text=normalized,
        explanation="Speech did not contain recognized confirmation or cancellation keywords.",
    )
