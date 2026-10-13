"""
Backend-Controlled Dialogue State Machine for VaaniPay.
Enforces explicit state transitions, multi-modal read-back, liveness verification,
anti-spoof integration, PIN step-up, human handoff, and double-entry execution boundaries.
"""

import uuid
import json
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.account import Account
from app.models.contact import Contact
from app.models.session import PaymentSession
from app.models.handoff import HandoffCase
from app.models.audit import AuditEvent
from app.parsers.number_parser import parse_amount, amount_to_words, ParseStatus
from app.parsers.payee_resolver import PayeeResolver, PayeeResolutionStatus
from app.core.cross_check import CrossCheckEngine, CrossCheckStatus
from app.core.liveness import (
    generate_liveness_challenge,
    verify_liveness_challenge,
    LivenessStatus,
)
from app.core.auth_step_up import PinSecurityManager, PinStatus
from app.services.antispoof_service import (
    antispoof_service,
    BaseAntiSpoofService,
    AntiSpoofOutcome,
)
from app.services.payment_service import PaymentLedgerService
from app.schemas.turn import (
    DialogueState,
    DialogueAction,
    TurnRequest,
    TurnResponse,
    ReadbackCardData,
    ReceiptData,
)


class DialogueStateMachine:
    """
    Central dialogue controller governing payment state transitions.
    SAFETY INVARIANTS:
    - Never execute directly from transcript or parser result.
    - Validate every transition server-side.
    - Explicit confirmation required.
    - Cancellations and lockouts permanently halt payment.
    - Double-entry ledger execution occurs ONLY at the EXECUTE boundary.
    """

    def __init__(
        self,
        cross_check_engine: Optional[CrossCheckEngine] = None,
        anti_spoof_adapter: Optional[BaseAntiSpoofService] = None,
    ):
        self.settings = get_settings()
        self.cross_check_engine = cross_check_engine or CrossCheckEngine()
        self.antispoof_service = anti_spoof_adapter or antispoof_service

    def process_turn(
        self,
        db: Session,
        account: Account,
        request: TurnRequest,
    ) -> TurnResponse:
        """Processes a single conversational or transactional turn."""
        # 1. Fetch or initialize PaymentSession
        session = self._get_or_create_session(db, account, request)
        if session is None:
            existing = (
                db.query(PaymentSession).filter(PaymentSession.id == request.session_id).first()
                if request.session_id
                else None
            )
            error_code = "SESSION_MISMATCH" if existing else "SESSION_NOT_FOUND"
            return TurnResponse(
                session_id=request.session_id or "unknown",
                state=DialogueState.FAILED,
                prompt_text="Session invalid, expired, or unauthorized.",
                error=error_code,
            )

        # 2. Check for Account Lockout
        if account.is_locked:
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.FAILED,
                prompt_text="Your account is locked due to security limits. Please contact a banking representative.",
                error="ACCOUNT_LOCKED",
            )

        # 3. Handle Explicit Cancellation Action or Spoken Cancel
        transcript_clean = (request.transcript or "").strip().lower()
        if (
            request.action == DialogueAction.CANCEL
            or any(w in transcript_clean for w in ["cancel", "cancel payment", "ruk jao", "mat bhejo"])
        ):
            return self._handle_cancellation(db, session, account)

        # 4. Handle Explicit Human Agent Request
        if (
            request.action == DialogueAction.REQUEST_HUMAN
            or any(w in transcript_clean for w in ["human agent", "talk to human", "representative", "specialist"])
        ):
            return self._escalate_to_handoff(
                db=db,
                session=session,
                account=account,
                reason="USER_REQUESTED",
                uncertain_field=None,
                user_note="Customer requested human assistance.",
            )

        # 5. Route by Current State
        current_state = DialogueState(session.current_state)

        if current_state in (DialogueState.RECEIPT, DialogueState.CANCELLED, DialogueState.FAILED, DialogueState.HANDOFF):
            return TurnResponse(
                session_id=session.id,
                state=current_state,
                prompt_text="This payment session is closed. Please start a new session.",
                error="SESSION_TERMINATED",
            )

        if current_state == DialogueState.CAPTURE:
            return self._handle_capture_state(db, session, account, request)

        if current_state in (DialogueState.CLARIFY_AMOUNT, DialogueState.CLARIFY_PAYEE):
            return self._handle_clarification_state(db, session, account, request, current_state)

        if current_state == DialogueState.READBACK:
            return self._handle_readback_state(db, session, account, request)

        if current_state == DialogueState.LIVENESS:
            return self._handle_liveness_state(db, session, account, request)

        if current_state == DialogueState.STEP_UP_PIN:
            return self._handle_step_up_pin_state(db, session, account, request)

        # Out of order transition attempt
        return TurnResponse(
            session_id=session.id,
            state=current_state,
            prompt_text="Out of order action received. Please follow the guided security steps.",
            error="INVALID_TRANSITION",
        )

    # =========================================================================
    # STATE HANDLERS
    # =========================================================================

    def _handle_capture_state(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
        request: TurnRequest,
    ) -> TurnResponse:
        """Processes initial payment request from voice transcript or typed fallback."""
        if request.action in (DialogueAction.SUBMIT_PIN, DialogueAction.SUBMIT_LIVENESS, DialogueAction.CONFIRM_READBACK):
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.FAILED,
                prompt_text="Out of order action. Cannot submit PIN, liveness, or confirmation in CAPTURE state.",
                error="INVALID_TRANSITION",
            )

        transcript = (request.transcript or "").strip()

        # Handle silence or blank speech without advancing state
        if not transcript:
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.CAPTURE,
                prompt_text="I didn't hear a payment request. Please state the amount and payee in English or Hinglish.",
            )

        session.raw_transcript = transcript
        session.channel = request.channel

        # 1. Deterministic Number Parser
        amount_res = parse_amount(transcript)

        # 2. Payee Resolver
        payee_res = PayeeResolver.resolve_for_account(db, account.id, transcript)

        # 3. Consensus Cross-Check
        cross_res = self.cross_check_engine.reconcile(transcript, amount_res, payee_res)

        # Log decision event (Zero audio, zero PIN)
        self._record_audit_event(
            db=db,
            session_id=session.id,
            account_id=account.id,
            event_type="PARSE_AND_CROSS_CHECK",
            details={
                "cross_status": cross_res.status.value,
                "amount_parsed": amount_res.amount,
                "payee_status": payee_res.status.value,
            },
        )

        # Handle Cross-Check Decisions
        if cross_res.status == CrossCheckStatus.SUSPICIOUS_PROMPT_INJECTION:
            return self._escalate_to_handoff(
                db=db,
                session=session,
                account=account,
                reason="PROMPT_INJECTION_DETECTED",
                uncertain_field="transcript",
                user_note="Adversarial prompt injection pattern detected in input.",
            )

        if cross_res.status == CrossCheckStatus.LIMIT_EXCEEDED:
            return self._escalate_to_handoff(
                db=db,
                session=session,
                account=account,
                reason="LIMIT_EXCEEDED",
                uncertain_field="amount",
                user_note=cross_res.explanation,
            )

        if cross_res.status == CrossCheckStatus.AMOUNT_MISMATCH or amount_res.status != ParseStatus.SUCCESS:
            session.current_state = DialogueState.CLARIFY_AMOUNT.value
            db.commit()
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.CLARIFY_AMOUNT,
                prompt_text="I'm not certain about the amount. Could you please specify the exact amount in rupees?",
            )

        if (
            cross_res.status in (CrossCheckStatus.PAYEE_MISMATCH, CrossCheckStatus.AMBIGUOUS_PAYEE)
            or payee_res.status != PayeeResolutionStatus.MATCHED
        ):
            session.current_state = DialogueState.CLARIFY_PAYEE.value
            db.commit()
            prompt = payee_res.explanation or "Which beneficiary would you like to pay?"
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.CLARIFY_PAYEE,
                prompt_text=prompt,
            )

        # Cross-Check Agreed: Advance to Read-Back
        session.pending_amount = float(cross_res.final_amount)
        session.pending_payee_name = cross_res.final_payee_name
        session.pending_payee_id = cross_res.final_payee_id
        session.current_state = DialogueState.READBACK.value
        db.commit()

        words = amount_to_words(cross_res.final_amount)
        readback_card = ReadbackCardData(
            amount_digits=cross_res.final_amount,
            amount_words=words,
            payee_name=cross_res.final_payee_name,
            payee_id=cross_res.final_payee_id,
        )

        prompt_text = (
            f"Sending {words} ({cross_res.final_amount}) to {cross_res.final_payee_name}. "
            "Please confirm or say cancel."
        )

        return TurnResponse(
            session_id=session.id,
            state=DialogueState.READBACK,
            prompt_text=prompt_text,
            readback_card=readback_card,
        )

    def _handle_clarification_state(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
        request: TurnRequest,
        current_state: DialogueState,
    ) -> TurnResponse:
        """Processes customer clarification input for amount or payee."""
        clarification_text = (request.transcript or "").strip()

        if not clarification_text:
            return TurnResponse(
                session_id=session.id,
                state=current_state,
                prompt_text="Please provide the clarification to proceed, or say cancel.",
            )

        combined_query = f"{session.raw_transcript} {clarification_text}"

        amount_res = parse_amount(clarification_text)
        if amount_res.status != ParseStatus.SUCCESS:
            amount_res = parse_amount(combined_query)

        payee_res = PayeeResolver.resolve_for_account(db, account.id, clarification_text)
        if payee_res.status != PayeeResolutionStatus.MATCHED:
            payee_res = PayeeResolver.resolve_for_account(db, account.id, combined_query)

        cross_res = self.cross_check_engine.reconcile(combined_query, amount_res, payee_res)

        if cross_res.status == CrossCheckStatus.AGREED:
            session.pending_amount = float(cross_res.final_amount)
            session.pending_payee_name = cross_res.final_payee_name
            session.pending_payee_id = cross_res.final_payee_id
            session.current_state = DialogueState.READBACK.value
            db.commit()

            words = amount_to_words(cross_res.final_amount)
            readback_card = ReadbackCardData(
                amount_digits=cross_res.final_amount,
                amount_words=words,
                payee_name=cross_res.final_payee_name,
                payee_id=cross_res.final_payee_id,
            )
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.READBACK,
                prompt_text=f"Understood. Sending {words} ({cross_res.final_amount}) to {cross_res.final_payee_name}. Please confirm.",
                readback_card=readback_card,
            )

        # Still ambiguous / conflicting -> Safe Human Handoff
        return self._escalate_to_handoff(
            db=db,
            session=session,
            account=account,
            reason="CLARIFICATION_FAILED",
            uncertain_field="amount" if current_state == DialogueState.CLARIFY_AMOUNT else "payee",
            user_note=f"Clarification attempt unresolved: {cross_res.explanation}",
        )

    def _handle_readback_state(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
        request: TurnRequest,
    ) -> TurnResponse:
        """Requires explicit confirmation before generating liveness challenge."""
        transcript_clean = (request.transcript or "").strip().lower()

        # Check for explicit affirmative action or tokens
        is_confirmed = (
            request.action == DialogueAction.CONFIRM_READBACK
            or any(w in transcript_clean for w in ["confirm", "yes", "proceed", "haan", "bhejo", "kar do"])
        )

        if not is_confirmed:
            # Silence or non-affirmative speech does not advance state
            words = amount_to_words(int(session.pending_amount or 0))
            readback_card = ReadbackCardData(
                amount_digits=int(session.pending_amount or 0),
                amount_words=words,
                payee_name=session.pending_payee_name or "",
                payee_id=session.pending_payee_id,
            )
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.READBACK,
                prompt_text="I did not hear a confirmation. Please say confirm or click the Confirm button to proceed.",
                readback_card=readback_card,
            )

        # Explicit confirmation received! Generate single-use liveness challenge
        challenge_digits, challenge_hash, expires_at = generate_liveness_challenge(session.id, account.id)
        session.liveness_challenge = challenge_hash
        session.challenge_expires_at = expires_at
        session.current_state = DialogueState.LIVENESS.value
        db.commit()

        self._record_audit_event(
            db=db,
            session_id=session.id,
            account_id=account.id,
            event_type="LIVENESS_CHALLENGE_ISSUED",
            details={"expires_at": expires_at.isoformat()},
        )

        return TurnResponse(
            session_id=session.id,
            state=DialogueState.LIVENESS,
            liveness_challenge=challenge_digits,
            prompt_text=f"For voice security, please repeat these verification digits: {challenge_digits}",
        )

    def _handle_liveness_state(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
        request: TurnRequest,
    ) -> TurnResponse:
        """Verifies challenge response and acoustic anti-spoof telemetry."""
        if request.action != DialogueAction.SUBMIT_LIVENESS:
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.LIVENESS,
                prompt_text="Please speak the verification digits shown on screen.",
                error="AWAITING_LIVENESS_DIGITS",
            )

        # 1. Verify Challenge-Response Digits
        liv_res = verify_liveness_challenge(
            session=session,
            account_id=account.id,
            response_digits=request.liveness_response,
            channel=request.channel,
        )

        if not liv_res.is_valid:
            # Liveness failed (mismatch or expired) -> Route to handoff
            return self._escalate_to_handoff(
                db=db,
                session=session,
                account=account,
                reason="LIVENESS_FAILED",
                uncertain_field="liveness",
                user_note=liv_res.explanation,
            )

        # 2. Audio Anti-Spoof Acoustic Check
        anti_res = self.antispoof_service.analyze_audio(
            audio_bytes=None,
            telemetry=request.audio_metadata,
        )

        self._record_audit_event(
            db=db,
            session_id=session.id,
            account_id=account.id,
            event_type="ANTISPOOF_EVALUATION",
            details={
                "outcome": anti_res.outcome.value,
                "score": anti_res.score,
                "is_blocked": anti_res.is_blocked,
            },
        )

        if anti_res.is_blocked:
            # High Risk Spoof detected -> Block & escalate
            return self._escalate_to_handoff(
                db=db,
                session=session,
                account=account,
                reason="SPOOF_RISK_HIGH",
                uncertain_field="acoustic_spoof",
                user_note=anti_res.explanation,
            )

        # 3. Evaluate Step-Up PIN Requirement
        payee_contact = None
        if session.pending_payee_id:
            payee_contact = db.query(Contact).filter(Contact.id == session.pending_payee_id).first()

        step_up_eval = PinSecurityManager.evaluate_step_up_needed(
            amount=session.pending_amount,
            payee_contact=payee_contact,
            antispoof_outcome=anti_res.outcome,
            channel=request.channel,
        )

        if step_up_eval.requires_pin:
            session.current_state = DialogueState.STEP_UP_PIN.value
            db.commit()
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.STEP_UP_PIN,
                requires_pin=True,
                prompt_text="Security verification requires your 4-digit PIN to authorize payment.",
                context={"step_up_reasons": step_up_eval.reasons},
            )

        # No Step-Up Required -> Execute Ledger Movement
        session.current_state = DialogueState.EXECUTE.value
        return self._execute_and_finish(db, session, account, request.idempotency_key)

    def _handle_step_up_pin_state(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
        request: TurnRequest,
    ) -> TurnResponse:
        """Verifies customer PIN against salted hash with 3-attempt lockout."""
        if request.action != DialogueAction.SUBMIT_PIN or not request.pin:
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.STEP_UP_PIN,
                requires_pin=True,
                prompt_text="Please enter your 4-digit PIN to proceed.",
                error="PIN_REQUIRED",
            )

        pin_res = PinSecurityManager.verify_pin(session, account, request.pin, db)

        self._record_audit_event(
            db=db,
            session_id=session.id,
            account_id=account.id,
            event_type="PIN_VERIFICATION_ATTEMPT",
            details={
                "is_success": pin_res.is_success,
                "is_locked": pin_res.is_locked,
                "remaining_attempts": pin_res.remaining_attempts,
            },
        )

        if pin_res.is_locked:
            session.current_state = DialogueState.FAILED.value
            db.commit()
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.FAILED,
                prompt_text="Account locked due to 3 consecutive failed PIN attempts. Please contact a human agent.",
                error="PIN_LOCKOUT",
            )

        if not pin_res.is_success:
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.STEP_UP_PIN,
                requires_pin=True,
                prompt_text=pin_res.explanation,
                error="INCORRECT_PIN",
            )

        # PIN Verified! Advance to EXECUTE
        session.current_state = DialogueState.EXECUTE.value
        return self._execute_and_finish(db, session, account, request.idempotency_key)

    def _execute_and_finish(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
        idempotency_key: Optional[str],
    ) -> TurnResponse:
        """Payment execution boundary: interacts with mock ledger atomically."""
        amount = float(session.pending_amount or 0.0)

        # Resolve receiver account
        receiver_id = "acc_ramesh"
        if session.pending_payee_id:
            contact = db.query(Contact).filter(Contact.id == session.pending_payee_id).first()
            if contact and contact.beneficiary_account_id:
                receiver_id = contact.beneficiary_account_id

        tx_key = idempotency_key or session.idempotency_key or f"tx_{uuid.uuid4().hex[:12]}"
        session.idempotency_key = tx_key

        exec_res = PaymentLedgerService.execute_payment(
            db=db,
            sender_id=account.id,
            receiver_id=receiver_id,
            amount=amount,
            description=f"Voice payment to {session.pending_payee_name}",
            idempotency_key=tx_key,
        )

        if not exec_res.success:
            session.current_state = DialogueState.FAILED.value
            db.commit()
            return TurnResponse(
                session_id=session.id,
                state=DialogueState.FAILED,
                prompt_text=f"Payment execution failed: {exec_res.explanation}",
                error=exec_res.explanation,
            )

        # Execution Succeeded -> Transition to RECEIPT
        session.current_state = DialogueState.RECEIPT.value
        db.commit()

        self._record_audit_event(
            db=db,
            session_id=session.id,
            account_id=account.id,
            event_type="PAYMENT_EXECUTED",
            details={
                "tx_id": exec_res.transaction_id,
                "amount": amount,
                "sender_balance_after": exec_res.sender_balance_after,
            },
        )

        receipt = ReceiptData(
            transaction_id=exec_res.transaction_id or tx_key,
            amount=amount,
            payee_name=session.pending_payee_name or "Beneficiary",
            sender_balance_after=exec_res.sender_balance_after or 0.0,
            timestamp=datetime.utcnow().isoformat(),
        )

        return TurnResponse(
            session_id=session.id,
            state=DialogueState.RECEIPT,
            prompt_text=f"Payment of ₹{amount:,.2f} to {session.pending_payee_name} was successful.",
            receipt=receipt,
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_or_create_session(
        self,
        db: Session,
        account: Account,
        request: TurnRequest,
    ) -> Optional[PaymentSession]:
        if request.session_id:
            session = db.query(PaymentSession).filter(PaymentSession.id == request.session_id).first()
            if session:
                if session.account_id != account.id:
                    return None  # Cross-customer session isolation violation
                return session
            return None  # Explicit session_id was provided but does not exist in DB

        # Create fresh session
        new_session = PaymentSession(
            id=f"sess_{uuid.uuid4().hex[:12]}",
            account_id=account.id,
            current_state=DialogueState.CAPTURE.value,
            channel=request.channel,
            idempotency_key=request.idempotency_key or f"tx_{uuid.uuid4().hex[:12]}",
        )
        db.add(new_session)
        db.commit()
        return new_session

    def _handle_cancellation(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
    ) -> TurnResponse:
        session.current_state = DialogueState.CANCELLED.value
        session.liveness_challenge = None
        db.commit()

        self._record_audit_event(
            db=db,
            session_id=session.id,
            account_id=account.id,
            event_type="SESSION_CANCELLED",
            details={"reason": "CUSTOMER_CANCELLED"},
        )

        return TurnResponse(
            session_id=session.id,
            state=DialogueState.CANCELLED,
            prompt_text="The payment request has been cancelled.",
        )

    def _escalate_to_handoff(
        self,
        db: Session,
        session: PaymentSession,
        account: Account,
        reason: str,
        uncertain_field: Optional[str],
        user_note: str,
    ) -> TurnResponse:
        handoff_case = HandoffCase(
            id=f"case_{uuid.uuid4().hex[:12]}",
            session_id=session.id,
            account_id=account.id,
            escalation_reason=reason,
            uncertain_field=uncertain_field,
            context_data=json.dumps({
                "raw_transcript": session.raw_transcript,
                "pending_amount": float(session.pending_amount) if session.pending_amount else None,
                "pending_payee_name": session.pending_payee_name,
                "note": user_note,
            }, default=str),
            status="PENDING",
        )
        db.add(handoff_case)
        session.current_state = DialogueState.HANDOFF.value
        db.commit()

        self._record_audit_event(
            db=db,
            session_id=session.id,
            account_id=account.id,
            event_type="ESCALATED_TO_HANDOFF",
            details={"case_id": handoff_case.id, "reason": reason},
        )

        return TurnResponse(
            session_id=session.id,
            state=DialogueState.HANDOFF,
            handoff_case_id=handoff_case.id,
            prompt_text="Your payment has been escalated to a human banking agent for manual review.",
            context={"case_id": handoff_case.id, "reason": reason},
        )

    def _record_audit_event(
        self,
        db: Session,
        session_id: Optional[str],
        account_id: Optional[str],
        event_type: str,
        details: Dict[str, Any],
    ) -> None:
        """Records an immutable audit event. Explicitly sanitizes raw audio and PINs."""
        # Sanitize sensitive fields
        clean_details = {k: v for k, v in details.items() if k not in ["pin", "raw_audio", "hashed_pin"]}
        event = AuditEvent(
            id=f"aud_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            account_id=account_id,
            event_type=event_type,
            details=json.dumps(clean_details, default=str),
            created_at=datetime.utcnow(),
        )
        db.add(event)
        db.commit()
