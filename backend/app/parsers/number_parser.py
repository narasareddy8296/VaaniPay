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
    "shunya": 0, "zero": 0,
    "ek": 1, "one": 1,
    "do": 2, "two": 2,
    "teen": 3, "tin": 3, "three": 3,
    "chaar": 4, "char": 4, "four": 4,
    "paanch": 5, "panch": 5, "five": 5,
    "chhah": 6, "che": 6, "chhe": 6, "six": 6,
    "saat": 7, "sat": 7, "seven": 7,
    "aath": 8, "ath": 8, "eight": 8,
    "nau": 9, "no": 9, "nine": 9,
    # 10 - 19
    "das": 10, "dus": 10, "ten": 10,
    "gyarah": 11, "gyara": 11, "eleven": 11,
    "baarah": 12, "bara": 12, "twelve": 12,
    "terah": 13, "tera": 13, "thirteen": 13,
    "chaudah": 14, "chouda": 14, "fourteen": 14,
    "pandrah": 15, "pandra": 15, "fifteen": 15,
    "solah": 16, "sola": 16, "sixteen": 16,
    "satrah": 17, "satra": 17, "seventeen": 17,
    "atharah": 18, "athara": 18, "eighteen": 18,
    "unnees": 19, "unnis": 19, "nineteen": 19,
    # 20 - 90
    "bees": 20, "bis": 20, "twenty": 20,
    "pachees": 25, "pachis": 25, "twenty five": 25, "twenty-five": 25,
    "tees": 30, "tis": 30, "thirty": 30,
    "chaalees": 40, "chalis": 40, "forty": 40,
    "pachaas": 50, "pachas": 50, "fifty": 50,
    "saath": 60, "sath": 60, "sixty": 60,
    "sattar": 70, "seventy": 70,
    "assi": 80, "eighty": 80,
    "nabbe": 90, "navve": 90, "ninety": 90,
}

MULTIPLIERS = {
    "sau": 100, "so": 100, "sou": 100, "hundred": 100,
    "hazaar": 1000, "hazar": 1000, "hajar": 1000, "thousand": 1000, "k": 1000,
    "lakh": 100000, "lac": 100000, "lakhs": 100000, "lacs": 100000,
    "crore": 10000000, "cr": 10000000, "crores": 10000000,
}


