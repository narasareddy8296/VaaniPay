"""
Unit tests for server-side challenge-response liveness detection.
Verifies single-use enforcement, 30s TTL expiry, replay rejection,
session binding, and typed-fallback speech limitations.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.session import PaymentSession
from app.core.liveness import (
    generate_liveness_challenge,
    verify_liveness_challenge,
    LivenessStatus,
)


def test_challenge_generation_is_random_and_hashed():
    """Challenge digits are generated server-side and protected via SHA-256 hash."""
    digits1, hash1, exp1 = generate_liveness_challenge("sess_1", "acc_priya", ttl_seconds=30)
    digits2, hash2, exp2 = generate_liveness_challenge("sess_1", "acc_priya", ttl_seconds=30)

    # Challenge format: 3 spaced digits
    assert len(digits1.split()) == 3
    for d in digits1.split():
        assert d.isdigit()

    # Hash is SHA-256 (64 hex characters)
    assert len(hash1) == 64
    assert hash1 != digits1  # Plaintext is NEVER stored
    assert exp1 > datetime.utcnow()


def test_valid_challenge_passes_voice_liveness(db_session: Session):
    """Accurately repeating challenge digits via voice passes liveness."""
    seed_database(db_session)
    session = PaymentSession(id="sess_live_1", account_id="acc_priya", current_state="LIVENESS")
    db_session.add(session)
    db_session.commit()

    digits, ch_hash, expires_at = generate_liveness_challenge(session.id, "acc_priya", ttl_seconds=30)
    session.liveness_challenge = ch_hash
    session.challenge_expires_at = expires_at
    db_session.commit()

    result = verify_liveness_challenge(session, "acc_priya", digits, channel="VOICE")
    assert result.status == LivenessStatus.PASSED
    assert result.is_valid is True
    assert result.is_live_speech_proven is True


def test_challenge_is_single_use_and_rejects_replay(db_session: Session):
    """
    SAFETY INVARIANT: Challenge is consumed immediately on verification attempt.
    Submitting the same response a second time MUST be rejected as a replay attack.
    """
    seed_database(db_session)
    session = PaymentSession(id="sess_live_2", account_id="acc_priya", current_state="LIVENESS")
    db_session.add(session)
    db_session.commit()

    digits, ch_hash, expires_at = generate_liveness_challenge(session.id, "acc_priya", ttl_seconds=30)
    session.liveness_challenge = ch_hash
    session.challenge_expires_at = expires_at
    db_session.commit()

    # First attempt: succeeds
    res1 = verify_liveness_challenge(session, "acc_priya", digits, channel="VOICE")
    assert res1.is_valid is True
    assert session.liveness_challenge is None  # Challenge cleared!

    # Second attempt (replay of same audio): REJECTED
    res2 = verify_liveness_challenge(session, "acc_priya", digits, channel="VOICE")
    assert res2.status == LivenessStatus.REPLAYED
    assert res2.is_valid is False


def test_expired_challenge_is_rejected(db_session: Session):
    """Challenges exceeding the 30-second TTL are rejected."""
    seed_database(db_session)
    session = PaymentSession(id="sess_live_3", account_id="acc_priya", current_state="LIVENESS")
    db_session.add(session)
    db_session.commit()

    digits, ch_hash, _ = generate_liveness_challenge(session.id, "acc_priya", ttl_seconds=30)
    session.liveness_challenge = ch_hash
    # Set expiration in the past (e.g. 5 seconds ago)
    session.challenge_expires_at = datetime.utcnow() - timedelta(seconds=5)
    db_session.commit()

    result = verify_liveness_challenge(session, "acc_priya", digits, channel="VOICE")
    assert result.status == LivenessStatus.EXPIRED
    assert result.is_valid is False
    assert session.liveness_challenge is None  # Cleared on failure


def test_wrong_customer_session_mismatch_rejected(db_session: Session):
    """A challenge bound to Priya cannot be submitted by Ramesh."""
    seed_database(db_session)
    session = PaymentSession(id="sess_live_4", account_id="acc_priya", current_state="LIVENESS")
    db_session.add(session)
    db_session.commit()

    digits, ch_hash, expires_at = generate_liveness_challenge(session.id, "acc_priya", ttl_seconds=30)
    session.liveness_challenge = ch_hash
    session.challenge_expires_at = expires_at
    db_session.commit()

    result = verify_liveness_challenge(session, "acc_ramesh", digits, channel="VOICE")
    assert result.status == LivenessStatus.SESSION_MISMATCH
    assert result.is_valid is False


def test_typed_fallback_does_not_prove_live_speech(db_session: Session):
    """
    SAFETY INVARIANT: Typed input can match challenge digits, but CANNOT be
    claimed as proof of live human speech.
    """
    seed_database(db_session)
    session = PaymentSession(id="sess_live_5", account_id="acc_priya", current_state="LIVENESS")
    db_session.add(session)
    db_session.commit()

    digits, ch_hash, expires_at = generate_liveness_challenge(session.id, "acc_priya", ttl_seconds=30)
    session.liveness_challenge = ch_hash
    session.challenge_expires_at = expires_at
    db_session.commit()

    result = verify_liveness_challenge(session, "acc_priya", digits, channel="TYPED")
    assert result.status == LivenessStatus.TYPED_FALLBACK
    assert result.is_valid is True
    # Speech liveness must be strictly False for typed fallback!
    assert result.is_live_speech_proven is False
    assert "speech liveness unverified" in result.explanation.lower()
