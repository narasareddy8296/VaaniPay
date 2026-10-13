"""
Risk-based PIN Step-Up Authentication and Lockout Manager for VaaniPay.
Enforces secure salted verification, 3-attempt brute-force lockout,
and transactional binding to prevent bypass.
"""

import hashlib
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.account import Account
from app.models.session import PaymentSession
from app.models.contact import Contact
from app.services.antispoof_service import AntiSpoofOutcome

DEFAULT_PIN_SALT = "vaanipay_mock_salt_2026"


class PinStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INCORRECT = "INCORRECT"
    LOCKED_OUT = "LOCKED_OUT"
    ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
    SESSION_MISMATCH = "SESSION_MISMATCH"


class PinVerificationResult(BaseModel):
    """Result of step-up PIN verification."""
    model_config = ConfigDict(from_attributes=True)

    status: PinStatus
    is_success: bool
    is_locked: bool
    remaining_attempts: int
    explanation: str
    audit_data: Dict[str, Any] = {}


class PinRequirementResult(BaseModel):
    """Evaluation of whether step-up PIN is required."""
    model_config = ConfigDict(from_attributes=True)

    requires_pin: bool
    reasons: List[str] = []
    threshold: float
    amount: Optional[float] = None
    is_new_payee: bool = False
    spoof_outcome: Optional[str] = None


try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHashError
    _argon2_hasher = PasswordHasher(
        time_cost=3,
        memory_cost=65536,  # 64 MiB
        parallelism=4,
        hash_len=32,
        salt_len=16,
    )
except ImportError:
    _argon2_hasher = None


