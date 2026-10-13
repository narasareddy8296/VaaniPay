"""Tests for database initialization, schema integrity, and SQLite foreign key enforcement."""

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.account import Account
from app.models.contact import Contact
from app.models.ledger import LedgerEntry
from app.models.session import PaymentSession
from app.models.handoff import HandoffCase


def test_sqlite_foreign_key_enforcement_on_contact(db_session: Session):
    """
    Verifies that foreign key constraints are strictly enforced in SQLite.
    Inserting a contact with a non-existent account_id must raise an IntegrityError.
    """
    orphaned_contact = Contact(
        id="cnt_orphaned",
        account_id="non_existent_account_12345",
        contact_name="Unknown Payee",
    )
    db_session.add(orphaned_contact)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_sqlite_foreign_key_enforcement_on_ledger(db_session: Session):
    """Verifies that ledger entries cannot reference non-existent accounts."""
    orphaned_entry = LedgerEntry(
        id="led_orphaned",
        transaction_id="tx_fake",
        account_id="non_existent_account_99999",
        entry_type="DEBIT",
        amount=500.0,
        balance_after=4500.0,
    )
    db_session.add(orphaned_entry)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_sqlite_foreign_key_enforcement_on_handoff(db_session: Session):
    """Verifies that handoff cases require a valid session_id and account_id."""
    orphaned_handoff = HandoffCase(
        id="hc_orphaned",
        session_id="non_existent_session",
        account_id="non_existent_account",
        escalation_reason="DISAGREEMENT_AMOUNT",
    )
    db_session.add(orphaned_handoff)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_valid_foreign_key_insertion(db_session: Session):
    """Verifies that valid parent-child relationships succeed without errors."""
    account = Account(
        id="acc_valid_test",
        account_number="ACC_TEST_001",
        holder_name="Test User",
        phone_number="+910000000001",
        role="customer",
        balance=1000.00,
        currency="INR",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()

    contact = Contact(
        id="cnt_valid_test",
        account_id=account.id,
        contact_name="Friend",
    )
    db_session.add(contact)
    db_session.flush()

    assert contact.id == "cnt_valid_test"
    assert contact.account.holder_name == "Test User"
