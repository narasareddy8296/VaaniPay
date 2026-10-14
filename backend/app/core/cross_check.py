"""
Independent multi-method cross-checking engine for VaaniPay.
Reconciles results between the deterministic parser and a secondary extractor.
Guarantees:
- Strict consensus required before proceeding to read-back.
- Discrepancies halt execution and request clarification or handoff.
- Spoken prompt-injections are treated strictly as untrusted data strings.
- Zero payment or ledger execution occurs in this module.
"""

import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz
from app.core.config import get_settings
from app.parsers.number_parser import ParsedAmountResult, ParseStatus
from app.parsers.payee_resolver import PayeeResolutionResult, PayeeResolutionStatus


class CrossCheckStatus(str, Enum):
    AGREED = "AGREED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    PAYEE_MISMATCH = "PAYEE_MISMATCH"
    INCOMPLETE_EXTRACTION = "INCOMPLETE_EXTRACTION"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    AMBIGUOUS_PAYEE = "AMBIGUOUS_PAYEE"
    SUSPICIOUS_PROMPT_INJECTION = "SUSPICIOUS_PROMPT_INJECTION"
    REJECTED = "REJECTED"


class SecondaryExtractionResult(BaseModel):
    """Structured candidate form produced by the secondary extractor."""
    model_config = ConfigDict(from_attributes=True)

    amount: Optional[int] = None
    payee_name: Optional[str] = None
    confidence: float = 0.0
    is_valid: bool = False
    raw_transcript: str = ""
    method_name: str = "conservative_rules"
    error: Optional[str] = None


class CrossCheckResult(BaseModel):
    """Reconciliation decision output."""
    model_config = ConfigDict(from_attributes=True)

    status: CrossCheckStatus
    is_agreed: bool = False
    can_proceed_to_readback: bool = False
    final_amount: Optional[int] = None
    final_payee_name: Optional[str] = None
    final_payee_id: Optional[str] = None
    primary_amount: Optional[int] = None
    secondary_amount: Optional[int] = None
    primary_payee: Optional[str] = None
    secondary_payee: Optional[str] = None
    recommended_action: str
    explanation: str
    suspicious_injection_detected: bool = False
    audit_context: Dict[str, Any] = {}


# =============================================================================
# SECONDARY EXTRACTOR INTERFACE & CONSERVATIVE IMPLEMENTATION
# =============================================================================

class SecondaryExtractor(ABC):
    """Abstract interface for independent extraction methods (rules or LLMs)."""

    @abstractmethod
    def extract(self, transcript: str) -> SecondaryExtractionResult:
        """Extracts candidate amount and payee independently."""
        pass


SEC_MULT_MAP = {
    "sau": 100, "so": 100, "sou": 100, "hundred": 100, "सौ": 100,
    "hazaar": 1000, "hazar": 1000, "hajar": 1000, "hazaarr": 1000, "hazarr": 1000, "thousand": 1000, "k": 1000, "हज़ार": 1000, "हजार": 1000,
    "lakh": 100000, "laakh": 100000, "laak": 100000, "lac": 100000, "lakhs": 100000, "laakhs": 100000, "lacs": 100000, "लाख": 100000,
    "crore": 10000000, "cr": 10000000, "crores": 10000000, "करोड़": 10000000,
}

SEC_WORD_MAP = {
    "shunya": 0, "zero": 0, "शून्य": 0,
    "ek": 1, "ik": 1, "one": 1, "एक": 1,
    "do": 2, "two": 2, "दो": 2,
    "teen": 3, "tin": 3, "three": 3, "तीन": 3,
    "chaar": 4, "char": 4, "four": 4, "चार": 4,
    "paanch": 5, "panch": 5, "five": 5, "पाँच": 5, "पांच": 5,
    "chhah": 6, "che": 6, "chhe": 6, "six": 6, "छह": 6,
    "saat": 7, "sat": 7, "seven": 7, "सात": 7,
    "aath": 8, "ath": 8, "eight": 8, "आठ": 8,
    "nau": 9, "no": 9, "nine": 9, "नौ": 9,
    "das": 10, "dus": 10, "ten": 10, "दस": 10,
    "bees": 20, "twenty": 20, "बीस": 20,
    "pachees": 25, "twenty-five": 25, "पच्चीस": 25,
    "tees": 30, "thirty": 30, "तीस": 30,
    "chaalees": 40, "forty": 40, "चालीस": 40,
    "pachaas": 50, "fifty": 50, "पचास": 50,
}

