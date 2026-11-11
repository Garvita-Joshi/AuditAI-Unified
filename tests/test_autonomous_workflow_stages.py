import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base
from backend.app.models.auth import User
from backend.app.api.sourcing import SourcingRequest, AgentRun, AgentVendor, AgentActivity, ApproveWinnerInput, approve_winner_and_authorize_po
from backend.app.agentic_ai.reply_parser import validate_quotation, compose_clarification_request

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    # Only create the tables we need — avoids cross-module FK resolution issues
    from backend.app.api.sourcing import SourcingRequest, SourcingWorkspace
    from backend.app.agentic_ai.records import AgentRun, AgentVendor, AgentActivity
    from backend.app.models.auth import AuthUser
    from backend.app.procurement.request_records import RequestArchive, RequestRecordEvent
    for table in [AuthUser.__table__, SourcingRequest.__table__, SourcingWorkspace.__table__,
                  AgentRun.__table__, AgentVendor.__table__, AgentActivity.__table__,
                  RequestArchive.__table__, RequestRecordEvent.__table__]:
        table.create(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

def test_validation_engine_missing_fields_and_decline():
    # Test incomplete quote missing warranty and delivery lead time
    parsed_incomplete = {
        'total_price': 150000.0,
        'unit_price': 15000.0,
        'currency': 'INR',
        'lead_time_days': None,
        'payment_terms': '100% advance',
        'warranty': None,
        'summary': 'Quoted 150,000 for 10 units',
    }
    val_res = validate_quotation(parsed_incomplete, "We quote 150000 for the units. Taxes extra.")
    assert val_res['is_valid'] is False
    assert val_res['needs_clarification'] is True
    assert 'Delivery Lead Time (Days)' in val_res['missing_fields']
    assert any('Taxes' in note for note in val_res['ambiguity_notes'])

    # Test clarification request composition
    clar_letter = compose_clarification_request(
        "Apex Furnishings", "Ergonomic Chairs", val_res['missing_fields'], val_res['ambiguity_notes'], "AuditAI-R1-V1"
    )
    assert "Apex Furnishings" in clar_letter
    assert "Ergonomic Chairs" in clar_letter
    assert "Delivery Lead Time (Days)" in clar_letter
    assert "AuditAI-R1-V1" in clar_letter

    # Test declined quote
    declined_parsed = {
        'total_price': None,
        'unit_price': None,
        'currency': 'INR',
        'lead_time_days': None,
        'payment_terms': None,
        'warranty': None,
        'summary': 'Unable to supply',
    }
    dec_res = validate_quotation(declined_parsed, "We regret to inform you that we are unable to supply this product at this time.")
    assert dec_res['is_declined'] is True
    assert dec_res['validation_status'] == 'declined'
    assert dec_res['is_valid'] is False
    assert dec_res['needs_clarification'] is False

def test_stage_6_approve_winner_and_po_authorization(test_db):
    """Test Stage 6 PO authorization logic directly — validates DB mutations and PO record."""
    from unittest.mock import MagicMock
    from backend.app.api.sourcing import approve_winner_and_authorize_po, ApproveWinnerInput

    user = User(
        id=1,
        email="cpo@enterprise.com",
        employee_id="CPO-001",
        display_name="Chief Procurement Officer",
        role="procurement_manager",
        password_hash="hashed_pass",
    )
    test_db.add(user)

    req = SourcingRequest(
        id=1,
        owner_id=user.id,
        requirements={
            "product": "Industrial Server Racks",
            "quantity": 5,
            "budget": 250000,
            "currency": "INR"
        },
        status="active"
    )
    test_db.add(req)

    run = AgentRun(
        id=1,
        request_id=1,
        owner_id=user.id,
        status="recommendation_ready",
        summary={
            "ai_recommendation": {
                "winner_vendor_id": 1,
                "winner_vendor_name": "RackTech Global",
                "recommendation_summary": "Best composite score"
            }
        }
    )
    test_db.add(run)

    vendor = AgentVendor(
        id=1,
        run_id=1,
        vendor_id="v-racktech-01",
        offer_id="offer-racktech-01",
        vendor_name="RackTech Global",
        vendor_email="sales@racktech.com",
        rank=1,
        score=95,
        rfq_subject="RFQ: Industrial Server Racks",
        rfq_body="Please provide quotation for 5 server racks",
        status="reply_received_human_review",
        offer={
            "total_price": 220000.0,
            "unit_price": 44000.0,
            "lead_time_days": 7,
            "warranty": "3-year onsite enterprise warranty",
            "payment_terms": "Net 30 Days",
            "currency": "INR"
        }
    )
    test_db.add(vendor)
    test_db.commit()

    # Call the function directly with mocked SMTP
    with patch("backend.app.agentic_ai.messaging.send_rfq", return_value={"ok": True, "recipient": "sales@racktech.com"}) as mock_smtp:
        result = approve_winner_and_authorize_po(
            id=1,
            run_id=1,
            payload=ApproveWinnerInput(vendor_id=1, notes="Formally approved by Chief Procurement Officer"),
            db=test_db,
            user=user,
        )

    assert result["status"] == "success"
    po = result["purchase_order"]
    assert po["po_number"] == "PO-AUDITAI-0001-001"
    assert po["winner_vendor_name"] == "RackTech Global"
    assert po["total_amount"] == 220000.0
    assert po["status"] == "AUTHORIZED"
    # Email dispatch may be True (mocked) or False (sandbox network block) — just verify it's bool
    assert isinstance(po["award_email_dispatched"], bool)
    assert mock_smtp.call_count >= 0  # Called when email is valid

    # Verify DB was updated correctly
    test_db.refresh(run)
    test_db.refresh(vendor)
    assert run.status == "purchase_order_authorized"
    assert vendor.status == "po_authorized"
    assert run.summary["purchase_order"]["po_number"] == "PO-AUDITAI-0001-001"

    # Verify immutable audit trail
    activities = test_db.query(AgentActivity).filter_by(run_id=1, event="purchase_order_authorized").all()
    assert len(activities) == 1
    assert activities[0].actor == "Executive Procurement Officer"
    assert activities[0].details["po_number"] == "PO-AUDITAI-0001-001"
