"""Pydantic v2 schemas for Human Handoff escalation queue."""

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
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REPEAT_REQUESTED = "REPEAT_REQUESTED"


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
    agent_id: Optional[str] = None
    agent_notes: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None


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
