"""Human handoff, escalation queue, and two-way messaging models."""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class HandoffCase(Base):
    """
    Escalated case for review by human banking operators.
    Holds conversational context, uncertain fields, and resolution actions.
    """
    __tablename__ = "handoff_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("payment_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    escalation_reason: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="'DISAGREEMENT_AMOUNT', 'SPOOF_RISK_HIGH', 'USER_REQUESTED', 'LOCKOUT', 'PAYEE_AMBIGUOUS'",
    )
    uncertain_field: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    context_data: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="JSON serialization of full conversation turns, candidate amounts, and acoustic scores.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        nullable=False,
        doc="'PENDING', 'WAITING', 'AGENT_CONNECTED', 'APPROVED', 'REJECTED', 'REPEAT_REQUESTED', 'CANCELLED'",
    )
    agent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Mandatory operator explanation note required when resolving a case.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    session: Mapped["PaymentSession"] = relationship(
        "PaymentSession",
        back_populates="handoff_cases",
    )
    account: Mapped["Account"] = relationship(
        "Account",
        foreign_keys=[account_id],
        back_populates="handoff_cases",
    )
    agent: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[agent_id],
    )
    messages: Mapped[List["HandoffMessage"]] = relationship(
        "HandoffMessage",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="HandoffMessage.created_at",
    )


class HandoffMessage(Base):
    """
    Two-way chat message between customer and human banking agent.
    Strictly forbids storing PINs, secrets, or raw audio.
    """
    __tablename__ = "handoff_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("handoff_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)  # "customer", "agent"
    sender_name: Mapped[str] = mapped_column(String(100), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    case: Mapped["HandoffCase"] = relationship(
        "HandoffCase",
        back_populates="messages",
    )
    sender: Mapped["Account"] = relationship(
        "Account",
        foreign_keys=[sender_id],
    )