SEC_MULT_RE = r'(?:sau|so|sou|hundred|hazaar|hazar|hajar|hazaarr|hazarr|thousand|lakh|laakh|laak|lac|lakhs|laakhs|lacs|crore|crores|cr|k|सौ|हज़ार|हजार|लाख|करोड़)'

SEC_NOISE_RE = re.compile(
    r'\b(?:dedh|dhedh|derh|deydh|dadh|dhai|dhaai|dhaee|adhai|sawa|sava|sawwa|paune|pone|saade|sadhe|sade|'
    r'डेढ़|डेढ|ढाई|ढा़ई|सवा|पौने|साढ़े|साढे|'
    r'sau|so|sou|hundred|hazaar|hazar|hajar|hazaarr|hazarr|thousand|lakh|laakh|laak|lac|lakhs|laakhs|lacs|crore|crores|cr|k|'
    r'सौ|हज़ार|हजार|लाख|करोड़|'
    r'shunya|zero|ek|ik|one|do|two|teen|tin|three|chaar|char|four|paanch|panch|five|chhah|che|chhe|six|saat|sat|seven|aath|ath|eight|nau|no|nine|das|dus|ten|'
    r'शून्य|एक|दो|तीन|चार|पाँच|पांच|छह|सात|आठ|नौ|दस|'
    r'bees|pachees|tees|chaalees|pachaas|saath|sattar|assi|nabbe|बीस|पच्चीस|तीस|चालीस|पचास|'
    r'rupees|rupaye|rupya|rupee|rs|inr|/-|रुपये|रुपए|रुपया|रु|'
    r'send|pay|transfer|bhej|bhejo|de|do|karo|kardo|kar|kripya|please)\b|\b\d+(?:\.\d+)?\b',
    re.IGNORECASE,
)


def _strip_secondary_noise(s: str) -> str:
    cleaned = SEC_NOISE_RE.sub(' ', s)
    return ' '.join(cleaned.split())


