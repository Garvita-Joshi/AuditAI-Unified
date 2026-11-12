from datetime import datetime
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.assistant import router as assistant_router
from backend.app.auth.security import get_current_user
from backend.app.db import Base, get_db
from backend.app.models.auth import AuthUser
from backend.app.api.sourcing import SourcingRequest, SourcingSearch
from backend.app.models.expense import ExpenseClaim
from backend.app.models.review_queue import ReviewRecord
from backend.app.models.procurement import ProcurementPayment


@pytest.fixture
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    user = AuthUser(
        id=1,
        email="prepares23@gmail.com",
        employee_id="E-001",
        display_name="Garvita Joshi",
        role="admin",
        roles=["admin", "procurement"],
        password_hash="fake_hash",
        active=True,
    )
    db.add(user)
    db.commit()

    app = FastAPI()
    app.include_router(assistant_router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user

    client = TestClient(app)
    yield client, db

    db.close()


def test_assistant_context_and_chat(client_and_db):
    client, db = client_and_db

    # Add a mock sourcing request
    sr = SourcingRequest(
        id=1,
        owner_id=1,
        requirements={"product": "MacBook Pro M3", "quantity": 5, "budget": 10000, "currency": "USD"},
        status="ready_for_research",
        version=1,
    )
    db.add(sr)
    # Add an expense claim
    claim = ExpenseClaim(
        claim_id="EXP-9901",
        employee_id="EMP-10",
        employee_name="Alice Smith",
        claimed_amount=Decimal("45000.00"),
        vendor_name="Acme Travel Corp",
        claimed_date=datetime.now().date(),
        status="flagged",
    )
    db.add(claim)
    # Add a review queue record
    rec = ReviewRecord(
        source_key="EXP-9901-REVIEW",
        case_type="Expense Claim",
        source_id=1,
        severity="HIGH",
        reason="Suspicious round trip amount",
        evidence={"amount": 45000},
        status="open",
    )
    db.add(rec)
    db.commit()

    # Test context
    res = client.get("/api/v1/assistant/context")
    assert res.status_code == 200
    data = res.json()
    assert data["procurement"]["total_requests"] == 1
    assert data["procurement"]["recent_requests"][0]["product"] == "MacBook Pro M3"
    assert data["fraud_detection"]["flagged_claims_count"] == 1
    assert data["review_queue"]["open_cases_count"] == 1

    # Test chat status inquiry
    res = client.post("/api/v1/assistant/chat", json={"message": "What is the current status of the system?"})
    assert res.status_code == 200
    body = res.json()
    assert "reply" in body
    assert "AuditAI Platform Live Status" in body["reply"]

    # Test chat PR lookup
    res = client.post("/api/v1/assistant/chat", json={"message": "Tell me about SR-0001"})
    assert res.status_code == 200
    body = res.json()
    assert "MacBook Pro M3" in body["reply"]
    assert "10,000.00" in body["reply"]

    # Test fraud inquiry
    res = client.post("/api/v1/assistant/chat", json={"message": "Are there any flagged claims or fraud anomalies?"})
    assert res.status_code == 200
    body = res.json()
    assert "EXP-9901" in body["reply"]
    assert "Alice Smith" in body["reply"]

    # Test review queue inquiry
    res = client.post("/api/v1/assistant/chat", json={"message": "What cases are pending in the review queue?"})
    assert res.status_code == 200
    body = res.json()
    assert "HIGH" in body["reply"]
    assert "Suspicious round trip amount" in body["reply"]

    # Test payments inquiry
    res = client.post("/api/v1/assistant/chat", json={"message": "What is the PayPal Sandbox payment status?"})
    assert res.status_code == 200
    body = res.json()
    assert "PayPal Sandbox" in body["reply"]
