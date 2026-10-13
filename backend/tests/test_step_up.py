"""
Unit tests for risk-based PIN step-up verification and 3-attempt brute-force lockout.
"""

from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.account import Account
from app.models.contact import Contact
from app.models.session import PaymentSession
from app.services.antispoof_service import AntiSpoofOutcome
from app.core.auth_step_up import PinSecurityManager, PinStatus


def test_pin_hashing_and_verification():
    """PINs are hashed using Argon2id and verified in constant time."""
    pin_hash = PinSecurityManager.hash_pin("1234")
    assert pin_hash.startswith("$argon2id$")
    assert pin_hash != "1234"

    assert PinSecurityManager.verify_pin_hash("1234", pin_hash) is True
    assert PinSecurityManager.verify_pin_hash("9999", pin_hash) is False
    assert PinSecurityManager.verify_pin_hash("", pin_hash) is False


def test_pin_step_up_triggers():
    """
    Verifies that step-up PIN is required under all documented risk conditions:
    1. Amount > ₹2,000 threshold
    2. New / unverified payee
    3. Grey-zone or unavailable spoof status
    4. Typed fallback channel
    """
    # 1. Low amount, frequent contact, clean acoustic check -> No PIN required
    frequent_contact = Contact(id="c1", account_id="acc_priya", contact_name="Ramesh", is_frequent=True, beneficiary_account_id="acc_ramesh")
    eval1 = PinSecurityManager.evaluate_step_up_needed(
        amount=500.0,
        payee_contact=frequent_contact,
        antispoof_outcome=AntiSpoofOutcome.LOW_RISK,
        channel="VOICE",
    )
    assert eval1.requires_pin is False

    # 2. Amount > ₹2,000 threshold forces PIN
    eval2 = PinSecurityManager.evaluate_step_up_needed(
        amount=2500.0,
        payee_contact=frequent_contact,
        antispoof_outcome=AntiSpoofOutcome.LOW_RISK,
        channel="VOICE",
    )
    assert eval2.requires_pin is True
    assert any("exceeds PIN threshold" in r for r in eval2.reasons)

    # 3. New payee forces PIN even for small amount (₹100)
    new_contact = Contact(id="c2", account_id="acc_priya", contact_name="New Person", is_frequent=False, beneficiary_account_id=None)
    eval3 = PinSecurityManager.evaluate_step_up_needed(
        amount=100.0,
        payee_contact=new_contact,
        antispoof_outcome=AntiSpoofOutcome.LOW_RISK,
        channel="VOICE",
    )
    assert eval3.requires_pin is True
    assert any("New Payee" in r for r in eval3.reasons)

    # 4. Grey-zone audio forces PIN
    eval4 = PinSecurityManager.evaluate_step_up_needed(
        amount=500.0,
        payee_contact=frequent_contact,
        antispoof_outcome=AntiSpoofOutcome.GREY_ZONE,
        channel="VOICE",
    )
    assert eval4.requires_pin is True
    assert any("GREY_ZONE" in r for r in eval4.reasons)

    # 5. Typed fallback forces PIN
    eval5 = PinSecurityManager.evaluate_step_up_needed(
        amount=500.0,
        payee_contact=frequent_contact,
        antispoof_outcome=AntiSpoofOutcome.LOW_RISK,
        channel="TYPED",
    )
    assert eval5.requires_pin is True
    assert any("Typed input fallback" in r for r in eval5.reasons)


def test_correct_pin_verification(db_session: Session):
    """Submitting valid PIN succeeds and resets failed attempts counter."""
    seed_database(db_session)
    account = db_session.query(Account).filter(Account.id == "acc_priya").first()
    session = PaymentSession(id="sess_pin_1", account_id=account.id, current_state="STEP_UP_PIN", failed_pin_attempts=1)
    db_session.add(session)
    db_session.commit()

    # Priya's seeded demo PIN is "1234"
    result = PinSecurityManager.verify_pin(session, account, "1234", db_session)
    assert result.status == PinStatus.VERIFIED
    assert result.is_success is True
    assert session.failed_pin_attempts == 0


def test_three_failed_attempts_triggers_account_lockout(db_session: Session):
    """
    SAFETY INVARIANT: Submitting 3 consecutive invalid PINs locks the customer account.
    All subsequent step-up attempts are permanently blocked.
    """
    seed_database(db_session)
    account = db_session.query(Account).filter(Account.id == "acc_priya").first()
    session = PaymentSession(id="sess_pin_2", account_id=account.id, current_state="STEP_UP_PIN")
    db_session.add(session)
    db_session.commit()

    assert account.is_locked is False

    # Attempt 1: Failed
    r1 = PinSecurityManager.verify_pin(session, account, "0000", db_session)
    assert r1.status == PinStatus.INCORRECT
    assert r1.remaining_attempts == 2
    assert account.is_locked is False

    # Attempt 2: Failed
    r2 = PinSecurityManager.verify_pin(session, account, "1111", db_session)
    assert r2.status == PinStatus.INCORRECT
    assert r2.remaining_attempts == 1
    assert account.is_locked is False

    # Attempt 3: Failed -> LOCKOUT!
    r3 = PinSecurityManager.verify_pin(session, account, "2222", db_session)
    assert r3.status == PinStatus.LOCKED_OUT
    assert r3.is_locked is True
    assert account.is_locked is True  # Account persisted as locked

    # Attempt 4: Even with correct PIN "1234", account is locked out!
    r4 = PinSecurityManager.verify_pin(session, account, "1234", db_session)
    assert r4.status == PinStatus.LOCKED_OUT
    assert r4.is_success is False
