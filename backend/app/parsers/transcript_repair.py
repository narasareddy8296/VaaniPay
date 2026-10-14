"""
Deterministic rule-based transcript repair stage for VaaniPay.
Maintains original speech transcripts untouched for auditing and compliance,
while normalizing a separate copy to resolve common ASR phonetic variations,
spacing issues, and dialectal Hinglish phrasing.
Zero external LLM dependencies. Strictly deterministic.
"""

import re
from typing import Tuple, List, Dict


class TranscriptRepairService:
    """
    Deterministic phonetic and lexical normalizer for Hindi/Hinglish speech transcripts.
    Guarantees:
    - Original raw transcript is never overwritten or altered.
    - Deterministic dictionary repairs known ASR errors and spacing merges.
    - Never invents numbers or turns uncertain gibberish into confident payments.
    """

    # Spacing fixes: ASR engines frequently merge numbers, fractions, and units
    SPACING_PATTERNS = [
        # sawa2 / sava2 -> sawa 2 / sava 2
        (re.compile(r'\b(sawa|sava|sawwa|सवा)(\d+)\b', re.IGNORECASE), r'\1 \2'),
        # dedhhazaar / dedhhajar -> dedh hazaar
        (re.compile(r'\b(dedh|dhedh|derh|deydh)(hazaar|hazar|hajar|sau|so|lakh|lac)\b', re.IGNORECASE), r'\1 \2'),
        # dhaisau / dhaaso -> dhai sau
        (re.compile(r'\b(dhai|dhaai|dhaee|adhai)(sau|so|hazaar|hazar|lakh|lac)\b', re.IGNORECASE), r'\1 \2'),
        # sawadolakh -> sawa do lakh
        (re.compile(r'\b(sawa|sava|sawwa)(do|teen|chaar|panch|paanch)(lakh|lac|hazaar|hazar|sau)\b', re.IGNORECASE), r'\1 \2 \3'),
        # sawa2lakh -> sawa 2 lakh
        (re.compile(r'\b(sawa|sava|sawwa)(\d+)(lakh|lac|hazaar|hazar|sau)\b', re.IGNORECASE), r'\1 \2 \3'),
        # paanchsau -> paanch sau
        (re.compile(r'\b(ek|do|teen|chaar|paanch|chhah|saat|aath|nau|das)(sau|so|hazaar|hazar|lakh)\b', re.IGNORECASE), r'\1 \2'),
        # 500rupaye -> 500 rupaye
        (re.compile(r'(\d+)(rupaye|rupees|rupya|rs|inr)\b', re.IGNORECASE), r'\1 \2'),
        # bhejdo -> bhej do
        (re.compile(r'\b(bhej|kar|de)(do|dena|karo|dijiye)\b', re.IGNORECASE), r'\1 \2'),
    ]

    # Deterministic dictionary for ASR phonetic misrecognitions
    LEXICAL_REPLACEMENTS = [
        # Lakh variants
        (re.compile(r'\b(?:laakh|laak|laac|lakhs|laakhs|lacs)\b', re.IGNORECASE), 'lakh'),
        # Thousand / Hazaar variants
        (re.compile(r'\b(?:hazaarr|hazaara|hazarr|hajar|hazaari)\b', re.IGNORECASE), 'hazaar'),
        # Hundred / Sau variants
        (re.compile(r'\b(?:sou)\b', re.IGNORECASE), 'sau'),
        # Dedh (1.5) variants
        (re.compile(r'\b(?:dhedh|derh|deydh|dadh)\b', re.IGNORECASE), 'dedh'),
        # Dhai (2.5) variants
        (re.compile(r'\b(?:dhaai|dhaee|dhayi|adhai)\b', re.IGNORECASE), 'dhai'),
        # Sawa (+0.25) variants
        (re.compile(r'\b(?:sawwa|savaa)\b', re.IGNORECASE), 'sawa'),
        # Paune (-0.25) variants
        (re.compile(r'\b(?:pone|pawne|pawnay)\b', re.IGNORECASE), 'paune'),
        # Saade (+0.5) variants
        (re.compile(r'\b(?:sadhe|sade)\b', re.IGNORECASE), 'saade'),
        # Paanch (5) variants
        (re.compile(r'\b(?:panch)\b', re.IGNORECASE), 'paanch'),
        # Currency token normalization
        (re.compile(r'\b(?:rupay|rupya|rupee|rupees|rs\.?|inr|/-)\b', re.IGNORECASE), 'rupaye'),
    ]

    @classmethod
    def repair(cls, raw_transcript: str) -> Tuple[str, List[Dict[str, str]]]:
        """
        Normalizes a raw transcript copy for parsing while tracking all applied repairs.
        Returns:
            Tuple[repaired_transcript, repairs_applied]
        """
        if not raw_transcript or not raw_transcript.strip():
            return "", []

        repairs_applied: List[Dict[str, str]] = []
        text = raw_transcript.strip()

        # 1. Spacing normalizations
        for pattern, repl in cls.SPACING_PATTERNS:
            if pattern.search(text):
                before = text
                text = pattern.sub(repl, text)
                if before != text:
                    repairs_applied.append({"type": "spacing", "before": before, "after": text})

        # 2. Lexical phonetic substitutions
        for pattern, repl in cls.LEXICAL_REPLACEMENTS:
            if pattern.search(text):
                before = text
                text = pattern.sub(repl, text)
                if before != text:
                    repairs_applied.append({"type": "lexical", "before": before, "after": text})

        # 3. Clean up multiple whitespaces
        text = " ".join(text.split())

        return text, repairs_applied
