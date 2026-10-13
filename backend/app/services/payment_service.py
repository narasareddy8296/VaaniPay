"""
Double-entry mock ledger execution and limit enforcement engine for VaaniPay.
Maintains absolute balance conservation (Debits == Credits), enforces per-transaction
and daily voice limits, overdraft protection, and idempotency guarantees.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.config import get_settings
from app.models.account import Account
from app.models.ledger import LedgerEntry


class PaymentExecutionResult(BaseModel):
    """Result of double-entry ledger execution."""
    model_config = ConfigDict(from_attributes=True)

    success: bool
    transaction_id: Optional[str] = None
    sender_id: str
    receiver_id: str
    amount: float
    sender_balance_after: Optional[float] = None
    explanation: str
    is_idempotent_replay: bool = False
    audit_data: Dict[str, Any] = {}


class PaymentLedgerService:
    """Manages double-entry financial movements with strict security guards."""

    @staticmethod
    def get_daily_voice_usage(db: Session, sender_id: str) -> float:
        """Calculates total debit volume for the account in the rolling 24-hour window."""
        window_start = datetime.utcnow() - timedelta(hours=24)
        total_used = (
            db.query(func.coalesce(func.sum(LedgerEntry.amount), 0.0))
            .filter(
                LedgerEntry.account_id == sender_id,
                LedgerEntry.entry_type == "DEBIT",
                LedgerEntry.status == "POSTED",
                LedgerEntry.created_at >= window_start,
            )
            .scalar()
        )
        return float(total_used)

    @staticmethod
    def execute_payment(
        db: Session,
        sender_id: str,
        receiver_id: str,
        amount: float,
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentExecutionResult:
        """
        Executes a double-entry payment transfer within an atomic database transaction.
        SAFETY INVARIANTS:
        - Debits must equal Credits.
        - Balance cannot drop below zero.
        - Maximum single transaction voice limit (₹10,000) enforced.
        - Rolling 24-hour voice payments limit (₹25,000) enforced.
        - Idempotency key prevents duplicate execution on network retry.
        """
        settings = get_settings()
        amount = float(amount)

        if amount <= 0:
            return PaymentExecutionResult(
                success=False,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                explanation="Payment amount must be strictly greater than zero.",
            )

        # 1. Idempotency Check
        if idempotency_key:
            existing_debit = (
                db.query(LedgerEntry)
                .filter(
                    LedgerEntry.account_id == sender_id,
                    LedgerEntry.entry_type == "DEBIT",
                    LedgerEntry.transaction_id == idempotency_key,
                    LedgerEntry.status == "POSTED",
                )
                .first()
            )
            if existing_debit:
                return PaymentExecutionResult(
                    success=True,
                    transaction_id=idempotency_key,
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    amount=float(existing_debit.amount),
                    sender_balance_after=float(existing_debit.balance_after),
                    is_idempotent_replay=True,
                    explanation="Payment already executed. Returning existing idempotent receipt.",
                )

        # 2. Single Transaction Limit Enforcement
        if amount > settings.MAX_VOICE_TX_AMOUNT:
            return PaymentExecutionResult(
                success=False,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                explanation=(
                    f"Amount ₹{amount:,.2f} exceeds maximum single voice transaction limit of "
                    f"₹{settings.MAX_VOICE_TX_AMOUNT:,.2f}."
                ),
            )

        # 3. 24-Hour Rolling Daily Limit Enforcement
        daily_used = PaymentLedgerService.get_daily_voice_usage(db, sender_id)
        if (daily_used + amount) > settings.MAX_DAILY_VOICE_PAYMENTS:
            remaining_limit = max(0.0, settings.MAX_DAILY_VOICE_PAYMENTS - daily_used)
            return PaymentExecutionResult(
                success=False,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                explanation=(
                    f"Payment exceeds 24-hour cumulative limit of ₹{settings.MAX_DAILY_VOICE_PAYMENTS:,.2f}. "
                    f"Used: ₹{daily_used:,.2f}, Remaining: ₹{remaining_limit:,.2f}."
                ),
            )

        # 4. Fetch Accounts
        sender = db.query(Account).filter(Account.id == sender_id).with_for_update().first()
        receiver = db.query(Account).filter(Account.id == receiver_id).with_for_update().first()

        if not sender:
            return PaymentExecutionResult(
                success=False,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                explanation=f"Sender account '{sender_id}' not found.",
            )

        if not receiver:
            return PaymentExecutionResult(
                success=False,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                explanation=f"Beneficiary account '{receiver_id}' not found.",
            )

        if sender.is_locked or not sender.is_active:
            return PaymentExecutionResult(
                success=False,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                explanation="Sender account is locked or inactive.",
            )

        # 5. Overdraft / Available Balance Check
        sender_balance = float(sender.balance)
        if sender_balance < amount:
            return PaymentExecutionResult(
                success=False,
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                explanation=f"Insufficient funds: Available balance ₹{sender_balance:,.2f} < requested ₹{amount:,.2f}.",
            )

        # 6. Execute Double-Entry Atomic Movement
        tx_id = idempotency_key or f"tx_{uuid.uuid4().hex[:12]}"
        new_sender_balance = sender_balance - amount
        new_receiver_balance = float(receiver.balance) + amount

        sender.balance = new_sender_balance
        receiver.balance = new_receiver_balance

        desc = description or f"Voice payment to {receiver.holder_name}"

        debit_entry = LedgerEntry(
            id=f"led_{uuid.uuid4().hex[:12]}",
            transaction_id=tx_id,
            account_id=sender.id,
            entry_type="DEBIT",
            amount=amount,
            balance_after=new_sender_balance,
            description=desc,
            status="POSTED",
            created_at=datetime.utcnow(),
        )

        credit_entry = LedgerEntry(
            id=f"led_{uuid.uuid4().hex[:12]}",
            transaction_id=tx_id,
            account_id=receiver.id,
            entry_type="CREDIT",
            amount=amount,
            balance_after=new_receiver_balance,
            description=f"Voice payment from {sender.holder_name}",
            status="POSTED",
            created_at=datetime.utcnow(),
        )

        db.add(debit_entry)
        db.add(credit_entry)
        db.commit()

        return PaymentExecutionResult(
            success=True,
            transaction_id=tx_id,
            sender_id=sender.id,
            receiver_id=receiver.id,
            amount=amount,
            sender_balance_after=new_sender_balance,
            explanation=f"Successfully transferred ₹{amount:,.2f} to {receiver.holder_name}.",
            audit_data={
                "tx_id": tx_id,
                "amount": amount,
                "sender_id": sender.id,
                "receiver_id": receiver.id,
            },
        )