def _clean_text(text: str) -> str:
    """Standardizes input string: lowercases, strips punctuation, and normalizes currency tags."""
    if not text:
        return ""
    # Normalize unicode symbols (e.g. ₹ to ' rs ')
    s = text.replace("₹", " rs ")
    s = s.lower()
    # Strip commas inside numbers (e.g. 1,500 -> 1500)
    s = re.sub(r'(?<=\d),(?=\d)', '', s)
    # Mask Indian mobile phone numbers (10 digits starting with 6-9) so they don't get parsed as amounts
    s = re.sub(r'\b(?:\+91|91)?[6-9]\d{9}\b', ' [PHONE] ', s)
    # Strip punctuation (keep hyphens and alphanumeric characters)
    s = re.sub(r'[^\w\s\-]', ' ', s)
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
        m_ko = re.search(r'^(.*?)\s+ko\b', text)
        if m_ko:
            payee_regions.append(m_ko.group(1))
        # In English: phrase after 'to' (e.g. '... to ramesh 2')
        m_to = re.search(r'\bto\s+([a-zA-Z0-9_\s]+)$', text)
        if m_to:
            payee_regions.append(m_to.group(1))

        # Helper to check if a phrase is inside an identified payee region
        def is_in_payee_region(phrase: str) -> bool:
            clean_phrase = phrase.strip()
            # If the phrase has explicit currency or multiplier, it is definitely an amount, not a payee!
            if any(k in clean_phrase for k in ["rupee", "rupay", "rs", "inr", "sau", "hazaar", "hazar", "lakh", "lac", "crore", "thousand", "hundred"]):
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
            has_strong_marker = any(k in phrase_clean for k in [
                "sau", "so", "hazaar", "hazar", "hajar", "thousand", "lakh", "lac", "crore",
                "dedh", "dhai", "sawa", "paune", "saade",
                "rupee", "rupay", "rs", "inr", "k"
            ])
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

        # Deduplicate while preserving order
        seen = set()
        unique_results = []
        for val, phrase in candidates_to_use:
            key = (val, phrase)
            if key not in seen:
                seen.add(key)
                unique_results.append((val, phrase))

        return unique_results

    def _extract_fractional_amounts(self, text: str) -> List[Tuple[int, str]]:
        """Parses colloquial Hindi fractional expressions."""
        matches: List[Tuple[int, str]] = []

        # 1. Dedh (<unit>) -> 1.5 * unit (e.g. dedh sau = 150, dedh hazaar = 1500, dedh lakh = 150000)
        for m in re.finditer(
            r'\b(?:dedh|dhedh|deydh|dadh)\s+(sau|so|hazaar|hazar|hajar|thousand|lakh|lac|crore)\b',
            text,
        ):
            unit_str = m.group(1)
            unit_val = MULTIPLIERS.get(unit_str, 1000)
            amount = int(1.5 * unit_val)
            matches.append((amount, m.group(0)))

        # 2. Dhai (<unit>) -> 2.5 * unit (e.g. dhai sau = 250, dhai hazaar = 2500, dhai lakh = 250000)
        for m in re.finditer(
            r'\b(?:dhai|dhaai|dhaee|adhai)\s+(sau|so|hazaar|hazar|hajar|thousand|lakh|lac|crore)\b',
            text,
        ):
            unit_str = m.group(1)
            unit_val = MULTIPLIERS.get(unit_str, 100)
            amount = int(2.5 * unit_val)
            matches.append((amount, m.group(0)))

        # 3. Sawa (<N> <unit>) -> (N + 0.25) * unit (e.g. sawa do lakh = 2.25 * 100,000 = 225,000)
        for m in re.finditer(
            r'\b(?:sawa|sava|sawwa)\s+([a-zA-Z]+|\d+)\s+(sau|so|hazaar|hazar|hajar|thousand|lakh|lac|crore)\b',
            text,
        ):
            num_val = _word_to_int(m.group(1))
            unit_val = MULTIPLIERS.get(m.group(2))
            if num_val is not None and unit_val is not None:
                amount = int((num_val + 0.25) * unit_val)
                matches.append((amount, m.group(0)))

        # 3b. Standalone Sawa (<unit>) -> 1.25 * unit (e.g. sawa hazaar = 1250, sawa sau = 125)
        for m in re.finditer(
            r'\b(?:sawa|sava|sawwa)\s+(sau|so|hazaar|hazar|hajar|thousand|lakh|lac|crore)\b',
            text,
        ):
            unit_val = MULTIPLIERS.get(m.group(1))
            if unit_val is not None:
                amount = int(1.25 * unit_val)
                matches.append((amount, m.group(0)))

        # 4. Paune (<N> <unit>) -> (N - 0.25) * unit (e.g. paune teen hazaar = 2.75 * 1000 = 2750)
        for m in re.finditer(
            r'\b(?:paune|pone|pawne|pawnay)\s+([a-zA-Z]+|\d+)\s+(sau|so|hazaar|hazar|hajar|thousand|lakh|lac|crore)\b',
            text,
        ):
            num_val = _word_to_int(m.group(1))
            unit_val = MULTIPLIERS.get(m.group(2))
            if num_val is not None and unit_val is not None:
                amount = int((num_val - 0.25) * unit_val)
                matches.append((amount, m.group(0)))

        # 4b. Standalone Paune (<unit>) -> 0.75 * unit (e.g. paune hazaar = 750, paune sau = 75)
        for m in re.finditer(
            r'\b(?:paune|pone|pawne|pawnay)\s+(sau|so|hazaar|hazar|hajar|thousand|lakh|lac|crore)\b',
            text,
        ):
            unit_val = MULTIPLIERS.get(m.group(1))
            if unit_val is not None:
                amount = int(0.75 * unit_val)
                matches.append((amount, m.group(0)))

        # 5. Saade (<N> <unit>) -> (N + 0.5) * unit (e.g. saade teen hazaar = 3500)
        for m in re.finditer(
            r'\b(?:saade|sadhe|sade)\s+([a-zA-Z]+|\d+)\s+(sau|so|hazaar|hazar|hajar|thousand|lakh|lac|crore)\b',
            text,
        ):
            num_val = _word_to_int(m.group(1))
            unit_val = MULTIPLIERS.get(m.group(2))
            if num_val is not None and unit_val is not None:
                amount = int((num_val + 0.5) * unit_val)
                matches.append((amount, m.group(0)))

        return matches

    def _extract_word_amounts(self, text: str) -> List[Tuple[int, str]]:
        """Parses composite words like 'two thousand paanch sau' or 'paanch sau'."""
        matches: List[Tuple[int, str]] = []

        # Replace auxiliary verb phrases where 'do' means 'give/send', not number 2
        normalized_text = re.sub(r'\b(?:bhej|kar|de)\s+do\b', ' transfer ', text)

        all_tokens = set(HINDI_ENGLISH_NUMBERS.keys()) | set(MULTIPLIERS.keys()) | {"and"}
        words = normalized_text.split()

        i = 0
        while i < len(words):
            if words[i] in all_tokens or words[i].isdigit():
                start = i
                while i < len(words) and (words[i] in all_tokens or words[i].isdigit()):
                    i += 1
                seq = words[start:i]
                # Filter out pure digits without any word multiplier (pure digits handled by _extract_digit_amounts)
                has_word_num = any(t in HINDI_ENGLISH_NUMBERS or t in MULTIPLIERS for t in seq)
                if has_word_num:
                    parsed = self._evaluate_number_sequence(seq)
                    if parsed is not None and parsed > 0:
                        phrase = " ".join(seq)
                        # Don't add if already captured by fractional parser
                        if not any(f in phrase for f in ["dedh", "dhai", "sawa", "paune", "saade"]):
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
        """Extracts direct numeric digits (e.g. '1500 rupees', '₹1,500', 'send 500 to Ramesh')."""
        matches: List[Tuple[int, str]] = []

        # Pattern: digits optionally followed by multiplier (with word boundary) or currency keywords
        pattern = re.compile(
            r'(?:(?:rs|inr)\s*)?(\b\d+)(?:(?:\s*|\b)(k\b|thousand|hazaar|hazar|lakh|lac|crore))?(?:\s*(?:rupees|rupaye|rupya|rs|inr|/-))?',
            re.IGNORECASE,
        )

        for m in pattern.finditer(text):
            digits_str = m.group(1)
            mult_str = m.group(2)

            val = int(digits_str)
            if mult_str:
                mult_key = mult_str.lower()
                val = val * MULTIPLIERS.get(mult_key, 1)

            # Avoid capturing phone numbers (10 digits) or years
            if len(digits_str) == 10 and digits_str.startswith(('6', '7', '8', '9')):
                continue

            matches.append((val, m.group(0)))

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
