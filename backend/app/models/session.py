"""Payment and dialogue conversation session models."""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Numeric, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class PaymentSession(Base):
    """
    Dialogue state tracking and transactional session.
    Preserves dialogue history, parsed fields, challenges, and attempt counters.
    """
    __tablename__ = "payment_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    current_state: Mapped[str] = mapped_column(
        String(30),
        default="CAPTURE",
        nullable=False,
        doc="'CAPTURE', 'CLARIFY', 'READ_BACK', 'CONFIRM', 'LIVENESS', 'STEP_UP', 'EXECUTE', 'RECEIPT', 'HANDOFF', 'CANCELLED'",
    )
    channel: Mapped[str] = mapped_column(String(20), default="VOICE", nullable=False)  # "VOICE" or "TYPED"
    raw_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pending_amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    pending_payee_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    pending_payee_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    liveness_challenge: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # SHA-256 hash of challenge
    challenge_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failed_pin_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    account: Mapped["Account"] = relationship(
        "Account",
        back_populates="sessions",
    )
    handoff_cases: Mapped[List["HandoffCase"]] = relationship(
        "HandoffCase",
        back_populates="session",
        cascade="all, delete-orphan",
    )
