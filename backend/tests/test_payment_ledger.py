"""
Unit tests for double-entry mock ledger execution and limit enforcement.
Verifies balance conservation, single transaction limit, 24-hr daily limit,
overdraft protection, and idempotency guarantees.
"""

from sqlalchemy.orm import Session
from app.db.seed import seed_database
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.services.payment_service import PaymentLedgerService


def test_double_entry_balance_conservation(db_session: Session):
    """
    SAFETY INVARIANT: Double-entry bookkeeping must strictly balance (Debits == Credits).
    Priya transfers ₹1,500 to Ramesh.
    """
    seed_database(db_session)
    priya_initial = db_session.query(Account).filter(Account.id == "acc_priya").first().balance
    ramesh_initial = db_session.query(Account).filter(Account.id == "acc_ramesh").first().balance

    assert priya_initial == 50000.00
    assert ramesh_initial == 25000.00

    result = PaymentLedgerService.execute_payment(
        db=db_session,
        sender_id="acc_priya",
        receiver_id="acc_ramesh",
        amount=1500.00,
        description="Test payment",
    )

    assert result.success is True
    assert result.sender_balance_after == 48500.00

    # Verify Database Balances
    priya_after = db_session.query(Account).filter(Account.id == "acc_priya").first().balance
    ramesh_after = db_session.query(Account).filter(Account.id == "acc_ramesh").first().balance

    assert priya_after == 48500.00
    assert ramesh_after == 26500.00

    # Verify Ledger Entries
    debit = (
        db_session.query(LedgerEntry)
        .filter(LedgerEntry.transaction_id == result.transaction_id, LedgerEntry.entry_type == "DEBIT")
        .first()
    )
    credit = (
        db_session.query(LedgerEntry)
        .filter(LedgerEntry.transaction_id == result.transaction_id, LedgerEntry.entry_type == "CREDIT")
        .first()
    )

    assert debit is not None and credit is not None
    assert debit.amount == credit.amount == 1500.00
    assert debit.balance_after == 48500.00
    assert credit.balance_after == 26500.00


def test_single_transaction_limit_rejection(db_session: Session):
    """Voice payments exceeding ₹10,000 ceiling are rejected with balances untouched."""
    seed_database(db_session)
    result = PaymentLedgerService.execute_payment(
        db=db_session,
        sender_id="acc_priya",
        receiver_id="acc_ramesh",
        amount=15000.00,  # Exceeds ₹10,000
    )

    assert result.success is False
    assert "exceeds maximum single voice transaction limit" in result.explanation

    priya = db_session.query(Account).filter(Account.id == "acc_priya").first()
    assert priya.balance == 50000.00  # Untouched


def test_daily_rolling_limit_rejection(db_session: Session):
    """
    Cumulative voice payments exceeding ₹25,000 in a rolling 24-hr window are rejected.
    """
    seed_database(db_session)

    # Tx 1: ₹10,000 (Success, cumulative: ₹10k)
    res1 = PaymentLedgerService.execute_payment(db_session, "acc_priya", "acc_ramesh", 10000.00)
    assert res1.success is True

    # Tx 2: ₹10,000 (Success, cumulative: ₹20k)
    res2 = PaymentLedgerService.execute_payment(db_session, "acc_priya", "acc_ramesh", 10000.00)
    assert res2.success is True

    # Tx 3: ₹10,000 (Attempted cumulative: ₹30k > ₹25k limit -> REJECTED!)
    res3 = PaymentLedgerService.execute_payment(db_session, "acc_priya", "acc_ramesh", 10000.00)
    assert res3.success is False
    assert "exceeds 24-hour cumulative limit" in res3.explanation

    # Balance decreased by exactly ₹20,000 (from 50,000 to 30,000)
    priya = db_session.query(Account).filter(Account.id == "acc_priya").first()
    assert priya.balance == 30000.00


def test_overdraft_insufficient_funds_protection(db_session: Session):
    """Payments exceeding available balance are rejected."""
    seed_database(db_session)
    # Ramesh has ₹25,000. Try to send ₹30,000 (within daily limits if under 10k, but let's test balance)
    # Give Ramesh a balance of ₹500
    ramesh = db_session.query(Account).filter(Account.id == "acc_ramesh").first()
    ramesh.balance = 500.00
    db_session.commit()

    result = PaymentLedgerService.execute_payment(db_session, "acc_ramesh", "acc_priya", 1000.00)
    assert result.success is False
    assert "Insufficient funds" in result.explanation

    assert ramesh.balance == 500.00  # Untouched


def test_idempotency_prevents_duplicate_transfers(db_session: Session):
    """
    SAFETY INVARIANT: Retrying a transaction with an identical idempotency key
    returns the original success receipt WITHOUT generating duplicate debits or credits.
    """
    seed_database(db_session)
    key = "idemp_test_999"

    # First attempt: Executes transfer
    res1 = PaymentLedgerService.execute_payment(
        db_session, "acc_priya", "acc_ramesh", 500.00, idempotency_key=key
    )
    assert res1.success is True
    assert res1.is_idempotent_replay is False

    ledger_count_1 = db_session.query(LedgerEntry).count()
    priya_balance_1 = db_session.query(Account).filter(Account.id == "acc_priya").first().balance

    # Second attempt (Network retry / duplicate submission):
    res2 = PaymentLedgerService.execute_payment(
        db_session, "acc_priya", "acc_ramesh", 500.00, idempotency_key=key
    )
    assert res2.success is True
    assert res2.is_idempotent_replay is True
    assert res2.transaction_id == key

    ledger_count_2 = db_session.query(LedgerEntry).count()
    priya_balance_2 = db_session.query(Account).filter(Account.id == "acc_priya").first().balance

    # Ensure NO duplicate entries created and balance remained identical
    assert ledger_count_2 == ledger_count_1
    assert priya_balance_2 == priya_balance_1
