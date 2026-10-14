"""
Stage 13 Unit & Integration Tests: Complete and Verify Two-Way Human-Agent Handoff in VaaniPay.

Covers:
1. Customer requests handoff -> case appears in agent queue.
2. Agent sends message -> customer receives it (status transitions to AGENT_CONNECTED).
3. Customer replies -> agent receives it.
4. Messages persist after refreshing / re-fetching.
5. Customer isolation: Customer B cannot read or send messages in Customer A's case (403 Forbidden).
6. Non-agents cannot access agent queue (403 Forbidden).
7. Closed cases (APPROVED, REJECTED, CANCELLED) strictly reject new messages (400 Bad Request).
8. Case deduplication: repeated escalations for the same session reuse the existing active case.
9. Security invariant: PINs and secrets in messages are strictly blocked (422 Unprocessable Entity).
10. Payment safety: agent messaging and reviews never move funds, modify balances, or bypass security.
11. Customer or agent cancellation safely cancels the handoff case and payment session.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.seed import seed_database
from app.models.account import Account
from app.models.session import PaymentSession
from app.models.handoff import HandoffCase, HandoffMessage
from app.models.ledger import LedgerEntry
from app.schemas.handoff import HandoffAction
from tests.conftest import make_auth_headers


def test_customer_requests_handoff_and_appears_in_agent_queue(client: TestClient, db_session: Session):
    """When a customer requests human assistance, case is created and appears in agent queue."""
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")
    agent_headers = make_auth_headers("acc_agent", role="agent")

    # Step 1: Customer initiates a payment session and requests human assistance
    turn_res = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "transcript": "I want to talk to a human agent",
            "action": "REQUEST_HUMAN",
            "channel": "TYPED",
        },
        headers=priya_headers,
    )
    assert turn_res.status_code == 200
    data = turn_res.json()
    assert data["state"] == "HANDOFF"
    assert data["handoff_case_id"] is not None
    case_id = data["handoff_case_id"]

    # Step 2: Case appears in Agent queue
    queue_res = client.get("/api/v1/handoff/cases", headers=agent_headers)
    assert queue_res.status_code == 200
    cases = queue_res.json()
    matching = [c for c in cases if c["id"] == case_id]
    assert len(matching) == 1
    case_info = matching[0]
    assert case_info["customer_name"] == "Priya Sharma"
    assert case_info["account_id"] == "acc_priya"
    assert case_info["status"] in ("PENDING", "WAITING")
    assert case_info["status_display"] == "Waiting"


def test_two_way_messaging_between_customer_and_agent(client: TestClient, db_session: Session):
    """
    Verifies two-way conversation flow:
    - Customer requests handoff.
    - Agent sends a message -> status becomes AGENT_CONNECTED.
    - Customer replies -> agent receives reply.
    """
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")
    agent_headers = make_auth_headers("acc_agent", role="agent")

    # 1. Create a handoff case
    session = PaymentSession(id="sess_h_chat_1", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(
        id="case_chat_101",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="USER_REQUESTED",
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    # 2. Agent sends first message to customer
    agent_msg_res = client.post(
        f"/api/v1/handoff/cases/{case.id}/messages",
        json={"message_text": "Hello Priya, I am your support agent. How can I help you today?"},
        headers=agent_headers,
    )
    assert agent_msg_res.status_code == 200
    msg1 = agent_msg_res.json()
    assert msg1["sender_role"] == "agent"
    assert "support agent" in msg1["message_text"]

    # Verify case status updated to AGENT_CONNECTED
    db_session.expire_all()
    case_reloaded = db_session.query(HandoffCase).filter(HandoffCase.id == case.id).first()
    assert case_reloaded.status == "AGENT_CONNECTED"

    # 3. Customer checks messages
    cust_list_res = client.get(f"/api/v1/handoff/cases/{case.id}/messages", headers=priya_headers)
    assert cust_list_res.status_code == 200
    msgs = cust_list_res.json()
    assert len(msgs) == 1
    assert msgs[0]["sender_role"] == "agent"

    # 4. Customer replies
    cust_reply_res = client.post(
        f"/api/v1/handoff/cases/{case.id}/messages",
        json={"message_text": "I wanted to verify why my payment of 225000 was flagged."},
        headers=priya_headers,
    )
    assert cust_reply_res.status_code == 200
    msg2 = cust_reply_res.json()
    assert msg2["sender_role"] == "customer"
    assert "flagged" in msg2["message_text"]

    # 5. Agent views full conversation
    agent_list_res = client.get(f"/api/v1/handoff/cases/{case.id}/messages", headers=agent_headers)
    assert agent_list_res.status_code == 200
    all_msgs = agent_list_res.json()
    assert len(all_msgs) == 2
    assert all_msgs[0]["sender_role"] == "agent"
    assert all_msgs[1]["sender_role"] == "customer"


def test_messages_persist_after_refresh(client: TestClient, db_session: Session):
    """Messages and case state remain in database across subsequent fetches."""
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")
    agent_headers = make_auth_headers("acc_agent", role="agent")

    session = PaymentSession(id="sess_h_persist", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(
        id="case_persist_102",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="DISAGREEMENT_AMOUNT",
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    # Send messages
    client.post(f"/api/v1/handoff/cases/{case.id}/messages", json={"message_text": "Customer note"}, headers=priya_headers)
    client.post(f"/api/v1/handoff/cases/{case.id}/messages", json={"message_text": "Agent reply"}, headers=agent_headers)

    # Re-fetch active case
    active_res = client.get("/api/v1/handoff/cases/active", headers=priya_headers)
    assert active_res.status_code == 200
    case_data = active_res.json()
    assert case_data["id"] == case.id
    assert len(case_data["messages"]) == 2
    assert case_data["messages"][0]["message_text"] == "Customer note"
    assert case_data["messages"][1]["message_text"] == "Agent reply"


def test_unauthorized_user_cannot_access_or_message_another_customers_case(client: TestClient, db_session: Session):
    """CUSTOMER PRIVACY: Ramesh cannot read or send messages in Priya's handoff case."""
    seed_database(db_session)
    ramesh_headers = make_auth_headers("acc_ramesh", role="customer")

    session = PaymentSession(id="sess_h_priv", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(
        id="case_priv_103",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="USER_REQUESTED",
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    # Ramesh tries to view Priya's case
    r_get = client.get(f"/api/v1/handoff/cases/{case.id}", headers=ramesh_headers)
    assert r_get.status_code == 403
    assert "access denied" in r_get.json()["detail"].lower()

    # Ramesh tries to read Priya's messages
    r_msgs = client.get(f"/api/v1/handoff/cases/{case.id}/messages", headers=ramesh_headers)
    assert r_msgs.status_code == 403

    # Ramesh tries to inject a message into Priya's case
    r_send = client.post(
        f"/api/v1/handoff/cases/{case.id}/messages",
        json={"message_text": "Spy message from Ramesh"},
        headers=ramesh_headers,
    )
    assert r_send.status_code == 403

    # Ramesh tries to list all agent cases
    r_queue = client.get("/api/v1/handoff/cases", headers=ramesh_headers)
    assert r_queue.status_code == 403


def test_closed_cases_reject_new_messages(client: TestClient, db_session: Session):
    """CLOSED CASE INVARIANT: Cases in APPROVED, REJECTED, or CANCELLED status cannot accept messages."""
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")
    agent_headers = make_auth_headers("acc_agent", role="agent")

    session = PaymentSession(id="sess_h_closed", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(
        id="case_closed_104",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="USER_REQUESTED",
        status="APPROVED",  # Already resolved
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    # Customer tries to message closed case
    r_cust = client.post(
        f"/api/v1/handoff/cases/{case.id}/messages",
        json={"message_text": "Trying to chat after closure"},
        headers=priya_headers,
    )
    assert r_cust.status_code == 400
    assert "closed" in r_cust.json()["detail"].lower()

    # Agent also cannot message closed case
    r_agent = client.post(
        f"/api/v1/handoff/cases/{case.id}/messages",
        json={"message_text": "Agent message to closed case"},
        headers=agent_headers,
    )
    assert r_agent.status_code == 400


def test_duplicate_submissions_reuse_active_case(client: TestClient, db_session: Session):
    """CASE DEDUPLICATION: Multiple escalation triggers in the same session reuse the existing active case."""
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")

    # Initial turn that escalates to handoff
    r1 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "transcript": "Talk to specialist",
            "action": "REQUEST_HUMAN",
            "channel": "TYPED",
        },
        headers=priya_headers,
    )
    assert r1.status_code == 200
    case_id_1 = r1.json()["handoff_case_id"]
    sess_id = r1.json()["session_id"]

    # Second turn with repeated request on same session
    r2 = client.post(
        "/api/v1/turn",
        json={
            "account_id": "acc_priya",
            "session_id": sess_id,
            "transcript": "I need a human agent now",
            "action": "REQUEST_HUMAN",
            "channel": "TYPED",
        },
        headers=priya_headers,
    )
    assert r2.status_code == 200
    case_id_2 = r2.json()["handoff_case_id"]

    # Must reuse exact same case ID
    assert case_id_1 == case_id_2

    # Total cases for this session must be exactly 1
    case_count = db_session.query(HandoffCase).filter(HandoffCase.session_id == sess_id).count()
    assert case_count == 1


def test_pin_and_secrets_strictly_rejected_in_messages(client: TestClient, db_session: Session):
    """SECURITY INVARIANT: PINs and secrets cannot be transmitted in chat messages."""
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")

    session = PaymentSession(id="sess_h_pin", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(
        id="case_pin_105",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="USER_REQUESTED",
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    # Attempt 1: Transmitting PIN with keyword
    r1 = client.post(
        f"/api/v1/handoff/cases/{case.id}/messages",
        json={"message_text": "Here is my PIN 1234 please process"},
        headers=priya_headers,
    )
    assert r1.status_code == 422
    assert "pin" in r1.json()["detail"].lower()

    # Attempt 2: Standalone 4-digit code
    r2 = client.post(
        f"/api/v1/handoff/cases/{case.id}/messages",
        json={"message_text": "1234"},
        headers=priya_headers,
    )
    assert r2.status_code == 422

    # Verify no message was stored
    msg_count = db_session.query(HandoffMessage).filter(HandoffMessage.case_id == case.id).count()
    assert msg_count == 0


def test_agent_conversation_cannot_bypass_payment_safety_or_move_funds(client: TestClient, db_session: Session):
    """PAYMENT SAFETY: Chatting with an agent never debits sender, credits payee, or approves transfer."""
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")
    agent_headers = make_auth_headers("acc_agent", role="agent")

    initial_priya_bal = db_session.query(Account).filter(Account.id == "acc_priya").first().balance
    initial_ledger_count = db_session.query(LedgerEntry).count()

    session = PaymentSession(id="sess_h_safe", account_id="acc_priya", current_state="HANDOFF", pending_amount=1500.0)
    case = HandoffCase(
        id="case_safe_106",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="USER_REQUESTED",
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    # Exchange messages
    client.post(f"/api/v1/handoff/cases/{case.id}/messages", json={"message_text": "Please approve my payment"}, headers=priya_headers)
    client.post(f"/api/v1/handoff/cases/{case.id}/messages", json={"message_text": "I am reviewing your account"}, headers=agent_headers)

    # Verify zero balance change
    db_session.expire_all()
    final_priya_bal = db_session.query(Account).filter(Account.id == "acc_priya").first().balance
    final_ledger_count = db_session.query(LedgerEntry).count()

    assert final_priya_bal == initial_priya_bal
    assert final_ledger_count == initial_ledger_count


def test_case_cancellation_safely_terminates_session(client: TestClient, db_session: Session):
    """Customer can safely cancel the handoff case and pending payment."""
    seed_database(db_session)
    priya_headers = make_auth_headers("acc_priya", role="customer")

    session = PaymentSession(id="sess_h_cancel", account_id="acc_priya", current_state="HANDOFF")
    case = HandoffCase(
        id="case_cancel_107",
        session_id=session.id,
        account_id="acc_priya",
        escalation_reason="USER_REQUESTED",
        status="PENDING",
    )
    db_session.add(session)
    db_session.add(case)
    db_session.commit()

    cancel_res = client.post(f"/api/v1/handoff/cases/{case.id}/cancel", headers=priya_headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"
    assert cancel_res.json()["status_display"] == "Cancelled"

    db_session.expire_all()
    session_reloaded = db_session.query(PaymentSession).filter(PaymentSession.id == session.id).first()
    assert session_reloaded.current_state == "CANCELLED"