class ConservativeSecondaryExtractor(SecondaryExtractor):
    """
    Independent conservative secondary extractor for offline execution.
    Uses distinct regular expressions and token isolation separate from the primary parser.
    """

    def extract(self, transcript: str) -> SecondaryExtractionResult:
        if not transcript or not transcript.strip():
            return SecondaryExtractionResult(
                is_valid=False,
                raw_transcript="",
                error="Empty transcript",
            )

        from app.parsers.transcript_repair import TranscriptRepairService
        repaired, _ = TranscriptRepairService.repair(transcript)
        text = repaired.strip().lower()

        # Check for injection attempts in secondary layer
        is_injection = bool(re.search(
            r'\b(?:ignore\s+(?:all\s+)?(?:instructions?|prompts?|rules?)|override\s+system|jailbreak|bypass)\b',
            text,
            re.IGNORECASE,
        ))

        extracted_amount: Optional[int] = None
        extracted_payee: Optional[str] = None

        # 1. Independent amount extraction
        t = text.translate(str.maketrans('०१२३४५६७८९', '0123456789'))
        t = re.sub(r'[^\w\s\-\.\u0900-\u097F]', ' ', t)
        t = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', t)
        t = ' '.join(t.split())

        # Fractional extraction
        m_dedh = re.search(r'(?:^|\s)(?:dedh|dhedh|derh|deydh|डेढ़|डेढ)\s+(' + SEC_MULT_RE + r')(?:\s|$|[^\w\u0900-\u097F])', t)
        if m_dedh:
            extracted_amount = int(1.5 * SEC_MULT_MAP.get(m_dedh.group(1), 1000))
        else:
            m_dhai = re.search(r'(?:^|\s)(?:dhai|dhaai|dhaee|adhai|ढाई|ढा़ई)\s+(' + SEC_MULT_RE + r')(?:\s|$|[^\w\u0900-\u097F])', t)
            if m_dhai:
                extracted_amount = int(2.5 * SEC_MULT_MAP.get(m_dhai.group(1), 100))
            else:
                m_sawa = re.search(r'(?:^|\s)(?:sawa|sava|सवा)\s+([\w\u0900-\u097F]+)\s+(' + SEC_MULT_RE + r')(?:\s|$|[^\w\u0900-\u097F])', t)
                if m_sawa:
                    val = SEC_WORD_MAP.get(m_sawa.group(1)) or (int(m_sawa.group(1)) if m_sawa.group(1).isdigit() else None)
                    mult = SEC_MULT_MAP.get(m_sawa.group(2))
                    if val is not None and mult is not None:
                        extracted_amount = int((val + 0.25) * mult)
                else:
                    m_sawa_std = re.search(r'(?:^|\s)(?:sawa|sava|सवा)\s+(' + SEC_MULT_RE + r')(?:\s|$|[^\w\u0900-\u097F])', t)
                    if m_sawa_std:
                        mult = SEC_MULT_MAP.get(m_sawa_std.group(1))
                        if mult is not None:
                            extracted_amount = int(1.25 * mult)
                    else:
                        m_paune = re.search(r'(?:^|\s)(?:paune|pone|पौने)\s+([\w\u0900-\u097F]+)\s+(' + SEC_MULT_RE + r')(?:\s|$|[^\w\u0900-\u097F])', t)
                        if m_paune:
                            val = SEC_WORD_MAP.get(m_paune.group(1)) or (int(m_paune.group(1)) if m_paune.group(1).isdigit() else None)
                            mult = SEC_MULT_MAP.get(m_paune.group(2))
                            if val is not None and mult is not None:
                                extracted_amount = int((val - 0.25) * mult)
                        else:
                            m_saade = re.search(r'(?:^|\s)(?:saade|sadhe|साढ़े)\s+([\w\u0900-\u097F]+)\s+(' + SEC_MULT_RE + r')(?:\s|$|[^\w\u0900-\u097F])', t)
                            if m_saade:
                                val = SEC_WORD_MAP.get(m_saade.group(1)) or (int(m_saade.group(1)) if m_saade.group(1).isdigit() else None)
                                mult = SEC_MULT_MAP.get(m_saade.group(2))
                                if val is not None and mult is not None:
                                    extracted_amount = int((val + 0.5) * mult)

        # Word multiplier combinations (e.g. 'paanch sau', 'do hazaar')
        if extracted_amount is None:
            m_words = re.search(r'\b(' + '|'.join(SEC_WORD_MAP.keys()) + r')\s+(' + SEC_MULT_RE + r')\b', t)
            if m_words:
                extracted_amount = int(SEC_WORD_MAP[m_words.group(1)] * SEC_MULT_MAP[m_words.group(2)])

        # Digits + optional multiplier (e.g. '1500 rupaye', '1.5 hazaar', 'send 500')
        if extracted_amount is None:
            m_amt = re.search(
                r'(?:(?:₹|rs\.?|inr)\s*)?(\b\d+(?:\.\d+)?)\s*(' + SEC_MULT_RE + r')?(?:\s*(?:rupees|rupaye|rupya|rs|inr|/-|रुपये|रुपए|रु))?',
                t,
            )
            if m_amt and m_amt.group(1):
                num = float(m_amt.group(1))
                mult = SEC_MULT_MAP.get(m_amt.group(2), 1) if m_amt.group(2) else 1
                extracted_amount = int(num * mult)

        # 2. Independent payee extraction
        m_ko = re.search(r'^(?:please\s+|kripya\s+)?(.*?)\s+ko\b', text, re.IGNORECASE)
        if m_ko:
            cand = _strip_secondary_noise(m_ko.group(1))
            if cand:
                extracted_payee = cand
        else:
            m_to = re.search(r'\bto\s+([a-zA-Z\s\.\'\u0900-\u097F-]+?)(?:\s+(?:rupees|rupaye|inr|rs|\d|immediately|now))?$', text, re.IGNORECASE)
            if m_to:
                cand = _strip_secondary_noise(m_to.group(1))
                if cand:
                    extracted_payee = cand
            else:
                m_pay = re.search(r'\b(?:pay|send|transfer)\s+([a-zA-Z\s\.\'\u0900-\u097F-]+?)\s+(?:\d+|paanch|dedh|dhai|two|one|three)', text, re.IGNORECASE)
                if m_pay:
                    cand = _strip_secondary_noise(m_pay.group(1))
                    if cand:
                        extracted_payee = cand
                else:
                    cand = _strip_secondary_noise(text)
                    if cand and len(cand.split()) <= 4:
                        extracted_payee = cand

        is_valid = bool(extracted_amount is not None or extracted_payee is not None)

        return SecondaryExtractionResult(
            amount=extracted_amount,
            payee_name=extracted_payee,
            confidence=0.90 if is_valid and not is_injection else 0.30,
            is_valid=is_valid,
            raw_transcript=transcript,
            method_name="conservative_rules",
            error="Prompt injection detected" if is_injection else None,
        )


