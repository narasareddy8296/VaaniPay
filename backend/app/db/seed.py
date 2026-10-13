"""
Repeatable seed data generation for VaaniPay synthetic mock banking environment.
Creates demo customers (Priya & Ramesh), their contacts, aliases, and initial balances.
Designed to be strictly idempotent: running multiple times never duplicates records.
"""

import hashlib
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.db.database import SessionLocal, Base, engine
from app.models.account import Account
from app.models.contact import Contact


def _hash_demo_pin(pin: str) -> str:
    """Creates a secure Argon2id hash for mock demo PINs (NEVER store plaintext)."""
    from app.core.auth_step_up import PinSecurityManager
    return PinSecurityManager.hash_pin(pin)


# Deterministic Synthetic Accounts
DEMO_ACCOUNTS = [
    {
        "id": "acc_priya",
        "account_number": "ACC_PRIYA_001",
        "holder_name": "Priya Sharma",
        "phone_number": "+919876543210",
        "role": "customer",
        "pin": "1234",
        "balance": 50000.00,
        "currency": "INR",
    },
    {
        "id": "acc_ramesh",
        "account_number": "ACC_RAMESH_002",
        "holder_name": "Ramesh Kumar",
        "phone_number": "+919876543211",
        "role": "customer",
        "pin": "5678",
        "balance": 25000.00,
        "currency": "INR",
    },
    {
        "id": "acc_agent",
        "account_number": "ACC_AGENT_001",
        "holder_name": "Support Agent (Human)",
        "phone_number": "+919876543299",
        "role": "agent",
        "pin": "9999",
        "balance": 0.00,
        "currency": "INR",
    },
]

# Contacts for Priya Sharma
PRIYA_CONTACTS = [
    {
        "id": "cnt_priya_ramesh",
        "contact_name": "Ramesh Kumar",
        "phone_number": "+919876543211",
        "beneficiary_account_id": "acc_ramesh",
        "aliases": "Ramesh,Rameshh,Ram",
        "is_frequent": True,
    },
    {
        "id": "cnt_priya_sharmaji",
        "contact_name": "Sharmaji",
        "phone_number": "+919876543212",
        "beneficiary_account_id": None,
        "aliases": "Sharmaji,Papa,Dad",
        "is_frequent": True,
    },
    {
        "id": "cnt_priya_neha",
        "contact_name": "Neha",
        "phone_number": "+919876543213",
        "beneficiary_account_id": None,
        "aliases": "Neha,Neha Di",
        "is_frequent": True,
    },
]

# Contacts for Ramesh Kumar
RAMESH_CONTACTS = [
    {
        "id": "cnt_ramesh_priya",
        "contact_name": "Priya Sharma",
        "phone_number": "+919876543210",
        "beneficiary_account_id": "acc_priya",
        "aliases": "Priya,Priyaji",
        "is_frequent": True,
    },
    {
        "id": "cnt_ramesh_amit",
        "contact_name": "Amit",
        "phone_number": "+919876543214",
        "beneficiary_account_id": None,
        "aliases": "Amit,Bhai",
        "is_frequent": True,
    },
]


def seed_database(db: Session) -> Dict[str, Any]:
    """
    Idempotent seed operation.
    Upserts accounts and contacts without generating duplicate records.
    """
    accounts_seeded = 0
    contacts_seeded = 0

    # 1. Seed Accounts
    for acc_data in DEMO_ACCOUNTS:
        existing_account = db.query(Account).filter(Account.id == acc_data["id"]).first()
        if not existing_account:
            # Check by unique account number or phone
            existing_account = db.query(Account).filter(
                (Account.account_number == acc_data["account_number"]) |
                (Account.phone_number == acc_data["phone_number"])
            ).first()

        if existing_account:
            # Idempotent update of non-destructive attributes
            existing_account.holder_name = acc_data["holder_name"]
            existing_account.role = acc_data["role"]
            existing_account.balance = acc_data["balance"]
            existing_account.currency = acc_data["currency"]
            existing_account.hashed_pin = _hash_demo_pin(acc_data["pin"])
            existing_account.is_active = True
            existing_account.is_locked = False
        else:
            new_account = Account(
                id=acc_data["id"],
                account_number=acc_data["account_number"],
                holder_name=acc_data["holder_name"],
                phone_number=acc_data["phone_number"],
                role=acc_data["role"],
                hashed_pin=_hash_demo_pin(acc_data["pin"]),
                balance=acc_data["balance"],
                currency=acc_data["currency"],
                is_active=True,
                is_locked=False,
            )
            db.add(new_account)
            accounts_seeded += 1

    db.commit()

    # 2. Seed Priya's Contacts
    for cnt_data in PRIYA_CONTACTS:
        existing_contact = db.query(Contact).filter(
            Contact.account_id == "acc_priya",
            Contact.contact_name == cnt_data["contact_name"],
        ).first()

        if existing_contact:
            existing_contact.aliases = cnt_data["aliases"]
            existing_contact.phone_number = cnt_data["phone_number"]
            existing_contact.beneficiary_account_id = cnt_data["beneficiary_account_id"]
            existing_contact.is_frequent = cnt_data["is_frequent"]
        else:
            new_contact = Contact(
                id=cnt_data["id"],
                account_id="acc_priya",
                contact_name=cnt_data["contact_name"],
                phone_number=cnt_data["phone_number"],
                beneficiary_account_id=cnt_data["beneficiary_account_id"],
                aliases=cnt_data["aliases"],
                is_frequent=cnt_data["is_frequent"],
            )
            db.add(new_contact)
            contacts_seeded += 1

    # 3. Seed Ramesh's Contacts
    for cnt_data in RAMESH_CONTACTS:
        existing_contact = db.query(Contact).filter(
            Contact.account_id == "acc_ramesh",
            Contact.contact_name == cnt_data["contact_name"],
        ).first()

        if existing_contact:
            existing_contact.aliases = cnt_data["aliases"]
            existing_contact.phone_number = cnt_data["phone_number"]
            existing_contact.beneficiary_account_id = cnt_data["beneficiary_account_id"]
            existing_contact.is_frequent = cnt_data["is_frequent"]
        else:
            new_contact = Contact(
                id=cnt_data["id"],
                account_id="acc_ramesh",
                contact_name=cnt_data["contact_name"],
                phone_number=cnt_data["phone_number"],
                beneficiary_account_id=cnt_data["beneficiary_account_id"],
                aliases=cnt_data["aliases"],
                is_frequent=cnt_data["is_frequent"],
            )
            db.add(new_contact)
            contacts_seeded += 1

    db.commit()

    total_accounts = db.query(Account).count()
    total_contacts = db.query(Contact).count()

    return {
        "status": "seeded",
        "accounts_total": total_accounts,
        "contacts_total": total_contacts,
        "newly_added_accounts": accounts_seeded,
        "newly_added_contacts": contacts_seeded,
    }


if __name__ == "__main__":
    # CLI execution support
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        result = seed_database(session)
        print("Seed result:", result)
