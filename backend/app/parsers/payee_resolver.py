"""
Deterministic payee resolver using RapidFuzz fuzzy matching for VaaniPay.
Resolves candidate names against authenticated customer contacts with strict ambiguity checks
and privacy isolation.
"""

import re
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from app.models.contact import Contact


class PayeeResolutionStatus(str, Enum):
    MATCHED = "MATCHED"                      # Score >= 85%, unambiguous
    AMBIGUOUS = "AMBIGUOUS"                  # Multiple competing contacts within 60-100%
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"  # Single candidate in 60-84% range
    UNRECOGNIZED = "UNRECOGNIZED"            # Highest score < 60%
    NOT_FOUND = "NOT_FOUND"                  # No payee name identified in input


class CandidateMatch(BaseModel):
    """Candidate contact with match score."""
    model_config = ConfigDict(from_attributes=True)

    contact_id: str
    contact_name: str
    score: float
    matched_alias: Optional[str] = None
    phone_number: Optional[str] = None
    beneficiary_account_id: Optional[str] = None


class PayeeResolutionResult(BaseModel):
    """Structured result from payee fuzzy resolution."""
    model_config = ConfigDict(from_attributes=True)

    status: PayeeResolutionStatus
    selected_contact: Optional[CandidateMatch] = None
    score: float = 0.0
    raw_query: str
    extracted_name: Optional[str] = None
    candidate_contacts: List[CandidateMatch] = []
    is_authorized_payee: bool = False
    explanation: str = ""


# Thresholds as specified in REQUIREMENTS.md
HIGH_CONFIDENCE_THRESHOLD = 85.0
CLARIFICATION_MIN_THRESHOLD = 60.0
AMBIGUITY_SCORE_DELTA = 6.0  # Scores within 6 points of each other are considered ambiguous


def extract_candidate_payee_name(text: str) -> Optional[str]:
    """
    Extracts candidate payee name substring from raw input transcripts.
    Handles English ('send to Ramesh', 'pay Ramesh') and Hinglish ('Ramesh ko paanch sau bhej do').
    """
    if not text:
        return None

    cleaned = text.strip()

    # Pattern 1: Hinglish '<name> ko ...' (e.g. 'Ramesh ko paanch sau rupaye bhej do')
    m_ko = re.search(r'^(?:please\s+)?(.*?)\s+ko\b', cleaned, re.IGNORECASE)
    if m_ko:
        cand = m_ko.group(1).strip()
        # Clean off common noise prefixes
        cand = re.sub(r'^(?:send|pay|transfer|kripya)\s+', '', cand, flags=re.IGNORECASE).strip()
        if cand:
            return cand

    # Pattern 2: English '... to <name>' (e.g. 'send 500 to Ramesh', 'transfer 1500 to Priya Sharma')
    m_to = re.search(r'\bto\s+([a-zA-Z\s\.\'-]+?)(?:\s+(?:rupees|inr|rs|\d|immediately|now))?$', cleaned, re.IGNORECASE)
    if m_to:
        cand = m_to.group(1).strip()
        if cand:
            return cand

    # Pattern 3: English 'pay <name> <amount>'
    m_pay = re.search(r'\b(?:pay|send|transfer)\s+([a-zA-Z\s\.\'-]+?)\s+(?:\d+|paanch|dedh|dhai|two)', cleaned, re.IGNORECASE)
    if m_pay:
        cand = m_pay.group(1).strip()
        if cand:
            return cand

    # If short string without verbs, treat entire string as name candidate
    words = cleaned.split()
    if len(words) <= 3 and not any(w in cleaned.lower() for w in ["rupees", "rupaye", "transfer", "bhej"]):
        return cleaned

    return None


