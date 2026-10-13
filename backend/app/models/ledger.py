"""Double-entry mock ledger transaction models."""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class LedgerEntry(Base):
    """
    Immutable double-entry ledger record.
    Every financial movement creates matching balanced DEBIT and CREDIT entries.
    """
    __tablename__ = "ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        doc="Shared correlation ID linking matching debit and credit movements.",
    )
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        doc="'DEBIT' or 'CREDIT'",
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    balance_after: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="POSTED",
        nullable=False,
        doc="'POSTED', 'REJECTED', 'PENDING'",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    account: Mapped["Account"] = relationship(
        "Account",
        back_populates="ledger_entries",
    )
