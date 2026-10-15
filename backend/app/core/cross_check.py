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
    # 0 - 9
    "shunya": 0, "zero": 0, "शून्य": 0,
    "ek": 1, "ik": 1, "one": 1, "एक": 1,
    "do": 2, "two": 2, "दो": 2,
    "teen": 3, "tin": 3, "three": 3, "तीन": 3,
    "chaar": 4, "char": 4, "four": 4, "चार": 4,
    "paanch": 5, "panch": 5, "five": 5, "पाँच": 5, "पांच": 5,
    "chhah": 6, "che": 6, "chhe": 6, "six": 6, "छह": 6, "छः": 6,
    "saat": 7, "sat": 7, "seven": 7, "सात": 7,
    "aath": 8, "ath": 8, "eight": 8, "आठ": 8,
    "nau": 9, "no": 9, "nine": 9, "नौ": 9,
    # 10 - 19
    "das": 10, "dus": 10, "ten": 10, "दस": 10,
    "gyarah": 11, "gyara": 11, "eleven": 11, "ग्यारह": 11,
    "baarah": 12, "bara": 12, "twelve": 12, "बारह": 12,
    "terah": 13, "tera": 13, "thirteen": 13, "तेरह": 13,
    "chaudah": 14, "chauda": 14, "chouda": 14, "fourteen": 14, "चौदह": 14,
    "pandrah": 15, "pandra": 15, "fifteen": 15, "पंद्रह": 15,
    "solah": 16, "sola": 16, "sixteen": 16, "सोलह": 16,
    "satrah": 17, "satra": 17, "seventeen": 17, "सत्रह": 17,
    "atharah": 18, "athara": 18, "eighteen": 18, "अट्ठारह": 18, "अठारह": 18,
    "unnees": 19, "unnis": 19, "nineteen": 19, "उन्नीस": 19,
    # 20 - 29
    "bees": 20, "bis": 20, "twenty": 20, "बीस": 20,
    "ikkees": 21, "ikkis": 21, "twenty one": 21, "twenty-one": 21, "इक्कीस": 21,
    "baaees": 22, "bais": 22, "twenty two": 22, "twenty-two": 22, "बाईस": 22,
    "teees": 23, "teis": 23, "twenty three": 23, "twenty-three": 23, "तेईस": 23,
    "chaubees": 24, "chaubis": 24, "twenty four": 24, "twenty-four": 24, "चौबीस": 24,
    "pachees": 25, "pachis": 25, "twenty five": 25, "twenty-five": 25, "पच्चीस": 25,
    "chhabbees": 26, "chhabbis": 26, "twenty six": 26, "twenty-six": 26, "छब्बीस": 26,
    "sattaees": 27, "sattais": 27, "twenty seven": 27, "twenty-seven": 27, "सत्ताईस": 27,
    "atthaees": 28, "atthais": 28, "twenty eight": 28, "twenty-eight": 28, "अट्ठाईस": 28,
    "untees": 29, "untis": 29, "twenty nine": 29, "twenty-nine": 29, "उनतीस": 29,
    # 30 - 39
    "tees": 30, "tis": 30, "thirty": 30, "तीस": 30,
    "ikattees": 31, "ikattis": 31, "thirty one": 31, "thirty-one": 31, "इकत्तीस": 31,
    "battees": 32, "battis": 32, "thirty two": 32, "thirty-two": 32, "बत्तीस": 32,
    "taintrees": 33, "taintis": 33, "tentis": 33, "thirty three": 33, "thirty-three": 33, "तैंतीस": 33,
    "chautees": 34, "chautis": 34, "thirty four": 34, "thirty-four": 34, "चौंतीस": 34,
    "paintees": 35, "paintis": 35, "thirty five": 35, "thirty-five": 35, "पैंतीस": 35,
    "chhattees": 36, "chhattis": 36, "thirty six": 36, "thirty-six": 36, "छत्तीस": 36,
    "saintees": 37, "saintis": 37, "thirty seven": 37, "thirty-seven": 37, "सैंतीस": 37,
    "adhtees": 38, "adhtis": 38, "artis": 38, "thirty eight": 38, "thirty-eight": 38, "अड़तीस": 38,
    "untalees": 39, "untalis": 39, "thirty nine": 39, "thirty-nine": 39, "उनतालीस": 39,
    # 40 - 49
    "chaalees": 40, "chalis": 40, "forty": 40, "चालीस": 40,
    "iktalees": 41, "iktalis": 41, "forty one": 41, "forty-one": 41, "इकतालीस": 41,
    "bayalees": 42, "bayalis": 42, "forty two": 42, "forty-two": 42, "बयालीस": 42,
    "taintalees": 43, "taintalis": 43, "forty three": 43, "forty-three": 43, "तैंतालीस": 43,
    "chavalees": 44, "chavalis": 44, "chauwalees": 44, "forty four": 44, "forty-four": 44, "चवालीस": 44,
    "paintalees": 45, "paintalis": 45, "forty five": 45, "forty-five": 45, "पैंतालीस": 45,
    "chhiyalees": 46, "chhiyalis": 46, "forty six": 46, "forty-six": 46, "छियालीस": 46,
    "saintaalees": 47, "saintalis": 47, "forty seven": 47, "forty-seven": 47, "सैंतालीस": 47,
    "adhtalees": 48, "adhtalis": 48, "artalis": 48, "forty eight": 48, "forty-eight": 48, "अड़तालीस": 48,
    "unchaas": 49, "unchas": 49, "forty nine": 49, "forty-nine": 49, "उनचास": 49,
    # 50 - 59
    "pachaas": 50, "pachas": 50, "fifty": 50, "पचास": 50,
    "ikyawan": 51, "ikyavan": 51, "ikawan": 51, "fifty one": 51, "fifty-one": 51, "इक्यावन": 51,
    "baawan": 52, "bavan": 52, "baavan": 52, "fifty two": 52, "fifty-two": 52, "बावन": 52,
    "tirepan": 53, "tirpan": 53, "fifty three": 53, "fifty-three": 53, "तिरपन": 53,
    "chauwan": 54, "chawwan": 54, "fifty four": 54, "fifty-four": 54, "चौवन": 54,
    "pachpan": 55, "fifty five": 55, "fifty-five": 55, "पचपन": 55,
    "chhappan": 56, "fifty six": 56, "fifty-six": 56, "छप्पन": 56,
    "sattawan": 57, "satavan": 57, "fifty seven": 57, "fifty-seven": 57, "सत्तावन": 57,
    "atthawan": 58, "athavan": 58, "fifty eight": 58, "fifty-eight": 58, "अट्ठावन": 58,
    "unsath": 59, "unsat": 59, "fifty nine": 59, "fifty-nine": 59, "उनसठ": 59,
    # 60 - 69
    "saath": 60, "sath": 60, "sixty": 60, "साठ": 60,
    "iksath": 61, "iksat": 61, "sixty one": 61, "sixty-one": 61, "इकसठ": 61,
    "baasath": 62, "basath": 62, "basat": 62, "sixty two": 62, "sixty-two": 62, "बासठ": 62,
    "tirsath": 63, "tirsat": 63, "sixty three": 63, "sixty-three": 63, "तिरसठ": 63,
    "chausath": 64, "chausat": 64, "sixty four": 64, "sixty-four": 64, "चौसठ": 64,
    "painsath": 65, "painsat": 65, "sixty five": 65, "sixty-five": 65, "पैंसठ": 65,
    "chhiyasath": 66, "chhiyasat": 66, "sixty six": 66, "sixty-six": 66, "छियासठ": 66,
    "sarsath": 67, "sarsat": 67, "sixty seven": 67, "sixty-seven": 67, "सरसठ": 67,
    "ardsath": 68, "athsath": 68, "adhsath": 68, "sixty eight": 68, "sixty-eight": 68, "अड़सठ": 68,
    "unhattar": 69, "unhatar": 69, "sixty nine": 69, "sixty-nine": 69, "उनहत्तर": 69,
    # 70 - 79
    "sattar": 70, "satar": 70, "seventy": 70, "सत्तर": 70,
    "ikhattar": 71, "ikhatar": 71, "seventy one": 71, "seventy-one": 71, "इकहत्तर": 71,
    "bahattar": 72, "bahatar": 72, "seventy two": 72, "seventy-two": 72, "बहत्तर": 72,
    "tihattar": 73, "tihatar": 73, "seventy three": 73, "seventy-three": 73, "तिहत्तर": 73,
    "chauhattar": 74, "chauhatar": 74, "seventy four": 74, "seventy-four": 74, "चौहत्तर": 74,
    "pachhattar": 75, "pachhatar": 75, "pachattar": 75, "seventy five": 75, "seventy-five": 75, "पचहत्तर": 75,
    "chhihattar": 76, "chhihatar": 76, "seventy six": 76, "seventy-six": 76, "छिहत्तर": 76,
    "sathattar": 77, "sathatar": 77, "seventy seven": 77, "seventy-seven": 77, "सतहत्तर": 77,
    "athhattar": 78, "ath-hattar": 78, "at-hattar": 78, "seventy eight": 78, "seventy-eight": 78, "अठहत्तर": 78,
    "unyasi": 79, "unyaasi": 79, "unasi": 79, "unaasi": 79, "seventy nine": 79, "seventy-nine": 79, "उनासी": 79, "उन्यासी": 79,
    # 80 - 89
    "assi": 80, "asi": 80, "eighty": 80, "अस्सी": 80,
    "ikyasi": 81, "ikyaasi": 81, "ikasi": 81, "ikaasi": 81, "eighty one": 81, "eighty-one": 81, "इक्यासी": 81,
    "bayasi": 82, "bayaasi": 82, "eighty two": 82, "eighty-two": 82, "बयासी": 82,
    "tirasi": 83, "tiraasi": 83, "eighty three": 83, "eighty-three": 83, "तिरासी": 83,
    "chaurasi": 84, "chauraasi": 84, "eighty four": 84, "eighty-four": 84, "चौरासी": 84,
    "pachasi": 85, "pachaasi": 85, "eighty five": 85, "eighty-five": 85, "पचासी": 85,
    "chhiyasi": 86, "chhiyaasi": 86, "eighty six": 86, "eighty-six": 86, "छियासी": 86,
    "satasi": 87, "sataasi": 87, "eighty seven": 87, "eighty-seven": 87, "सत्तासी": 87,
    "atthasi": 88, "atthaasi": 88, "eighty eight": 88, "eighty-eight": 88, "अट्ठासी": 88,
    "nawasi": 89, "nawaasi": 89, "navasi": 89, "navaasi": 89, "eighty nine": 89, "eighty-nine": 89, "नवासी": 89,
    # 90 - 99
    "nabbe": 90, "navve": 90, "nabbey": 90, "ninety": 90, "नब्बे": 90,
    "ikyanve": 91, "ikyanwey": 91, "ikyaanve": 91, "ninety one": 91, "ninety-one": 91, "इक्यानवे": 91,
    "baanve": 92, "baanwey": 92, "ninety two": 92, "ninety-two": 92, "बानवे": 92,
    "tiranve": 93, "tiranwey": 93, "ninety three": 93, "ninety-three": 93, "तिरानवे": 93,
    "chauranve": 94, "chauranwey": 94, "ninety four": 94, "ninety-four": 94, "चौरानवे": 94,
    "pachanve": 95, "pachanwey": 95, "ninety five": 95, "ninety-five": 95, "पचानवे": 95,
    "chhiyanve": 96, "chhiyanwey": 96, "ninety six": 96, "ninety-six": 96, "छियानवे": 96,
    "sattanve": 97, "sattanwey": 97, "ninety seven": 97, "ninety-seven": 97, "सत्तानवे": 97,
    "atthanve": 98, "atthanwey": 98, "ninety eight": 98, "ninety-eight": 98, "अट्ठानवे": 98,
    "ninyanve": 99, "ninyaanve": 99, "ninyanwey": 99, "ninety nine": 99, "ninety-nine": 99, "निन्यानवे": 99,
}

