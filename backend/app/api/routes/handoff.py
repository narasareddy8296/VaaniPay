"""Human Handoff queue and resolution endpoints for VaaniPay."""

from datetime import datetime
from typing import List, Optional
import json
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.account import Account
from app.models.handoff import HandoffCase
from app.core.session import SessionContext, get_current_agent
from app.schemas.handoff import (
    HandoffAction,
    HandoffCaseStatus,
    HandoffCaseRead,
    HandoffResolveRequest,
    HandoffResolveResponse,
)

router = APIRouter(prefix="/handoff", tags=["Human Handoff"])


@router.get("/cases", response_model=List[HandoffCaseRead])
def list_handoff_cases(
    case_status: Optional[str] = Query(None, alias="status"),
    session: SessionContext = Depends(get_current_agent),
    db: Session = Depends(get_db),
) -> List[HandoffCaseRead]:
    """
    Lists escalation cases in the queue with optional status filtering.
    SECURITY ENFORCEMENT:
    - Enforces agent session requirement (role == 'agent').
    - Customer sessions are strictly rejected with 403 Forbidden.
    """
    query = db.query(HandoffCase)
    if case_status:
        query = query.filter(HandoffCase.status == case_status.upper())
    cases = query.order_by(HandoffCase.created_at.desc()).all()

    results = []
    for c in cases:
        customer = db.query(Account).filter(Account.id == c.account_id).first()
        parsed = None
        if c.context_data:
            try:
                parsed = json.loads(c.context_data)
            except Exception:
                parsed = None

        results.append(
            HandoffCaseRead(
                id=c.id,
                session_id=c.session_id,
                account_id=c.account_id,
                customer_name=customer.holder_name if customer else "Unknown",
                escalation_reason=c.escalation_reason,
                uncertain_field=c.uncertain_field,
                context_data=c.context_data,
                parsed_context=parsed,
                status=c.status,
                agent_id=c.agent_id,
                agent_notes=c.agent_notes,
                created_at=c.created_at,
                resolved_at=c.resolved_at,
            )
        )
    return results


@router.get("/cases/{case_id}", response_model=HandoffCaseRead)
def get_handoff_case(
    case_id: str,
    session: SessionContext = Depends(get_current_agent),
    db: Session = Depends(get_db),
) -> HandoffCaseRead:
    """
    Fetches details for a single escalation case.
    SECURITY ENFORCEMENT:
    - Enforces agent session requirement (role == 'agent').
    - Customer sessions are strictly rejected with 403 Forbidden.
    """
    case = db.query(HandoffCase).filter(HandoffCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

    parsed = None
    if case.context_data:
        try:
            parsed = json.loads(case.context_data)
        except Exception:
            parsed = None

    customer = db.query(Account).filter(Account.id == case.account_id).first()
    return HandoffCaseRead(
        id=case.id,
        session_id=case.session_id,
        account_id=case.account_id,
        customer_name=customer.holder_name if customer else "Unknown",
        escalation_reason=case.escalation_reason,
        uncertain_field=case.uncertain_field,
        context_data=case.context_data,
        parsed_context=parsed,
        status=case.status,
        agent_id=case.agent_id,
        agent_notes=case.agent_notes,
        created_at=case.created_at,
        resolved_at=case.resolved_at,
    )


@router.post("/cases/{case_id}/resolve", response_model=HandoffResolveResponse)
def resolve_handoff_case(
    case_id: str,
    request: HandoffResolveRequest,
    session: SessionContext = Depends(get_current_agent),
    db: Session = Depends(get_db),
) -> HandoffResolveResponse:
    """
    Submits an agent review decision on an escalation case.
    SAFETY INVARIANTS:
    - Agent authorization required (role == 'agent'), derived from verified session token.
    - Non-empty operator explanation note is mandatory (min 3 chars).
    - Agent approval is a review audit decision, NOT a rogue payment execution command.
      Approval does NOT bypass customer confirmation, PIN requirements, or ledger limits.
    """
    case = db.query(HandoffCase).filter(HandoffCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff case not found.")

    agent = session.account

    # Validate note is non-empty
    clean_notes = request.notes.strip()
    if len(clean_notes) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A mandatory operator explanation note of at least 3 characters is required.",
        )

    status_mapping = {
        HandoffAction.APPROVE: HandoffCaseStatus.APPROVED.value,
        HandoffAction.REJECT: HandoffCaseStatus.REJECTED.value,
        HandoffAction.REPEAT_REQUESTED: HandoffCaseStatus.REPEAT_REQUESTED.value,
    }
    action_status = status_mapping.get(request.action, request.action.value)
    case.status = action_status
    case.agent_id = agent.id
    case.agent_notes = clean_notes
    case.resolved_at = datetime.utcnow()
    db.commit()

    explanation = (
        f"Case {case_id} marked {action_status} by Agent {agent.holder_name}. "
        "Audit note recorded. (Note: Review approval does not bypass payment security guards)."
    )

    return HandoffResolveResponse(
        case_id=case.id,
        status=action_status,
        action_taken=request.action.value,
        agent_id=agent.id,
        notes=clean_notes,
        explanation=explanation,
        resolved_at=case.resolved_at,
    )
