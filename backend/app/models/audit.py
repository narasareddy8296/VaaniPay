"""Immutable audit event logging model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class AuditEvent(Base):
    """
    Immutable audit trail recording every state change, score calculation,
    and security event.
    SAFETY INVARIANT: Raw audio binary data and plaintext PINs are strictly prohibited.
    """
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="'SESSION_INIT', 'TRANSCRIPT_RECEIVED', 'PARSE_COMPLETED', 'CROSS_CHECK_EVALUATED', 'LIVENESS_CHALLENGE', 'PIN_ATTEMPT', 'TRANSFER_EXECUTED', 'HANDOFF_CREATED', 'HANDOFF_RESOLVED', 'THRESHOLD_CHANGED'",
    )
    details: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Sanitized JSON metadata. Never contains raw audio or unhashed PINs.",
    )
    client_ip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
