"""Synthetic customer and agent account models."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Numeric, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Account(Base):
    """
    Synthetic bank account entity.
    Represents mock customers and human agents.
    """
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    holder_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="customer", nullable=False)  # "customer", "agent"
    hashed_pin: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Argon2id hash only, never plaintext
    balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0.00, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    contacts: Mapped[List["Contact"]] = relationship(
        "Contact",
        back_populates="account",
        foreign_keys="Contact.account_id",
        cascade="all, delete-orphan",
    )
    ledger_entries: Mapped[List["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="account",
    )
    sessions: Mapped[List["PaymentSession"]] = relationship(
        "PaymentSession",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    handoff_cases: Mapped[List["HandoffCase"]] = relationship(
        "HandoffCase",
        back_populates="account",
        foreign_keys="HandoffCase.account_id",
    )
