"""
Account endpoints for VaaniPay: demo profiles, balance, mock ledger history,
server-validated session creation, and evaluator demo data reset.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.seed import seed_database
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.core.session import (
    SessionContext,
    create_session_token,
    get_current_session,
    get_current_agent,
)
from app.schemas.account import (
    AccountRead,
    TransactionRead,
    DemoLoginRequest,
    DemoLoginResponse,
)

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.get("", response_model=List[AccountRead])
def list_accounts(db: Session = Depends(get_db)) -> List[AccountRead]:
    """
    Lists all synthetic demo accounts (customers and support agents).
    Publicly accessible to populate the demo login profile selector.
    """
    accounts = db.query(Account).all()
    return accounts


@router.get("/{account_id}", response_model=AccountRead)
def get_account(
    account_id: str,
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> AccountRead:
    """
    Fetches details for a specific account including balance and address book contacts.
    SECURITY ENFORCEMENT:
    - Identity is derived from the server-validated session, NOT caller headers.
    - Customers cannot access other customers' private balances or contacts (403 Forbidden).
    - Agents possess authorized access across customer dossiers for review.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    # Server-enforced caller isolation: ignore any forged caller headers
    if session.role != "agent" and session.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Customers cannot access private account data of another customer.",
        )

    return account


@router.get("/{account_id}/transactions", response_model=List[TransactionRead])
def get_account_transactions(
    account_id: str,
    session: SessionContext = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> List[TransactionRead]:
    """
    Fetches mock ledger transaction history for an account.
    SECURITY ENFORCEMENT:
    - Requires valid server-issued session token.
    - Cross-customer private transaction inspection is rejected with 403 Forbidden.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found.",
        )

    if session.role != "agent" and session.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Customers cannot access private transaction records of another customer.",
        )

    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(50)
        .all()
    )
    return entries


@router.post("/demo-login", response_model=DemoLoginResponse)
def demo_login(
    payload: DemoLoginRequest,
    db: Session = Depends(get_db),
) -> DemoLoginResponse:
    """
    Issues a server-validated demo session credential for the selected seeded profile.
    SECURITY INVARIANTS:
    - Returns a signed HMAC-SHA256 session token with expiration and bound role.
    - Locked accounts cannot log in.
    - Clearly disclaims that this is a simulated demo login, not production banking authentication.
    """
    account = db.query(Account).filter(Account.id == payload.account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Demo account '{payload.account_id}' not found. Please select a valid seeded account.",
        )

    if account.is_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is currently locked out due to security limits. Please contact support.",
        )

    # Issue cryptographic session credential token
    token = create_session_token(account_id=account.id, role=account.role)

    return DemoLoginResponse(
        account=account,
        role=account.role,
        session_token=token,
        token_type="Bearer",
        expires_in_seconds=86400,
        is_demo=True,
        auth_notice="DEMO EVALUATION MODE: Connected to mock banking ledger. Session is server-validated for demo evaluation.",
    )


@router.post("/demo-reset")
def reset_demo_data(
    db: Session = Depends(get_db),
):
    """
    Evaluator convenience endpoint: Resets synthetic demo accounts, unlocks accounts,
    and restores baseline balances (Priya ₹50k, Ramesh ₹25k).
    Does not drop database tables.
    """
    result = seed_database(db)
    return {
        "status": "success",
        "message": "Demo data successfully reset to baseline seeded state.",
        "details": result,
    }
