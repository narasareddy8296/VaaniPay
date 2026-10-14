"""Pydantic v2 schemas for Human Handoff escalation queue and two-way messaging."""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class HandoffAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REPEAT_REQUESTED = "REPEAT_REQUESTED"


class HandoffCaseStatus(str, Enum):
    PENDING = "PENDING"
    WAITING = "WAITING"
    AGENT_CONNECTED = "AGENT_CONNECTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REPEAT_REQUESTED = "REPEAT_REQUESTED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class HandoffMessageCreate(BaseModel):
    """Payload to send a message within a handoff case."""
    message_text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Text content of the message. Strictly no PINs or sensitive credentials.",
    )


class HandoffMessageRead(BaseModel):
    """Schema for a persisted message in the two-way handoff conversation."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    sender_id: str
    sender_role: str
    sender_name: str
    message_text: str
    created_at: datetime


class HandoffCaseRead(BaseModel):
    """Schema representing an escalation case for review by human agents."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    account_id: str
    customer_name: Optional[str] = None
    escalation_reason: str
    uncertain_field: Optional[str] = None
    context_data: Optional[str] = None
    parsed_context: Optional[Dict[str, Any]] = None
    status: str
    status_display: Optional[str] = None
    agent_id: Optional[str] = None
    agent_notes: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    messages_count: Optional[int] = 0
    messages: Optional[List[HandoffMessageRead]] = None


class HandoffResolveRequest(BaseModel):
    """Payload submitted by agent to resolve an escalation case."""
    model_config = ConfigDict(from_attributes=True)

    action: HandoffAction
    agent_id: str = Field(..., description="ID of authenticated human agent, e.g., 'acc_agent'")
    notes: str = Field(
        ...,
        min_length=3,
        description="Mandatory operator explanation note required for audit compliance.",
    )


class HandoffResolveResponse(BaseModel):
    """Output returned upon resolving a handoff case."""
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    status: str
    action_taken: str
    agent_id: str
    notes: str
    explanation: str
    resolved_at: datetime