class PinSecurityManager:
    """Manages PIN hashing, step-up requirements, and brute-force lockout."""

    @staticmethod
    def hash_pin(pin: str) -> str:
        """
        Computes an Argon2id hash. NEVER stores or logs plaintext PINs.
        Argon2id provides state-of-the-art resistance to GPU/ASIC brute forcing.
        """
        clean_pin = pin.strip()
        if _argon2_hasher:
            return _argon2_hasher.hash(clean_pin)
        # Fallback scrypt if argon2-cffi is somehow not found
        import os
        salt = os.urandom(16)
        kdf = hashlib.scrypt(clean_pin.encode(), salt=salt, n=16384, r=8, p=1)
        return f"scrypt${salt.hex()}${kdf.hex()}"

    @staticmethod
    def verify_pin_hash(submitted_pin: str, stored_hash: Optional[str]) -> bool:
        """
        Verifies submitted PIN against stored hash in constant time using Argon2id.
        Gracefully handles legacy hashes during database migration.
        """
        if not stored_hash or not submitted_pin:
            return False
        clean_pin = submitted_pin.strip()

        # 1. Argon2id verification
        if stored_hash.startswith("$argon2id$") and _argon2_hasher:
            try:
                return _argon2_hasher.verify(stored_hash, clean_pin)
            except (VerifyMismatchError, InvalidHashError):
                return False

        # 2. scrypt verification
        if stored_hash.startswith("scrypt$"):
            try:
                _, salt_hex, kdf_hex = stored_hash.split("$")
                salt = bytes.fromhex(salt_hex)
                expected_kdf = bytes.fromhex(kdf_hex)
                actual_kdf = hashlib.scrypt(clean_pin.encode(), salt=salt, n=16384, r=8, p=1)
                import hmac
                return hmac.compare_digest(actual_kdf, expected_kdf)
            except Exception:
                return False

        # 3. Fallback for legacy salted SHA-256 hashes during migration
        import hmac
        legacy_payload = f"{DEFAULT_PIN_SALT}_{clean_pin}"
        legacy_hash = hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy_hash, stored_hash)

    @staticmethod
    def evaluate_step_up_needed(
        amount: Optional[float],
        payee_contact: Optional[Contact],
        antispoof_outcome: Optional[AntiSpoofOutcome],
        channel: str = "VOICE",
    ) -> PinRequirementResult:
        """
        Evaluates risk rules to determine if PIN step-up is mandatory:
        1. Amount > PIN_STEP_UP_THRESHOLD (₹2,000)
        2. New or non-frequent payee
        3. Audio anti-spoof in GREY_ZONE or UNAVAILABLE
        4. Typed input fallback (since voice liveness was unproven)
        """
        settings = get_settings()
        reasons: List[str] = []
        is_new_payee = False

        # 1. Amount threshold check
        if amount is not None and amount > settings.PIN_STEP_UP_THRESHOLD:
            reasons.append(
                f"Transaction amount ₹{amount:,.2f} exceeds PIN threshold of ₹{settings.PIN_STEP_UP_THRESHOLD:,.2f}."
            )

        # 2. Payee status check
        if payee_contact is None or not payee_contact.is_frequent or payee_contact.beneficiary_account_id is None:
            is_new_payee = True
            reasons.append("Payee is not in pre-verified frequent contacts list (New Payee).")

        # 3. Audio acoustic risk check
        if antispoof_outcome in (AntiSpoofOutcome.GREY_ZONE, AntiSpoofOutcome.UNAVAILABLE):
            reasons.append(f"Acoustic verification status requires step-up ({antispoof_outcome.value}).")

        # 4. Typed channel fallback
        if channel.upper() == "TYPED":
            reasons.append("Typed input fallback utilized; speech liveness unverified.")

        requires_pin = len(reasons) > 0

        return PinRequirementResult(
            requires_pin=requires_pin,
            reasons=reasons,
            threshold=settings.PIN_STEP_UP_THRESHOLD,
            amount=amount,
            is_new_payee=is_new_payee,
            spoof_outcome=antispoof_outcome.value if antispoof_outcome else None,
        )

    @staticmethod
    def verify_pin(
        session: PaymentSession,
        account: Account,
        submitted_pin: Optional[str],
        db: Session,
    ) -> PinVerificationResult:
        """
        Verifies customer PIN against account hash.
        Enforces 3-attempt lockout and binds to pending transaction.
        """
        settings = get_settings()
        max_attempts = settings.PIN_MAX_FAILED_ATTEMPTS

        # Check account lock status
        if account.is_locked:
            return PinVerificationResult(
                status=PinStatus.LOCKED_OUT,
                is_success=False,
                is_locked=True,
                remaining_attempts=0,
                explanation="Account is locked due to repeated security failures.",
                audit_data={"account_id": account.id, "reason": "PREVIOUS_LOCKOUT"},
            )

        if not account.is_active:
            return PinVerificationResult(
                status=PinStatus.ACCOUNT_INACTIVE,
                is_success=False,
                is_locked=False,
                remaining_attempts=0,
                explanation="Account is inactive.",
                audit_data={"account_id": account.id},
            )

        # Validate session ownership
        if session.account_id != account.id:
            return PinVerificationResult(
                status=PinStatus.SESSION_MISMATCH,
                is_success=False,
                is_locked=account.is_locked,
                remaining_attempts=max(0, max_attempts - session.failed_pin_attempts),
                explanation="Session and account ownership mismatch.",
                audit_data={"session_account": session.account_id, "attempted_account": account.id},
            )

        # Check if already locked out on session attempts
        if session.failed_pin_attempts >= max_attempts:
            account.is_locked = True
            db.commit()
            return PinVerificationResult(
                status=PinStatus.LOCKED_OUT,
                is_success=False,
                is_locked=True,
                remaining_attempts=0,
                explanation="Maximum PIN attempts exceeded. Account is now locked.",
                audit_data={"attempts": session.failed_pin_attempts, "event": "LOCKOUT_TRIGGERED"},
            )

        # Verify PIN match
        is_match = PinSecurityManager.verify_pin_hash(submitted_pin or "", account.hashed_pin)

        if is_match:
            # Reset session failed attempts on success
            session.failed_pin_attempts = 0
            db.commit()
            return PinVerificationResult(
                status=PinStatus.VERIFIED,
                is_success=True,
                is_locked=False,
                remaining_attempts=max_attempts,
                explanation="PIN step-up successfully verified.",
                audit_data={
                    "account_id": account.id,
                    "session_id": session.id,
                    "event": "PIN_VERIFIED",
                },
            )

        # Incorrect PIN entered
        session.failed_pin_attempts += 1
        remaining = max(0, max_attempts - session.failed_pin_attempts)

        if session.failed_pin_attempts >= max_attempts:
            account.is_locked = True
            db.commit()
            return PinVerificationResult(
                status=PinStatus.LOCKED_OUT,
                is_success=False,
                is_locked=True,
                remaining_attempts=0,
                explanation=f"Incorrect PIN. Maximum {max_attempts} attempts reached. Account is now locked.",
                audit_data={
                    "account_id": account.id,
                    "session_id": session.id,
                    "event": "LOCKOUT_ENFORCED",
                },
            )

        db.commit()
        return PinVerificationResult(
            status=PinStatus.INCORRECT,
            is_success=False,
            is_locked=False,
            remaining_attempts=remaining,
            explanation=f"Incorrect PIN. {remaining} attempt(s) remaining.",
            audit_data={
                "account_id": account.id,
                "session_id": session.id,
                "attempts_failed": session.failed_pin_attempts,
            },
        )
