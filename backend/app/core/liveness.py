"""
Server-side challenge-response liveness detection for VaaniPay.
Generates single-use, time-limited cryptographic challenges bound to the session and customer.
Prevents audio replay attacks while maintaining data privacy.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple
from pydantic import BaseModel, ConfigDict
from app.core.config import get_settings
from app.models.session import PaymentSession

LIVENESS_SALT = "vaanipay_liveness_salt_2026"


class LivenessStatus(str, Enum):
    PASSED = "PASSED"
    EXPIRED = "EXPIRED"
    MISMATCH = "MISMATCH"
    REPLAYED = "REPLAYED"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    TYPED_FALLBACK = "TYPED_FALLBACK"


class LivenessResult(BaseModel):
    """Result of liveness challenge verification."""
    model_config = ConfigDict(from_attributes=True)

    status: LivenessStatus
    is_valid: bool
    is_live_speech_proven: bool
    session_id: str
    account_id: str
    explanation: str


def _hash_challenge(session_id: str, account_id: str, challenge_digits: str) -> str:
    """Computes deterministic hash of challenge digits without storing plaintext."""
    clean_digits = "".join(challenge_digits.split())
    payload = f"{LIVENESS_SALT}:{session_id}:{account_id}:{clean_digits}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_liveness_challenge(
    session_id: str,
    account_id: str,
    ttl_seconds: Optional[int] = None,
) -> Tuple[str, str, datetime]:
    """
    Generates a cryptographically random 3-digit challenge code.
    Returns:
        challenge_digits: Spoken/displayed prompt (e.g., '4 7 2')
        challenge_hash: SHA-256 hash stored in session to prevent accidental log leaks
        expires_at: Expiration timestamp (default: 30 seconds TTL)
    """
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.LIVENESS_CHALLENGE_EXPIRY_SECONDS

    # Generate 3 distinct or random single digits
    digits = [str(secrets.randbelow(10)) for _ in range(3)]
    challenge_digits = " ".join(digits)

    challenge_hash = _hash_challenge(session_id, account_id, challenge_digits)
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)

    return challenge_digits, challenge_hash, expires_at


def verify_liveness_challenge(
    session: PaymentSession,
    account_id: str,
    response_digits: Optional[str],
    channel: str = "VOICE",
) -> LivenessResult:
    """
    Verifies customer challenge response.
    Guarantees:
    - Challenge is single-use: cleared immediately upon attempt to defeat replay attacks.
    - Bound strictly to session and customer.
    - Rejects expired challenges (TTL check).
    - Rejects typed input from claiming proof of live human speech.
    """
    if not session.liveness_challenge:
        return LivenessResult(
            status=LivenessStatus.REPLAYED,
            is_valid=False,
            is_live_speech_proven=False,
            session_id=session.id,
            account_id=account_id,
            explanation="Challenge has already been consumed or was never issued. Replay rejected.",
        )

    # Validate session customer ownership
    if session.account_id != account_id:
        # Invalidate challenge immediately
        session.liveness_challenge = None
        return LivenessResult(
            status=LivenessStatus.SESSION_MISMATCH,
            is_valid=False,
            is_live_speech_proven=False,
            session_id=session.id,
            account_id=account_id,
            explanation="Challenge session ownership mismatch.",
        )

    # Check TTL Expiration
    now = datetime.utcnow()
    if session.challenge_expires_at and now > session.challenge_expires_at:
        session.liveness_challenge = None
        return LivenessResult(
            status=LivenessStatus.EXPIRED,
            is_valid=False,
            is_live_speech_proven=False,
            session_id=session.id,
            account_id=account_id,
            explanation="Liveness challenge expired (exceeded 30 seconds TTL).",
        )

    if not response_digits or not response_digits.strip():
        session.liveness_challenge = None
        return LivenessResult(
            status=LivenessStatus.MISMATCH,
            is_valid=False,
            is_live_speech_proven=False,
            session_id=session.id,
            account_id=account_id,
            explanation="Empty challenge response received.",
        )

    # Single-use consumption: extract stored hash and clear from session immediately
    stored_hash = session.liveness_challenge
    session.liveness_challenge = None

    # Compute expected hash from customer response
    response_clean = "".join(response_digits.split())
    candidate_hash = _hash_challenge(session.id, account_id, response_clean)

    if candidate_hash != stored_hash:
        return LivenessResult(
            status=LivenessStatus.MISMATCH,
            is_valid=False,
            is_live_speech_proven=False,
            session_id=session.id,
            account_id=account_id,
            explanation="Incorrect challenge digits provided.",
        )

    # Challenge response text matched!
    # SAFETY INVARIANT: Typed text does NOT prove live human voice.
    is_live_speech = (channel.upper() == "VOICE")
    status = LivenessStatus.PASSED if is_live_speech else LivenessStatus.TYPED_FALLBACK

    explanation = (
        "Liveness challenge passed via live voice."
        if is_live_speech
        else "Liveness challenge text matched via typed fallback. Speech liveness unverified."
    )

    return LivenessResult(
        status=status,
        is_valid=True,
        is_live_speech_proven=is_live_speech,
        session_id=session.id,
        account_id=account_id,
        explanation=explanation,
    )
