"""Turn endpoint for VaaniPay dialogue state machine."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.account import Account
from app.schemas.turn import TurnRequest, TurnResponse
from app.core.state_machine import DialogueStateMachine
from app.core.session import SessionContext, get_current_session

router = APIRouter(tags=["Dialogue Turn"])
state_machine = DialogueStateMachine()


@router.post("/turn", response_model=TurnResponse)
def execute_turn(
    request: TurnRequest,
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> TurnResponse:
    """
    Processes a conversational or transactional dialogue turn.
    Enforces backend-controlled state transitions, explicit read-back confirmation,
    liveness verification, PIN step-up, and mock double-entry ledger execution.

    SECURITY INVARIANTS:
    - Caller must present a valid server-issued session token.
    - Identity is validated against the authenticated session; customers cannot execute turns for another account.
    """
    if session.role != "agent" and session.account_id != request.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Cannot execute dialogue turns for another customer account.",
        )

    account = db.query(Account).filter(Account.id == request.account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer account '{request.account_id}' not found.",
        )

    return state_machine.process_turn(db=db, account=account, request=request)
