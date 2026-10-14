"""Pydantic schemas for synthetic accounts and contacts."""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ContactBase(BaseModel):
    contact_name: str
    phone_number: Optional[str] = None
    beneficiary_account_id: Optional[str] = None
    aliases: Optional[str] = None
    is_frequent: bool = True


class ContactCreate(BaseModel):
    contact_name: str
    beneficiary_account_id: Optional[str] = None
    phone_number: Optional[str] = None
    aliases: Optional[str] = None
    is_frequent: bool = False  # New payees default to non-frequent to enforce step-up PIN


class ContactRead(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    created_at: datetime


class AccountBase(BaseModel):
    account_number: str
    holder_name: str
    phone_number: str
    role: str
    balance: float
    currency: str
    is_active: bool
    is_locked: bool


class AccountRead(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    contacts: List[ContactRead] = []


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    transaction_id: str
    account_id: str
    entry_type: str
    amount: float
    balance_after: float
    description: Optional[str] = None
    status: str
    created_at: datetime


class DemoLoginRequest(BaseModel):
    account_id: str


class DemoLoginResponse(BaseModel):
    account: AccountRead
    role: str
    session_token: str
    token_type: str = "Bearer"
    expires_in_seconds: int = 86400
    is_demo: bool = True
    auth_notice: str