# =============================================================================
# RECONCILIATION & CONSENSUS CONTROLLER
# =============================================================================

class CrossCheckEngine:
    """
    Reconciles primary deterministic parsing with secondary extraction.
    Enforces two-way consensus and prompt-injection resistance.
    """

    def __init__(self, secondary_extractor: Optional[SecondaryExtractor] = None):
        self.secondary_extractor = secondary_extractor or ConservativeSecondaryExtractor()
        self.settings = get_settings()

    def reconcile(
        self,
        transcript: str,
        primary_amount_result: ParsedAmountResult,
        primary_payee_result: PayeeResolutionResult,
    ) -> CrossCheckResult:
        """
        Reconciles the primary and secondary results.
        Returns a CrossCheckResult declaring whether the payment may proceed to read-back.
        """
        # 1. Spoken Prompt Injection Guard
        # Transcripts are treated strictly as untrusted data strings.
        injection_pattern = re.compile(
            r'\b(?:ignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions?|prompts?|rules?|safeguards?)|'
            r'system\s+(?:override|prompt)|'
            r'jailbreak|bypass\s+security|'
            r'drop\s+table|elevate\s+privileges)\b',
            re.IGNORECASE,
        )
        is_injection = bool(injection_pattern.search(transcript))
        if is_injection:
            return CrossCheckResult(
                status=CrossCheckStatus.SUSPICIOUS_PROMPT_INJECTION,
                is_agreed=False,
                can_proceed_to_readback=False,
                recommended_action="ROUTE_TO_HANDOFF",
                explanation=(
                    "Suspicious instruction override detected in speech data. "
                    "Treated strictly as untrusted data; zero execution permitted."
                ),
                suspicious_injection_detected=True,
                audit_context={"transcript": transcript, "flag": "PROMPT_INJECTION_DETECTED"},
            )

        # 2. Check for primary parsing errors
        if primary_amount_result.status != ParseStatus.SUCCESS:
            return CrossCheckResult(
                status=CrossCheckStatus.INCOMPLETE_EXTRACTION,
                is_agreed=False,
                can_proceed_to_readback=False,
                primary_amount=primary_amount_result.amount,
                recommended_action="CLARIFY_AMOUNT",
                explanation=f"Primary amount parser incomplete: {primary_amount_result.explanation}",
                audit_context={"amount_status": primary_amount_result.status.value},
            )

        # 3. Check transaction limit IMMEDIATELY
        # Critical Requirement: If amount exceeds limit (e.g. ₹225,000 for "sawa do lakh"),
        # reject or hand off immediately without waiting for a payee.
        if primary_amount_result.limit_exceeded or (primary_amount_result.amount and primary_amount_result.amount > self.settings.MAX_VOICE_TX_AMOUNT):
            return CrossCheckResult(
                status=CrossCheckStatus.LIMIT_EXCEEDED,
                is_agreed=False,
                can_proceed_to_readback=False,
                primary_amount=primary_amount_result.amount,
                primary_payee=primary_payee_result.selected_contact.contact_name if primary_payee_result.selected_contact else None,
                recommended_action="ROUTE_TO_HANDOFF",
                explanation=(
                    f"The requested amount of ₹{primary_amount_result.amount:,} exceeds the single transaction "
                    f"limit of ₹{int(self.settings.MAX_VOICE_TX_AMOUNT):,}. Your payment has been escalated to a human banking agent for manual review."
                ),
                audit_context={"amount": primary_amount_result.amount, "limit": self.settings.MAX_VOICE_TX_AMOUNT},
            )

        # 4. Check for payee resolution errors or missing payee
        if primary_payee_result.status == PayeeResolutionStatus.AMBIGUOUS:
            return CrossCheckResult(
                status=CrossCheckStatus.AMBIGUOUS_PAYEE,
                is_agreed=False,
                can_proceed_to_readback=False,
                primary_amount=primary_amount_result.amount,
                recommended_action="CLARIFY_PAYEE",
                explanation=primary_payee_result.explanation,
                audit_context={"candidates": [c.contact_name for c in primary_payee_result.candidate_contacts]},
            )

        if primary_payee_result.status not in (PayeeResolutionStatus.MATCHED, PayeeResolutionStatus.CLARIFICATION_NEEDED):
            return CrossCheckResult(
                status=CrossCheckStatus.INCOMPLETE_EXTRACTION,
                is_agreed=False,
                can_proceed_to_readback=False,
                primary_amount=primary_amount_result.amount,
                recommended_action="CLARIFY_PAYEE",
                explanation=primary_payee_result.explanation,
                audit_context={"payee_status": primary_payee_result.status.value},
            )

        # 4. Invoke Secondary Extractor
        secondary = self.secondary_extractor.extract(transcript)

        p_amount = primary_amount_result.amount
        s_amount = secondary.amount

        p_contact = primary_payee_result.selected_contact
        p_payee_name = p_contact.contact_name if p_contact else None
        s_payee_name = secondary.payee_name

        # 5. Independent Amount Comparison
        amounts_match = (p_amount is not None and s_amount is not None and p_amount == s_amount)
        if not amounts_match:
            clarify_phrase = f"₹{p_amount:,}" if p_amount else "the amount"
            return CrossCheckResult(
                status=CrossCheckStatus.AMOUNT_MISMATCH,
                is_agreed=False,
                can_proceed_to_readback=False,
                primary_amount=p_amount,
                secondary_amount=s_amount,
                primary_payee=p_payee_name,
                secondary_payee=s_payee_name,
                recommended_action="CLARIFY_AMOUNT",
                explanation=f"Amount disagreement between extraction methods. Did you mean {clarify_phrase} or another amount?",
                audit_context={"primary_amount": p_amount, "secondary_amount": s_amount},
            )

        # 6. Independent Payee Comparison
        payees_match = False
        if p_payee_name and s_payee_name:
            # Fuzzy comparison between resolved contact name and secondary raw payee extraction
            similarity = fuzz.token_set_ratio(p_payee_name.lower(), s_payee_name.lower())
            payees_match = similarity >= 80.0

        if not payees_match:
            return CrossCheckResult(
                status=CrossCheckStatus.PAYEE_MISMATCH,
                is_agreed=False,
                can_proceed_to_readback=False,
                primary_amount=p_amount,
                secondary_amount=s_amount,
                primary_payee=p_payee_name,
                secondary_payee=s_payee_name,
                recommended_action="CLARIFY_PAYEE",
                explanation=(
                    f"Payee disagreement: Primary resolved to '{p_payee_name}', "
                    f"but secondary method extracted '{s_payee_name}'. Clarification required."
                ),
                audit_context={"primary_payee": p_payee_name, "secondary_payee": s_payee_name},
            )

        # 7. Exact Agreement Reached
        return CrossCheckResult(
            status=CrossCheckStatus.AGREED,
            is_agreed=True,
            can_proceed_to_readback=True,
            final_amount=p_amount,
            final_payee_name=p_payee_name,
            final_payee_id=p_contact.contact_id if p_contact else None,
            primary_amount=p_amount,
            secondary_amount=s_amount,
            primary_payee=p_payee_name,
            secondary_payee=s_payee_name,
            recommended_action="PROCEED_TO_READ_BACK",
            explanation=(
                f"Multi-method consensus verified for ₹{p_amount:,} to {p_payee_name}. "
                "Ready for vocal and visual read-back."
            ),
            audit_context={
                "amount": p_amount,
                "payee_id": p_contact.contact_id if p_contact else None,
                "payee_name": p_payee_name,
            },
        )