class PayeeResolver:
    """
    Fuzzy payee matching engine enforcing contact isolation and strict confidence bounds.
    """

    @staticmethod
    def resolve(
        query: str,
        contacts: List[Contact],
        account_id: Optional[str] = None,
    ) -> PayeeResolutionResult:
        """
        Resolves query text against a specific user's contacts list.
        Enforces customer isolation: only contacts passed in are considered.
        """
        if not query or not query.strip():
            return PayeeResolutionResult(
                status=PayeeResolutionStatus.NOT_FOUND,
                raw_query=query or "",
                explanation="No query provided for payee resolution.",
            )

        extracted_name = extract_candidate_payee_name(query)
        target_name = (extracted_name if extracted_name else query).strip().lower()

        if not contacts:
            return PayeeResolutionResult(
                status=PayeeResolutionStatus.UNRECOGNIZED,
                raw_query=query,
                extracted_name=extracted_name,
                explanation="No contacts exist in the customer's address book.",
            )

        scored_candidates: List[CandidateMatch] = []

        for c in contacts:
            # Customer contact isolation verification
            if account_id and c.account_id != account_id:
                continue

            names_to_check = [c.contact_name]
            if c.aliases:
                aliases_list = [a.strip() for a in c.aliases.split(",") if a.strip()]
                names_to_check.extend(aliases_list)

            best_score = 0.0
            matched_alias = None

            for name_variant in names_to_check:
                v_clean = name_variant.lower()
                # Compute fuzzy similarity metrics
                r = fuzz.ratio(target_name, v_clean)
                ts = fuzz.token_sort_ratio(target_name, v_clean)
                tset = fuzz.token_set_ratio(target_name, v_clean)
                # Word-based token sort vs direct ratio
                current_score = max(r, ts, (tset if len(target_name) > 3 else r))

                if current_score > best_score:
                    best_score = current_score
                    matched_alias = name_variant

            if best_score > 0:
                scored_candidates.append(
                    CandidateMatch(
                        contact_id=c.id,
                        contact_name=c.contact_name,
                        score=round(best_score, 1),
                        matched_alias=matched_alias,
                        phone_number=c.phone_number,
                        beneficiary_account_id=c.beneficiary_account_id,
                    )
                )

        if not scored_candidates:
            return PayeeResolutionResult(
                status=PayeeResolutionStatus.UNRECOGNIZED,
                raw_query=query,
                extracted_name=extracted_name,
                explanation=f"Payee '{target_name}' could not be matched with any contact.",
            )

        # Sort candidates by score descending
        scored_candidates.sort(key=lambda x: x.score, reverse=True)
        top_match = scored_candidates[0]

        # Case 1: Unrecognized / New Payee (< 60.0)
        if top_match.score < CLARIFICATION_MIN_THRESHOLD:
            return PayeeResolutionResult(
                status=PayeeResolutionStatus.UNRECOGNIZED,
                score=top_match.score,
                raw_query=query,
                extracted_name=extracted_name,
                candidate_contacts=scored_candidates[:3],
                is_authorized_payee=False,
                explanation=(
                    f"Payee '{extracted_name or query}' was not recognized in your saved contacts "
                    f"(match score {top_match.score}% < {CLARIFICATION_MIN_THRESHOLD}%)."
                ),
            )

        # Check for ambiguity among top candidates (close competing matches >= 60%)
        competing = [
            c for c in scored_candidates
            if c.score >= CLARIFICATION_MIN_THRESHOLD and (top_match.score - c.score) <= AMBIGUITY_SCORE_DELTA
        ]

        # Case 2: Ambiguous (Multiple contacts with close competing scores)
        if len(competing) > 1:
            names = [c.contact_name for c in competing]
            return PayeeResolutionResult(
                status=PayeeResolutionStatus.AMBIGUOUS,
                score=top_match.score,
                raw_query=query,
                extracted_name=extracted_name,
                candidate_contacts=competing,
                is_authorized_payee=False,
                explanation=f"Ambiguous payee name. Did you mean {' or '.join(names)}?",
            )

        # Case 3: Clarification Needed (Single candidate in 60 - 84% range)
        if CLARIFICATION_MIN_THRESHOLD <= top_match.score < HIGH_CONFIDENCE_THRESHOLD:
            return PayeeResolutionResult(
                status=PayeeResolutionStatus.CLARIFICATION_NEEDED,
                selected_contact=top_match,
                score=top_match.score,
                raw_query=query,
                extracted_name=extracted_name,
                candidate_contacts=[top_match],
                is_authorized_payee=False,
                explanation=f"Did you mean {top_match.contact_name}? (Confidence: {top_match.score}%)",
            )

        # Case 4: High Confidence Match (>= 85.0%)
        return PayeeResolutionResult(
            status=PayeeResolutionStatus.MATCHED,
            selected_contact=top_match,
            score=top_match.score,
            raw_query=query,
            extracted_name=extracted_name,
            candidate_contacts=[top_match],
            is_authorized_payee=True,
            explanation=f"Successfully resolved to {top_match.contact_name} (Confidence: {top_match.score}%).",
        )

    @classmethod
    def resolve_for_account(
        cls,
        db: Session,
        account_id: str,
        query: str,
    ) -> PayeeResolutionResult:
        """
        Database helper: fetches only the authenticated customer's contacts
        and resolves the payee. Ensures strict isolation.
        """
        user_contacts = db.query(Contact).filter(Contact.account_id == account_id).all()
        return cls.resolve(query=query, contacts=user_contacts, account_id=account_id)
