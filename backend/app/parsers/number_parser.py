"""
Deterministic English and Hinglish financial amount parser for VaaniPay.
Converts colloquial spoken and written numerical expressions into exact integer INR amounts.
Zero external LLM or API dependencies. Strictly deterministic and unit-tested.
"""

import re
from enum import Enum
from typing import Optional, List, Tuple
from pydantic import BaseModel, ConfigDict
from app.core.config import get_settings


class ParseStatus(str, Enum):
    SUCCESS = "SUCCESS"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    INVALID_VALUE = "INVALID_VALUE"
    MALFORMED = "MALFORMED"


class ParsedAmountResult(BaseModel):
    """Structured result from deterministic amount parsing."""
    model_config = ConfigDict(from_attributes=True)

    status: ParseStatus
    amount: Optional[int] = None
    currency: str = "INR"
    raw_phrase: Optional[str] = None
    normalized_phrase: Optional[str] = None
    is_within_limit: bool = True
    limit_exceeded: bool = False
    max_limit: float = 10000.0
    candidate_amounts: List[int] = []
    explanation: str = ""


# =============================================================================
# LEXICAL VOCABULARY & MULTIPLIER TABLES
# =============================================================================

HINDI_ENGLISH_NUMBERS = {
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

MULTIPLIERS = {
    "sau": 100, "so": 100, "sou": 100, "hundred": 100, "सौ": 100,
    "hazaar": 1000, "hazar": 1000, "hajar": 1000, "hazaarr": 1000, "hazarr": 1000, "hazaari": 1000, "thousand": 1000, "k": 1000, "हज़ार": 1000, "हजार": 1000,
    "lakh": 100000, "laakh": 100000, "laak": 100000, "lac": 100000, "lakhs": 100000, "laakhs": 100000, "lacs": 100000, "लाख": 100000,
    "crore": 10000000, "cr": 10000000, "crores": 10000000, "करोड़": 10000000,
}

FRACTION_UNITS = r'(?:sau|so|hazaar|hazar|hajar|hazaarr|hazarr|thousand|lakh|laakh|laak|lac|lacs|lakhs|laakhs|crore|crores|cr|सौ|हज़ार|हजार|लाख|करोड़)'

DEVANAGARI_DIGITS = str.maketrans('०१२३४५६७८९', '0123456789')


def _clean_text(text: str) -> str:
    """Standardizes input string: applies deterministic transcript repair, converts Devanagari numerals, and normalizes currency."""
    if not text:
        return ""
    from app.parsers.transcript_repair import TranscriptRepairService
    repaired, _ = TranscriptRepairService.repair(text)
    # Translate Devanagari numerals to standard digits (० -> 0, etc.)
    s = repaired.translate(DEVANAGARI_DIGITS)
    # Normalize unicode symbols (e.g. ₹ to ' rs ')
    s = s.replace("₹", " rs ")
    # Replace Devanagari currency words using unicode-safe word boundaries (avoids ASCII \b destroying Devanagari words)
    s = re.sub(r'(?:(?<=^)|(?<=[^\w\u0900-\u097F]))(?:रुपये|रुपए|रुपया|रुपयी|रु)(?:(?=[^\w\u0900-\u097F])|$)', ' rs ', s)
    s = s.lower()
    # Strip commas inside numbers (e.g. 1,500 -> 1500)
    s = re.sub(r'(?<=\d),(?=\d)', '', s)
    # Mask Indian mobile phone numbers (10 digits starting with 6-9) so they don't get parsed as amounts
    s = re.sub(r'\b(?:\+91|91)?[6-9]\d{9}\b', ' [PHONE] ', s)
    # Strip punctuation (keep hyphens, decimals between digits, alphanumeric, and Devanagari unicode range \u0900-\u097F)
    s = re.sub(r'[^\w\s\-\.\u0900-\u097F]', ' ', s)
    s = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', s)
    # Normalize whitespaces
    return " ".join(s.split())


def _word_to_int(word: str) -> Optional[int]:
    """Resolves a token or compound word to its base integer value."""
    word = word.strip()
    if word in HINDI_ENGLISH_NUMBERS:
        return HINDI_ENGLISH_NUMBERS[word]
    if word.isdigit():
        return int(word)
    return None


class DeterministicNumberParser:
    """Deterministic parser engine for English and Hinglish amount requests."""

    def __init__(self, max_limit: Optional[float] = None):
        settings = get_settings()
        self.max_limit = max_limit if max_limit is not None else settings.MAX_VOICE_TX_AMOUNT

    def parse(self, text: str) -> ParsedAmountResult:
        """
        Main entrypoint. Extracts payment amounts from input text.
        Guarantees:
        - Never silently guesses or clamps amounts.
        - Enforces transaction limit validation.
        - Flags multiple conflicting candidate amounts as AMBIGUOUS.
        """
        if not text or not text.strip():
            return ParsedAmountResult(
                status=ParseStatus.NOT_FOUND,
                max_limit=self.max_limit,
                explanation="Empty or whitespace-only input provided.",
            )

        cleaned = _clean_text(text)

        # 1. Check for negative numbers
        if re.search(r'(?:minus|-)\s*\d+', cleaned) or re.search(r'\bminus\b', cleaned):
            return ParsedAmountResult(
                status=ParseStatus.INVALID_VALUE,
                raw_phrase=text,
                normalized_phrase=cleaned,
                max_limit=self.max_limit,
                explanation="Transaction amount cannot be negative.",
            )

        # 2. Check for explicit multiple amounts / ambiguity
        candidates = self._extract_all_candidates(cleaned)
        distinct_amounts = sorted(list({c[0] for c in candidates if c[0] > 0}))

        if len(distinct_amounts) > 1:
            # Check if this is a composite phrase like 'two thousand' + 'five hundred' (already combined)
            # or truly multiple competing amounts e.g. '500 or 1000', 'dedh hazaar ya do hazaar'
            has_disjunction = bool(re.search(r'\b(or|ya|nahi|no|wait|instead)\b', cleaned))
            if has_disjunction or len(candidates) > 2:
                return ParsedAmountResult(
                    status=ParseStatus.AMBIGUOUS,
                    candidate_amounts=distinct_amounts,
                    raw_phrase=text,
                    normalized_phrase=cleaned,
                    max_limit=self.max_limit,
                    explanation=f"Multiple conflicting amounts detected: {distinct_amounts}. Clarification required.",
                )

        if not candidates:
            return ParsedAmountResult(
                status=ParseStatus.NOT_FOUND,
                raw_phrase=text,
                normalized_phrase=cleaned,
                max_limit=self.max_limit,
                explanation="No monetary amount detected in the provided input.",
            )

        # Select primary candidate
        amount, matched_phrase = candidates[0]

        if amount == 0:
            return ParsedAmountResult(
                status=ParseStatus.INVALID_VALUE,
                amount=0,
                raw_phrase=text,
                normalized_phrase=matched_phrase,
                max_limit=self.max_limit,
                explanation="Transaction amount must be greater than zero.",
            )

        # Validate transaction limits (Do not silently clamp!)
        is_within_limit = amount <= self.max_limit
        limit_exceeded = not is_within_limit
        explanation = "Amount successfully parsed."
        if limit_exceeded:
            explanation = (
                f"Parsed amount ₹{amount:,} exceeds maximum voice transaction limit of ₹{int(self.max_limit):,}."
            )

        return ParsedAmountResult(
            status=ParseStatus.SUCCESS,
            amount=amount,
            currency="INR",
            raw_phrase=text,
            normalized_phrase=matched_phrase,
            is_within_limit=is_within_limit,
            limit_exceeded=limit_exceeded,
            max_limit=self.max_limit,
            candidate_amounts=[amount],
            explanation=explanation,
        )

    def _extract_all_candidates(self, text: str) -> List[Tuple[int, str]]:
        """
        Extracts candidate amounts using strict deterministic rules.
        Guarantees that numbers attached to payee names (e.g. 'Ramesh 2 ko', 'to Ramesh 2')
        or phone numbers are never confused with payment amounts.
        """
        # Identify text regions that are likely payee names to avoid extracting numbers from them
        payee_regions = []
        # In Hindi/Hinglish: phrase before 'ko' (e.g. 'ramesh 2 ko ...')
        m_ko = re.search(r'^(?:please\s+|kripya\s+)?(.*?)\s+ko\b', text, re.IGNORECASE)
        if m_ko:
            cand = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', m_ko.group(1))
            cand = re.sub(r'\b(?:rupee|rupay|rupaye|rupya|rs|inr|sau|hazaar|lakh|dedh|dhai|sawa)\b', ' ', cand, flags=re.IGNORECASE)
            cand_clean = ' '.join(cand.split())
            if cand_clean:
                payee_regions.append(cand_clean)
        # In English: phrase after 'to' (e.g. '... to ramesh 2')
        m_to = re.search(r'\bto\s+([a-zA-Z0-9_\s]+)$', text, re.IGNORECASE)
        if m_to:
            cand = re.sub(r'\b\d+(?:\.\d+)?\b', ' ', m_to.group(1))
            cand_clean = ' '.join(cand.split())
            if cand_clean:
                payee_regions.append(cand_clean)

        AMOUNT_MARKERS = [
            "rupee", "rupay", "rupya", "rs", "inr",
            "sau", "so", "hazaar", "hazar", "hajar", "thousand", "lakh", "lac", "crore", "hundred", "k",
            "dedh", "dhedh", "derh", "dhai", "dhaai", "sawa", "sava", "paune", "pone", "saade", "sadhe",
            "रुपये", "रुपए", "रुपया", "रु", "सौ", "हज़ार", "हजार", "लाख", "करोड़",
            "डेढ़", "ढाई", "सवा", "पौने", "साढ़े",
        ]

        # Helper to check if a phrase is inside an identified payee region
        def is_in_payee_region(phrase: str) -> bool:
            clean_phrase = phrase.strip()
            # If the candidate phrase is numeric, or has explicit currency, fraction, or multiplier, it is definitely an amount!
            if re.match(r'^\d+(?:\.\d+)?$', clean_phrase) or any(k in clean_phrase for k in AMOUNT_MARKERS):
                return False
            for pr in payee_regions:
                if re.search(r'\b' + re.escape(clean_phrase) + r'\b', pr):
                    return True
            return False

        # Step A: Fractional Idioms (dedh, dhai, sawa, paune, saade)
        fractional_results = self._extract_fractional_amounts(text)
        
        # Step B: Word Combinations with multipliers (e.g. 'two thousand paanch sau', 'paanch sau')
        word_results = self._extract_word_amounts(text)
        
        # Step C: Digits with explicit currency or transfer context
        digit_results = self._extract_digit_amounts(text)

        # Collect strong candidates (those with multipliers, fractions, or currency keywords)
        strong_candidates: List[Tuple[int, str]] = []
        weak_candidates: List[Tuple[int, str]] = []

        for val, phrase in fractional_results + word_results + digit_results:
            if val < 0:
                continue
            phrase_clean = phrase.strip()
            if is_in_payee_region(phrase_clean):
                continue
            
            # Check if candidate has strong amount markers
            has_strong_marker = any(k in phrase_clean for k in AMOUNT_MARKERS)
            # Or if text immediately adjacent has transfer verb or currency
            pattern_adj = re.compile(
                r'(?:send|pay|transfer|bhej|bhejo|₹|rs|inr)\s+' + re.escape(phrase_clean) +
                r'|' + re.escape(phrase_clean) + r'\s*(?:rupees|rupaye|rupya|rs|inr|bhej|bhejo|transfer)',
                re.IGNORECASE
            )
            if has_strong_marker or pattern_adj.search(text):
                strong_candidates.append((val, phrase_clean))
            else:
                weak_candidates.append((val, phrase_clean))

        has_disjunction = bool(re.search(r'\b(or|ya|nahi|no|wait|instead)\b', text, re.IGNORECASE))
        if has_disjunction:
            candidates_to_use = strong_candidates + weak_candidates
        else:
            candidates_to_use = strong_candidates if strong_candidates else weak_candidates

        # Discard candidates that are strictly sub-phrases of a longer candidate
        non_sub_candidates = []
        for val, phrase in candidates_to_use:
            is_sub = False
            for other_val, other_phrase in candidates_to_use:
                if phrase != other_phrase and phrase in other_phrase:
                    is_sub = True
                    break
            if not is_sub:
                non_sub_candidates.append((val, phrase))

        # Deduplicate while preserving order
        seen = set()
        unique_results = []
        for val, phrase in non_sub_candidates:
            key = (val, phrase)
            if key not in seen:
                seen.add(key)
                unique_results.append((val, phrase))

        return unique_results

    def _extract_fractional_amounts(self, text: str) -> List[Tuple[int, str]]:
        """Parses colloquial Hindi and Devanagari fractional expressions."""
        matches: List[Tuple[int, str]] = []

        # 1. Dedh (<unit>) -> 1.5 * unit (e.g. dedh sau = 150, dedh hazaar = 1500, dedh lakh = 150000)
        for m in re.finditer(
            r'(?:^|\s)(?:dedh|dhedh|derh|deydh|dadh|डेढ़|डेढ)\s+(' + FRACTION_UNITS + r')(?:\s|$|[^\w\u0900-\u097F])',
            text,
        ):
            unit_str = m.group(1)
            unit_val = MULTIPLIERS.get(unit_str, 1000)
            amount = int(1.5 * unit_val)
            matches.append((amount, m.group(0).strip()))

        # 2. Dhai (<unit>) -> 2.5 * unit (e.g. dhai sau = 250, dhai hazaar = 2500, dhai lakh = 250000)
        for m in re.finditer(
            r'(?:^|\s)(?:dhai|dhaai|dhaee|adhai|ढाई|ढा़ई)\s+(' + FRACTION_UNITS + r')(?:\s|$|[^\w\u0900-\u097F])',
            text,
        ):
            unit_str = m.group(1)
            unit_val = MULTIPLIERS.get(unit_str, 100)
            amount = int(2.5 * unit_val)
            matches.append((amount, m.group(0).strip()))

        # 3. Sawa (<N> <unit>) -> (N + 0.25) * unit (e.g. sawa do lakh = 2.25 * 100,000 = 225,000)
        for m in re.finditer(
            r'(?:^|\s)(?:sawa|sava|sawwa|सवा)\s+([a-zA-Z\u0900-\u097F]+|\d+)\s+(' + FRACTION_UNITS + r')(?:\s|$|[^\w\u0900-\u097F])',
            text,
        ):
            num_val = _word_to_int(m.group(1))
            unit_val = MULTIPLIERS.get(m.group(2))
            if num_val is not None and unit_val is not None:
                amount = int((num_val + 0.25) * unit_val)
                matches.append((amount, m.group(0).strip()))

        # 3b. Standalone Sawa (<unit>) -> 1.25 * unit (e.g. sawa hazaar = 1250, sawa sau = 125)
        for m in re.finditer(
            r'(?:^|\s)(?:sawa|sava|sawwa|सवा)\s+(' + FRACTION_UNITS + r')(?:\s|$|[^\w\u0900-\u097F])',
            text,
        ):
            unit_val = MULTIPLIERS.get(m.group(1))
            if unit_val is not None:
                amount = int(1.25 * unit_val)
                matches.append((amount, m.group(0).strip()))

        # 4. Paune (<N> <unit>) -> (N - 0.25) * unit (e.g. paune teen hazaar = 2.75 * 1000 = 2750)
        for m in re.finditer(
            r'(?:^|\s)(?:paune|pone|pawne|pawnay|पौने)\s+([a-zA-Z\u0900-\u097F]+|\d+)\s+(' + FRACTION_UNITS + r')(?:\s|$|[^\w\u0900-\u097F])',
            text,
        ):
            num_val = _word_to_int(m.group(1))
            unit_val = MULTIPLIERS.get(m.group(2))
            if num_val is not None and unit_val is not None:
                amount = int((num_val - 0.25) * unit_val)
                matches.append((amount, m.group(0).strip()))

        # 4b. Standalone Paune (<unit>) -> 0.75 * unit (e.g. paune hazaar = 750, paune sau = 75)
        for m in re.finditer(
            r'(?:^|\s)(?:paune|pone|pawne|pawnay|पौने)\s+(' + FRACTION_UNITS + r')(?:\s|$|[^\w\u0900-\u097F])',
            text,
        ):
            unit_val = MULTIPLIERS.get(m.group(1))
            if unit_val is not None:
                amount = int(0.75 * unit_val)
                matches.append((amount, m.group(0).strip()))

        # 5. Saade (<N> <unit>) -> (N + 0.5) * unit (e.g. saade teen hazaar = 3500)
        for m in re.finditer(
            r'(?:^|\s)(?:saade|sadhe|sade|साढ़े|साढे)\s+([a-zA-Z\u0900-\u097F]+|\d+)\s+(' + FRACTION_UNITS + r')(?:\s|$|[^\w\u0900-\u097F])',
            text,
        ):
            num_val = _word_to_int(m.group(1))
            unit_val = MULTIPLIERS.get(m.group(2))
            if num_val is not None and unit_val is not None:
                amount = int((num_val + 0.5) * unit_val)
                matches.append((amount, m.group(0).strip()))

        return matches

    def _extract_word_amounts(self, text: str) -> List[Tuple[int, str]]:
        """Parses composite words like 'two thousand paanch sau' or 'paanch sau'."""
        matches: List[Tuple[int, str]] = []

        # Replace auxiliary verb phrases where 'do' means 'give/send', not number 2
        normalized_text = re.sub(r'\b(?:bhej|kar|de|भेज|कर|दे)\s+(?:do|दो)\b', ' transfer ', text)

        all_tokens = set(HINDI_ENGLISH_NUMBERS.keys()) | set(MULTIPLIERS.keys()) | {"and"}
        words = normalized_text.split()

        i = 0
        while i < len(words):
            if words[i] in all_tokens or words[i].isdigit():
                start = i
                while i < len(words) and (words[i] in all_tokens or words[i].isdigit()):
                    i += 1
                seq = words[start:i]
                # If sequence is only a multiplier and previous token was a digit/decimal, skip (already handled by digit parser)
                if len(seq) == 1 and seq[0] in MULTIPLIERS and start > 0 and re.match(r'^\d+(?:\.\d+)?$', words[start - 1]):
                    continue
                # Filter out pure digits without any word multiplier (pure digits handled by _extract_digit_amounts)
                has_word_num = any(t in HINDI_ENGLISH_NUMBERS or t in MULTIPLIERS for t in seq)
                if has_word_num:
                    parsed = self._evaluate_number_sequence(seq)
                    if parsed is not None and parsed > 0:
                        phrase = " ".join(seq)
                        # Don't add if already captured by fractional parser
                        if not any(f in phrase for f in ["dedh", "dhai", "sawa", "paune", "saade", "डेढ़", "ढाई", "सवा", "पौने", "साढ़े"]):
                            matches.append((parsed, phrase))
            else:
                i += 1

        return matches

    def _evaluate_number_sequence(self, tokens: List[str]) -> Optional[int]:
        """Calculates total value of a compound number sequence."""
        total = 0
        current = 0
        has_number = False

        for token in tokens:
            if token == "and":
                continue
            if token in MULTIPLIERS:
                mult = MULTIPLIERS[token]
                if current == 0:
                    current = 1
                current *= mult
                total += current
                current = 0
                has_number = True
            elif token in HINDI_ENGLISH_NUMBERS:
                val = HINDI_ENGLISH_NUMBERS[token]
                current += val
                has_number = True
            elif token.isdigit():
                val = int(token)
                current += val
                has_number = True
            else:
                return None

        total += current
        return total if has_number and total > 0 else None

    def _extract_digit_amounts(self, text: str) -> List[Tuple[int, str]]:
        """Extracts direct numeric digits (e.g. '1500 rupees', '₹1,500', '1.5 lakh', 'send 500 to Ramesh')."""
        matches: List[Tuple[int, str]] = []

        # Pattern: digits optionally decimal, followed by multiplier or currency keywords
        pattern = re.compile(
            r'(?:(?:rs|inr)\s*)?(\b\d+(?:\.\d+)?)(?:(?:\s*|\b)(k\b|thousand|hazaar|hazar|lakh|lac|crore|सौ|हज़ार|हजार|लाख|करोड़))?(?:\s*(?:rupees|rupaye|rupya|rs|inr|/-|रुपये|रुपए|रु))?',
            re.IGNORECASE,
        )

        for m in pattern.finditer(text):
            digits_str = m.group(1)
            mult_str = m.group(2)

            # Avoid capturing phone numbers (10 digits) or years
            if len(digits_str) == 10 and digits_str.startswith(('6', '7', '8', '9')):
                continue

            if "." in digits_str:
                val = float(digits_str)
            else:
                val = int(digits_str)

            if mult_str:
                mult_key = mult_str.lower()
                val = int(val * MULTIPLIERS.get(mult_key, 1))
            else:
                val = int(val)

            if val >= 0:
                matches.append((val, m.group(0).strip()))

        return matches


# Global default instance
number_parser = DeterministicNumberParser()


def parse_amount(text: str, max_limit: Optional[float] = None) -> ParsedAmountResult:
    """Convenience helper to parse an amount using the deterministic parser."""
    parser = DeterministicNumberParser(max_limit=max_limit)
    return parser.parse(text)


def amount_to_words(n: int) -> str:
    """Converts integer INR amounts into written words for vocal and visual read-back."""
    if n == 0:
        return "Zero Rupees only"
    if n < 0:
        return f"Minus {amount_to_words(abs(n))}"

    ones = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
        "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"
    ]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def convert_below_thousand(num: int) -> str:
        parts = []
        if num >= 100:
            parts.append(ones[num // 100] + " Hundred")
            num %= 100
        if num >= 20:
            parts.append(tens[num // 10])
            num %= 10
        if num > 0:
            parts.append(ones[num])
        return " ".join([p for p in parts if p])

    parts = []
    # Crores (10,000,000)
    if n >= 10000000:
        cr = n // 10000000
        parts.append(convert_below_thousand(cr) + " Crore")
        n %= 10000000
    # Lakhs (100,000)
    if n >= 100000:
        lk = n // 100000
        parts.append(convert_below_thousand(lk) + " Lakh")
        n %= 100000
    # Thousands (1,000)
    if n >= 1000:
        th = n // 1000
        parts.append(convert_below_thousand(th) + " Thousand")
        n %= 1000
    # Hundreds / Remainder
    if n > 0:
        parts.append(convert_below_thousand(n))

    words = " ".join([p for p in parts if p]).strip()
    return f"{words} Rupees only"
