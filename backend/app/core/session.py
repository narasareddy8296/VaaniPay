"""
Server-validated session credential manager for VaaniPay.
Issues and validates cryptographically signed demo sessions using HMAC-SHA256.
Enforces session expiry, role binding, caller isolation, and prevents forged identity headers.
"""

import base64
import hmac
import hashlib
import json
import secrets
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db
from app.models.account import Account


@dataclass
class SessionContext:
    account_id: str
    role: str
    account: Account


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64decode(data_str: str) -> bytes:
    padding = "=" * (4 - (len(data_str) % 4)) if len(data_str) % 4 != 0 else ""
    return base64.urlsafe_b64decode(data_str + padding)


def create_session_token(account_id: str, role: str, expires_in_seconds: Optional[int] = None) -> str:
    """
    Creates an HMAC-SHA256 signed session credential token.
    Token contains: sub (account_id), role, iat, exp, and jti.
    """
    settings = get_settings()
    ttl = expires_in_seconds if expires_in_seconds is not None else (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    now = int(time.time())
    payload = {
        "sub": account_id,
        "role": role,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(8),
    }

    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode(payload_json)

    signature = hmac.new(
        key=settings.SECRET_KEY.encode("utf-8"),
        msg=payload_b64.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sig_b64 = _b64encode(signature)

    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: str) -> Dict[str, Any]:
    """
    Cryptographically verifies an HMAC-SHA256 session token.
    Returns decoded payload if valid; raises HTTPException 401 otherwise.
    """
    settings = get_settings()
    parts = token.strip().split(".")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token format.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload_b64, sig_b64 = parts[0], parts[1]

    # Verify signature in constant time
    expected_sig = hmac.new(
        key=settings.SECRET_KEY.encode("utf-8"),
        msg=payload_b64.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    expected_sig_b64 = _b64encode(expected_sig)

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session credential: signature verification failed.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode and check payload
    try:
        payload_bytes = _b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session credential payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Expiry verification
    now = int(time.time())
    if "exp" in payload and payload["exp"] < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session credential has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if "sub" not in payload or "role" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session credential missing required claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def get_current_session(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    db: Session = Depends(get_db),
) -> SessionContext:
    """
    FastAPI dependency that extracts and validates the caller's server-issued session.
    Extracts from 'Authorization: Bearer <token>' or 'X-Session-Token: <token>'.
    Derives identity strictly from the verified token payload — NEVER from caller identity headers.
    """
    token = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]
    elif x_session_token:
        token = x_session_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session credential. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_session_token(token)
    account_id = payload["sub"]

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session account no longer exists in database.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if account.is_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is currently locked due to security limits. Please contact support.",
        )

    return SessionContext(account_id=account.id, role=account.role, account=account)


def get_current_agent(
    session: SessionContext = Depends(get_current_session),
) -> SessionContext:
    """
    FastAPI dependency enforcing that the authenticated session possesses 'agent' role.
    Rejects customer sessions with 403 Forbidden.
    """
    if session.role != "agent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Human banking agent credentials required for this endpoint.",
        )
    return session
