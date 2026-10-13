"""Pydantic v2 schemas for Dialogue Turn endpoint."""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class DialogueState(str, Enum):
    CAPTURE = "CAPTURE"
    CLARIFY_AMOUNT = "CLARIFY_AMOUNT"
    CLARIFY_PAYEE = "CLARIFY_PAYEE"
    READBACK = "READBACK"
    CONFIRM = "CONFIRM"
    LIVENESS = "LIVENESS"
    STEP_UP_PIN = "STEP_UP_PIN"
    EXECUTE = "EXECUTE"
    RECEIPT = "RECEIPT"
    HANDOFF = "HANDOFF"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class DialogueAction(str, Enum):
    START = "START"
    SUBMIT_TRANSCRIPT = "SUBMIT_TRANSCRIPT"
    CLARIFY = "CLARIFY"
    CONFIRM_READBACK = "CONFIRM_READBACK"
    CANCEL = "CANCEL"
    SUBMIT_LIVENESS = "SUBMIT_LIVENESS"
    SUBMIT_PIN = "SUBMIT_PIN"
    REQUEST_HUMAN = "REQUEST_HUMAN"


class ReadbackCardData(BaseModel):
    """Multi-modal visual and auditory read-back presentation."""
    model_config = ConfigDict(from_attributes=True)

    amount_digits: int
    amount_words: str
    payee_name: str
    payee_id: Optional[str] = None
    currency: str = "INR"


class ReceiptData(BaseModel):
    """Receipt presented upon successful ledger execution."""
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    amount: float
    payee_name: str
    sender_balance_after: float
    timestamp: str


class TurnRequest(BaseModel):
    """Payload submitted to POST /api/v1/turn."""
    model_config = ConfigDict(from_attributes=True)

    session_id: Optional[str] = None
    account_id: str = Field(..., description="Authenticated customer ID, e.g., 'acc_priya'")
    action: DialogueAction = DialogueAction.SUBMIT_TRANSCRIPT
    transcript: Optional[str] = None
    channel: str = Field(default="VOICE", description="'VOICE' or 'TYPED'")
    liveness_response: Optional[str] = None
    pin: Optional[str] = None
    audio_metadata: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None


class TurnResponse(BaseModel):
    """Output returned by POST /api/v1/turn."""
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    state: DialogueState
    prompt_text: str
    readback_card: Optional[ReadbackCardData] = None
    liveness_challenge: Optional[str] = None
    requires_pin: bool = False
    receipt: Optional[ReceiptData] = None
    handoff_case_id: Optional[str] = None
    error: Optional[str] = None
    context: Dict[str, Any] = {}
