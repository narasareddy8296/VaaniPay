"""Human Handoff queue, two-way messaging, and resolution endpoints for VaaniPay."""

from datetime import datetime
from typing import List, Optional
import json
import re
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.account import Account
from app.models.session import PaymentSession
from app.models.handoff import HandoffCase, HandoffMessage
from app.models.audit import AuditEvent
from app.schemas.turn import DialogueState
from app.core.session import SessionContext, get_current_session, get_current_agent
from app.schemas.handoff import (
    HandoffAction,
    HandoffCaseStatus,
    HandoffCaseRead,
    HandoffMessageCreate,
    HandoffMessageRead,
    HandoffResolveRequest,
    HandoffResolveResponse,
)

router = APIRouter(prefix="/handoff", tags=["Human Handoff"])


def _status_display_name(raw_status: str) -> str:
    """Formats internal status code into human-friendly customer display string."""
    s = (raw_status or "").upper()
    if s in ("PENDING", "WAITING"):
        return "Waiting"
    if s == "AGENT_CONNECTED":
        return "Agent Connected"
    if s in ("APPROVED", "RESOLVED"):
        return "Resolved"
    if s == "REJECTED":
        return "Rejected"
    if s == "REPEAT_REQUESTED":
        return "Repeat Requested"
    if s == "CANCELLED":
        return "Cancelled"
    return raw_status.title()


def _format_case_read(db: Session, case: HandoffCase, include_messages: bool = False) -> HandoffCaseRead:
    customer = db.query(Account).filter(Account.id == case.account_id).first()
    parsed = None
    if case.context_data:
        try:
            parsed = json.loads(case.context_data)
        except Exception:
            parsed = None

    messages_read = None
    msg_count = len(case.messages) if case.messages is not None else 0
    if include_messages and case.messages:
        messages_read = [
            HandoffMessageRead(
                id=m.id,
                case_id=m.case_id,
                sender_id=m.sender_id,
                sender_role=m.sender_role,
                sender_name=m.sender_name,
                message_text=m.message_text,
                created_at=m.created_at,
            )
            for m in case.messages
        ]

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
        status_display=_status_display_name(case.status),
        agent_id=case.agent_id,
        agent_notes=case.agent_notes,
        created_at=case.created_at,
        resolved_at=case.resolved_at,
        messages_count=msg_count,
        messages=messages_read,
    )


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
    if case_status and case_status.upper() != "ALL":
        target = case_status.upper()
        if target == "WAITING":
            query = query.filter(HandoffCase.status.in_(["PENDING", "WAITING"]))
        else:
            query = query.filter(HandoffCase.status == target)
    cases = query.order_by(HandoffCase.created_at.desc()).all()

    return [_format_case_read(db, c, include_messages=False) for c in cases]


@router.get("/cases/active", response_model=HandoffCaseRead)
def get_active_handoff_case(
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> HandoffCaseRead:
    """
    Fetches the currently active handoff case for the authenticated customer.
    Allows customer session recovery and conversation persistence across page refresh.
    """
    active_case = (
        db.query(HandoffCase)
        .filter(
            HandoffCase.account_id == session.account_id,
            HandoffCase.status.in_(["PENDING", "WAITING", "AGENT_CONNECTED"]),
        )
        .order_by(HandoffCase.created_at.desc())
        .first()
    )

    if not active_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active handoff case found for this customer.",
        )

    return _format_case_read(db, active_case, include_messages=True)


@router.get("/cases/{case_id}", response_model=HandoffCaseRead)
def get_handoff_case(
    case_id: str,
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> HandoffCaseRead:
    """
    Fetches details for a single escalation case.
    SECURITY ENFORCEMENT:
    - If customer: verifies case ownership (case.account_id == session.account_id).
    - If agent: verifies valid customer association.
    - Unauthorized access is strictly rejected with 403 Forbidden.
    """
    case = db.query(HandoffCase).filter(HandoffCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

    # Customer isolation check
    if session.role != "agent" and session.account_id != case.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Access denied to another customer's handoff case.",
        )

    # Agent customer authorization check
    if session.role == "agent":
        customer = db.query(Account).filter(Account.id == case.account_id).first()
        if not customer or customer.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Unauthorized customer account.",
            )

    return _format_case_read(db, case, include_messages=True)


