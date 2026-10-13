"""Customer contact and payee models with alias support."""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Contact(Base):
    """
    Beneficiary / contact address book entity associated with an account.
    Supports colloquial aliases used in speech recognition fuzzy matching.
    """
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    beneficiary_account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    aliases: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Comma-separated alternative names or pronunciations, e.g., 'Ramesh,Rameshh'",
    )
    is_frequent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    account: Mapped["Account"] = relationship(
        "Account",
        foreign_keys=[account_id],
        back_populates="contacts",
    )
    beneficiary_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[beneficiary_account_id],
    )