SEC_MULT_RE = r'(?:sau|so|sou|hundred|hazaar|hazar|hajar|hazaarr|hazarr|thousand|lakh|laakh|laak|lac|lakhs|laakhs|lacs|crore|crores|cr|k|सौ|हज़ार|हजार|लाख|करोड़)'

SEC_NOISE_RE = re.compile(
    r'(?:(?<=^)|(?<=[^\w\u0900-\u097F]))(?:'
    r'dedh|dhedh|derh|deydh|dadh|dhai|dhaai|dhaee|adhai|sawa|sava|sawwa|paune|pone|saade|sadhe|sade|'
    r'डेढ़|डेढ|ढाई|ढा़ई|सवा|पौने|साढ़े|साढे|'
    r'sau|so|sou|hundred|hazaar|hazar|hajar|hazaarr|hazarr|thousand|lakh|laakh|laak|lac|lakhs|laakhs|lacs|crore|crores|cr|k|'
    r'सौ|हज़ार|हजार|लाख|करोड़|'
    r'shunya|zero|ek|ik|one|do|two|teen|tin|three|chaar|char|four|paanch|panch|five|chhah|che|chhe|six|saat|sat|seven|aath|ath|eight|nau|no|nine|das|dus|ten|'
    r'शून्य|एक|दो|तीन|चार|पाँच|पांच|छह|सात|आठ|नौ|दस|'
    r'bees|pachees|tees|chaalees|pachaas|saath|sattar|assi|nabbe|बीस|पच्चीस|तीस|चालीस|पचास|'
    r'rupees|rupaye|rupya|rupee|rs|inr|/-|रुपये|रुपए|रुपया|रु|'
    r'send|pay|transfer|bhej|bhejo|de|do|karo|kardo|kar|kripya|please|भेज|भेजो|करो|कर|दो'
    r')(?:(?=[^\w\u0900-\u097F])|$)|(?:(?<=^)|(?<=[^\w\u0900-\u097F]))\d+(?:\.\d+)?(?:(?=[^\w\u0900-\u097F])|$)',
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
        # Replace auxiliary verb phrases where 'do' means 'give/send', not number 2
        text = re.sub(r'(?:(?<=^)|(?<=[^\w\u0900-\u097F]))(?:bhej|kar|de|भेज|कर|दे)\s+(?:do|दो)(?:(?=[^\w\u0900-\u097F])|$)', ' transfer ', text)

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

        # Fractional extraction (dedh, dhai, sawa, paune, saade)
        m_dedh = re.search(r'(?:^|[^\w\u0900-\u097F])(?:dedh|dhedh|derh|deydh|डेढ़|डेढ)\s+(' + SEC_MULT_RE + r')(?:[^\w\u0900-\u097F]|$)', t)
        if m_dedh:
            extracted_amount = int(1.5 * SEC_MULT_MAP.get(m_dedh.group(1), 1000))
        else:
            m_dhai = re.search(r'(?:^|[^\w\u0900-\u097F])(?:dhai|dhaai|dhaee|adhai|ढाई|ढा़ई)\s+(' + SEC_MULT_RE + r')(?:[^\w\u0900-\u097F]|$)', t)
            if m_dhai:
                extracted_amount = int(2.5 * SEC_MULT_MAP.get(m_dhai.group(1), 100))
            else:
                m_sawa = re.search(r'(?:^|[^\w\u0900-\u097F])(?:sawa|sava|सवा)\s+([\w\u0900-\u097F]+)\s+(' + SEC_MULT_RE + r')(?:[^\w\u0900-\u097F]|$)', t)
                if m_sawa:
                    val = SEC_WORD_MAP.get(m_sawa.group(1)) or (int(m_sawa.group(1)) if m_sawa.group(1).isdigit() else None)
                    mult = SEC_MULT_MAP.get(m_sawa.group(2))
                    if val is not None and mult is not None:
                        extracted_amount = int((val + 0.25) * mult)
                else:
                    m_sawa_std = re.search(r'(?:^|[^\w\u0900-\u097F])(?:sawa|sava|सवा)\s+(' + SEC_MULT_RE + r')(?:[^\w\u0900-\u097F]|$)', t)
                    if m_sawa_std:
                        mult = SEC_MULT_MAP.get(m_sawa_std.group(1))
                        if mult is not None:
                            extracted_amount = int(1.25 * mult)
                    else:
                        m_paune = re.search(r'(?:^|[^\w\u0900-\u097F])(?:paune|pone|पौने)\s+([\w\u0900-\u097F]+)\s+(' + SEC_MULT_RE + r')(?:[^\w\u0900-\u097F]|$)', t)
                        if m_paune:
                            val = SEC_WORD_MAP.get(m_paune.group(1)) or (int(m_paune.group(1)) if m_paune.group(1).isdigit() else None)
                            mult = SEC_MULT_MAP.get(m_paune.group(2))
                            if val is not None and mult is not None:
                                extracted_amount = int((val - 0.25) * mult)
                        else:
                            m_saade = re.search(r'(?:^|[^\w\u0900-\u097F])(?:saade|sadhe|साढ़े)\s+([\w\u0900-\u097F]+)\s+(' + SEC_MULT_RE + r')(?:[^\w\u0900-\u097F]|$)', t)
                            if m_saade:
                                val = SEC_WORD_MAP.get(m_saade.group(1)) or (int(m_saade.group(1)) if m_saade.group(1).isdigit() else None)
                                mult = SEC_MULT_MAP.get(m_saade.group(2))
                                if val is not None and mult is not None:
                                    extracted_amount = int((val + 0.5) * mult)

        # Compound word + multiplier combinations (e.g. 'ek sau bees', 'do sau pachaas', 'teen sau', 'चार सौ', 'एक सौ बीस')
        if extracted_amount is None:
            sorted_words = sorted(SEC_WORD_MAP.keys(), key=lambda x: len(x), reverse=True)
            sorted_mults = sorted(SEC_MULT_MAP.keys(), key=lambda x: len(x), reverse=True)
            word_re = '(?:' + '|'.join(re.escape(w) for w in sorted_words) + r'|\d+)'
            mult_re = '(?:' + '|'.join(re.escape(m) for m in sorted_mults) + ')'
            pattern_mult = re.compile(
                r'(?:^|[^\w\u0900-\u097F])(?:(' + word_re + r')\s+)?(' + mult_re + r')(?:(?:\s+(' + word_re + r')))?(?:[^\w\u0900-\u097F]|$)',
                re.IGNORECASE
            )
            m_mult = pattern_mult.search(t)
            if m_mult:
                w1, mult, w2 = m_mult.group(1), m_mult.group(2), m_mult.group(3)
                mult_val = SEC_MULT_MAP.get(mult.lower(), 100)
                if w1:
                    val1 = int(w1) if w1.isdigit() else SEC_WORD_MAP.get(w1.lower(), 1)
                else:
                    val1 = 1
                if w2:
                    val2 = int(w2) if w2.isdigit() else SEC_WORD_MAP.get(w2.lower(), 0)
                else:
                    val2 = 0
                if val1 is not None and mult_val is not None and val2 is not None:
                    extracted_amount = int(val1 * mult_val + val2)

        # Digits + optional multiplier (e.g. '1500 rupaye', '1.5 hazaar', 'send 500', '120', '300')
        if extracted_amount is None:
            m_amt = re.search(
                r'(?:(?:₹|rs\.?|inr)\s*)?(\b\d+(?:\.\d+)?)\s*(' + SEC_MULT_RE + r')?(?:\s*(?:rupees|rupaye|rupya|rs|inr|/-|रुपये|रुपए|रु))?',
                t,
            )
            if m_amt and m_amt.group(1):
                num = float(m_amt.group(1))
                mult = SEC_MULT_MAP.get(m_amt.group(2), 1) if m_amt.group(2) else 1
                extracted_amount = int(num * mult)

        # Standalone word amounts (e.g. 'pachaas rupaye', 'bees', 'पचास')
        if extracted_amount is None:
            sorted_words = sorted(SEC_WORD_MAP.keys(), key=lambda x: len(x), reverse=True)
            word_re = '(?:' + '|'.join(re.escape(w) for w in sorted_words) + ')'
            pattern_word = re.compile(
                r'(?:^|[^\w\u0900-\u097F])(' + word_re + r')(?:[^\w\u0900-\u097F]|$)',
                re.IGNORECASE
            )
            m_single = pattern_word.search(t)
            if m_single and m_single.group(1).lower() in SEC_WORD_MAP:
                extracted_amount = SEC_WORD_MAP[m_single.group(1).lower()]

        # 2. Independent payee extraction
        m_ko = re.search(r'^(?:please\s+|kripya\s+)?(.*?)\s+(?:ko|को)(?:[^\w\u0900-\u097F]|$)', text, re.IGNORECASE)
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
            from app.parsers.payee_resolver import DEVANAGARI_NAME_MAP, devanagari_to_latin
            s_clean = s_payee_name.lower().strip()
            s_latin = (DEVANAGARI_NAME_MAP.get(s_clean) or devanagari_to_latin(s_clean)).lower().strip()
            similarity = max(
                fuzz.token_set_ratio(p_payee_name.lower(), s_clean),
                fuzz.token_set_ratio(p_payee_name.lower(), s_latin) if s_latin else 0.0,
            )
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