@router.get("/cases/{case_id}/messages", response_model=List[HandoffMessageRead])
def list_case_messages(
    case_id: str,
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> List[HandoffMessageRead]:
    """
    Returns full chronological message history for a handoff case.
    Enforces customer isolation and agent role validation.
    """
    case = db.query(HandoffCase).filter(HandoffCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

    if session.role != "agent" and session.account_id != case.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Access denied to messages for this case.",
        )

    messages = (
        db.query(HandoffMessage)
        .filter(HandoffMessage.case_id == case_id)
        .order_by(HandoffMessage.created_at.asc())
        .all()
    )

    return [
        HandoffMessageRead(
            id=m.id,
            case_id=m.case_id,
            sender_id=m.sender_id,
            sender_role=m.sender_role,
            sender_name=m.sender_name,
            message_text=m.message_text,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/cases/{case_id}/messages", response_model=HandoffMessageRead)
def send_case_message(
    case_id: str,
    request: HandoffMessageCreate,
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> HandoffMessageRead:
    """
    Appends a new message to the two-way handoff conversation.
    SAFETY INVARIANTS:
    - Rejects empty or whitespace-only messages.
    - Closed cases (APPROVED, REJECTED, RESOLVED, CANCELLED) cannot accept new messages.
    - Never stores PINs, secrets, or raw audio in message text.
    - Server-generated timestamps and backend message ownership.
    """
    case = db.query(HandoffCase).filter(HandoffCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

    # Authorization
    if session.role != "agent" and session.account_id != case.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Cannot send messages to another customer's case.",
        )

    # Closed Case Invariant
    if case.status.upper() in ("APPROVED", "REJECTED", "RESOLVED", "CANCELLED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot send messages to a closed handoff case (Status: {case.status}).",
        )

    clean_text = request.message_text.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message content cannot be blank or whitespace-only.",
        )

    # PIN & Secret Security Invariant: Strictly forbid PIN / credential transmission
    lower_text = clean_text.lower()
    has_secret_kw = bool(re.search(r'\b(?:pin|otp|mpin|passcode|password|secret)\b', lower_text))
    has_standalone_digits = bool(re.search(r'^\s*\d{4,6}\s*$', lower_text))
    has_kw_with_digits = has_secret_kw and bool(re.search(r'\b\d{4,6}\b', lower_text))

    if has_standalone_digits or has_kw_with_digits:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Security policy violation: PINs and secrets must never be transmitted in chat messages.",
        )

    # Create message
    msg = HandoffMessage(
        id=f"msg_{uuid.uuid4().hex[:12]}",
        case_id=case.id,
        sender_id=session.account.id,
        sender_role=session.role,
        sender_name=session.account.holder_name,
        message_text=clean_text,
        created_at=datetime.utcnow(),
    )
    db.add(msg)

    # If an agent sends a message to a waiting case, mark as Agent Connected
    if session.role == "agent":
        if case.status in ("PENDING", "WAITING"):
            case.status = "AGENT_CONNECTED"
        case.agent_id = session.account.id

    db.commit()
    db.refresh(msg)

    # Audit event (zero secrets, zero audio)
    audit = AuditEvent(
        id=f"aud_{uuid.uuid4().hex[:12]}",
        session_id=case.session_id,
        account_id=session.account.id,
        event_type="HANDOFF_MESSAGE_SENT",
        details=json.dumps({
            "case_id": case.id,
            "message_id": msg.id,
            "sender_role": session.role,
            "text_length": len(clean_text),
        }),
    )
    db.add(audit)
    db.commit()

    return HandoffMessageRead(
        id=msg.id,
        case_id=msg.case_id,
        sender_id=msg.sender_id,
        sender_role=msg.sender_role,
        sender_name=msg.sender_name,
        message_text=msg.message_text,
        created_at=msg.created_at,
    )


@router.post("/cases/{case_id}/cancel", response_model=HandoffCaseRead)
def cancel_handoff_case(
    case_id: str,
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> HandoffCaseRead:
    """
    Cancels an active handoff case and the associated pending payment session.
    Safe termination of escalation request.
    """
    case = db.query(HandoffCase).filter(HandoffCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

    if session.role != "agent" and session.account_id != case.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Cannot cancel another customer's case.",
        )

    case.status = "CANCELLED"
    case.resolved_at = datetime.utcnow()

    # Also cancel payment session
    payment_session = db.query(PaymentSession).filter(PaymentSession.id == case.session_id).first()
    if payment_session:
        payment_session.current_state = DialogueState.CANCELLED.value

    db.commit()
    return _format_case_read(db, case, include_messages=True)


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
