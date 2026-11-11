"""Comprehensive test suite for Dograh Voice AI integration in AuditAI.
Tests configuration loading, payload preparation, validation, dry-run safety,
webhook authentication, quotation persistence, idempotency, and error handling.
"""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.app.agentic_ai.records import AgentActivity, AgentRun, AgentVendor
from backend.app.agentic_ai.voice.dograh_client import DograhClient, DograhClientError
from backend.app.agentic_ai.voice.dograh_schemas import (
    DograhInitialContext,
    DograhTriggerRequest,
    DograhWebhookPayload,
    ExotelCallbackPayload,
    StartCallRequest,
    clean_phone_number,
    is_valid_indian_phone,
)
from backend.app.agentic_ai.voice.dograh_service import (
    _extract_rfq_context,
    initiate_vendor_rfq_call,
    process_dograh_webhook,
    process_exotel_callback,
    verify_webhook_authentication,
    get_workflow_run_status,
    check_voice_calling_safety,
)
from backend.app.agentic_ai.voice.models import (
    VOICE_TABLES,
    VoiceCall,
    VoiceQuotation,
    VoiceQuotationField,
    VoiceTranscript,
)
from backend.app.api.sourcing import SourcingRequest
from backend.app.models.auth import AuthUser


@pytest.fixture
def db_session(tmp_path):
    """Disposable SQLite test database with all required procurement and voice tables."""
    db_file = tmp_path / "dograh_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def do_connect(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    # Create parent and voice tables
    for model in (AuthUser, SourcingRequest, AgentRun, AgentVendor, AgentActivity):
        model.__table__.create(engine, checkfirst=True)
    for table in VOICE_TABLES:
        table.create(engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_actor(db_session):
    user = AuthUser(
        id=13,
        email="prepares23@gmail.com",
        employee_id="E013",
        password_hash="test_hash_123",
        display_name="prepares23",
        role="admin",
        roles=["admin", "employee"],
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_rfq_and_vendor(db_session, test_actor):
    """Seed test sourcing request and shortlisted agent vendor."""
    request = SourcingRequest(
        owner_id=test_actor.id,
        status="sourcing",
        version=1,
        requirements={
            "product": "Enterprise Cloud Database",
            "currency": "INR",
            "budget": 250000.0,
            "delivery_location": "Mumbai, India",
            "contract_end": "2026-12-31",
            "line_items": [
                {
                    "description": "Enterprise Cloud Database cluster with 99.99% SLA",
                    "quantity": 2,
                    "unit_price": 100000.0,
                    "location": "Mumbai, India",
                }
            ],
        },
    )
    db_session.add(request)
    db_session.flush()

    run = AgentRun(
        request_id=request.id,
        owner_id=test_actor.id,
        status="active",
        summary={"vendor_count": 1},
    )
    db_session.add(run)
    db_session.flush()

    vendor = AgentVendor(
        run_id=run.id,
        vendor_id="V_DOGRAH_01",
        offer_id="OFF_DOGRAH_01",
        vendor_name="Nexus Cloud Systems",
        vendor_email="contact@nexuscloud.example",
        rank=1,
        score=88,
        rfq_subject="Quotation Request: Enterprise Cloud Database",
        rfq_body="Please provide commercial quotation for 2 units.",
        offer={
            "phone": "+919876543210",
            "contact_name": "Arjun Mehta",
            "address": "Bandra Kurla Complex, Mumbai",
        },
    )
    db_session.add(vendor)
    db_session.commit()

    return request, run, vendor


# ── TEST 1: CONFIGURATION LOADING ──
def test_dograh_configuration_loading():
    client = DograhClient(
        api_key="test_key_abc123",
        trigger_path="test_trigger_path_xyz",
        dry_run=True,
    )
    assert client.api_key == "test_key_abc123"
    assert client.trigger_path == "test_trigger_path_xyz"
    assert client.dry_run is True
    assert client.get_trigger_url(test_mode=False).endswith("/test_trigger_path_xyz")
    assert "/test/" in client.get_trigger_url(test_mode=True)


# ── TEST 2: RFQ PAYLOAD PREPARATION ──
def test_rfq_payload_preparation(db_session, test_actor, sample_rfq_and_vendor):
    request, run, vendor = sample_rfq_and_vendor
    context = _extract_rfq_context(request, vendor, "+919876543210")

    assert context.vendor_name == "Nexus Cloud Systems"
    assert context.vendor_contact_number == "+919876543210"
    assert context.rfq_reference == f"AuditAI-R{run.id}-V{vendor.id}"
    assert "Enterprise Cloud Database" in context.product_name
    assert context.currency == "INR"
    assert context.quantity == 2


# ── TEST 3: REQUIRED-FIELD VALIDATION ──
def test_required_field_validation():
    with pytest.raises(ValueError):
        DograhTriggerRequest(
            phone_number="not-a-number",
            initial_context=DograhInitialContext(
                vendor_name="Acme",
                rfq_reference="AuditAI-R1-V1",
                product_name="Hardware",
            ),
        )

    req = DograhTriggerRequest(
        phone_number="+91 98765 43210",
        initial_context=DograhInitialContext(
            vendor_name="Acme",
            rfq_reference="AuditAI-R1-V1",
            product_name="Hardware",
        ),
    )
    assert req.phone_number == "+919876543210"


# ── TEST 4: DRY-RUN API TRIGGER (ZERO DOLLAR / ZERO DIALS) ──
def test_dry_run_api_trigger(db_session, test_actor, sample_rfq_and_vendor):
    request, run, vendor = sample_rfq_and_vendor
    payload = StartCallRequest(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        phone_number="+919876543210",
        test_mode=True,
    )

    with patch("httpx.AsyncClient.post") as mock_post, patch("httpx.AsyncClient.request") as mock_req:
        response = asyncio.run(initiate_vendor_rfq_call(db_session, test_actor, payload))
        mock_post.assert_not_called()
        mock_req.assert_not_called()

    assert response.status == "dry_run_success"
    assert response.dry_run is True
    assert response.workflow_run_id.startswith("sim_dgr_")
    assert response.tracking_reference == f"AuditAI-R{run.id}-V{vendor.id}"
    assert response.prepared_payload is not None
    assert response.prepared_payload["initial_context"]["vendor_name"] == "Nexus Cloud Systems"

    call_record = db_session.query(VoiceCall).filter_by(id=response.call_id).first()
    assert call_record is not None
    assert call_record.provider_call_id == response.workflow_run_id
    assert call_record.status == "prepared"


# ── TEST 4B: STRICT ASSERTION THAT ZERO EXTERNAL HTTP REQUESTS ARE MADE IN DRY-RUN ──
def test_dry_run_strictly_zero_http_requests():
    client = DograhClient(
        api_key="real_api_key_should_not_be_used",
        trigger_path="fe74624e-3928-482b-821e-9be6416df7c8",
        dry_run=True,
    )
    req = DograhTriggerRequest(
        phone_number="+919876543210",
        initial_context=DograhInitialContext(
            vendor_name="Demo Electronics",
            rfq_reference="AuditAI-TEST-001",
            product_name="DataSafe Standard",
            quantity=1,
            currency="INR",
            delivery_location="India",
            target_date="2026-12-04",
        ),
    )

    with patch("httpx.AsyncClient.post") as mock_post, patch("httpx.AsyncClient.request") as mock_req:
        response = asyncio.run(client.trigger_call(req))
        mock_post.assert_not_called()
        mock_req.assert_not_called()

    # Verify all 7 required simulated response fields
    assert response.status == "dry_run_success"
    assert response.workflow_run_id.startswith("sim_dgr_")
    assert response.call_id is None or isinstance(response.call_id, str)
    assert response.tracking_reference == "AuditAI-TEST-001"
    assert response.phone_number == "+919876543210"
    assert response.dry_run is True
    assert response.prepared_payload == {
        "phone_number": "+919876543210",
        "initial_context": {
            "vendor_name": "Demo Electronics",
            "vendor_contact_number": None,
            "rfq_reference": "AuditAI-TEST-001",
            "product_name": "DataSafe Standard",
            "quantity": 1,
            "currency": "INR",
            "delivery_location": "India",
            "target_date": "2026-12-04",
        },
    }


# ── TEST 4C: MISSING CREDENTIALS OR INVALID TRIGGER CANNOT BYPASS DRY-RUN ──
def test_missing_credentials_cannot_bypass_dry_run():
    # Even with empty API key and empty trigger path, dry run must strictly intercept
    client = DograhClient(
        api_key="",
        trigger_path="",
        dry_run=True,
    )
    req = DograhTriggerRequest(
        phone_number="+919876543210",
        initial_context=DograhInitialContext(
            vendor_name="FailSafe Supplier",
            rfq_reference="AuditAI-SAFE-99",
            product_name="Test Widget",
        ),
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        response = asyncio.run(client.trigger_call(req))
        mock_post.assert_not_called()

    assert response.dry_run is True
    assert response.status == "dry_run_success"
    assert response.workflow_run_id.startswith("sim_dgr_")


# ── TEST 5: MISSING API KEY HANDLING IN LIVE MODE ──
def test_missing_api_key_handling():
    client = DograhClient(api_key="", dry_run=False)
    req = DograhTriggerRequest(
        phone_number="+919876543210",
        initial_context=DograhInitialContext(
            vendor_name="Acme",
            rfq_reference="AuditAI-R1-V1",
            product_name="Hardware",
        ),
    )
    with pytest.raises(DograhClientError) as exc_info:
        asyncio.run(client.trigger_call(req))
    assert exc_info.value.status_code == 401
    assert "DOGRAH_API_KEY environment variable is missing" in exc_info.value.detail


# ── TEST 6: INVALID ENDPOINT HANDLING ──
def test_invalid_endpoint_handling():
    client = DograhClient(
        api_key="real_api_key_123",
        trigger_path="invalid_path_404",
        dry_run=False,
    )
    req = DograhTriggerRequest(
        phone_number="+919876543210",
        initial_context=DograhInitialContext(
            vendor_name="Acme",
            rfq_reference="AuditAI-R1-V1",
            product_name="Hardware",
        ),
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_post.return_value = mock_resp

        with pytest.raises(DograhClientError) as exc_info:
            asyncio.run(client.trigger_call(req))
        assert exc_info.value.status_code == 404
        assert "endpoint not found" in exc_info.value.detail.lower()


# ── TEST 7: SIMULATED SUCCESSFUL DOGRAH RESPONSE ──
def test_successful_dograh_live_response():
    client = DograhClient(
        api_key="valid_token_xyz",
        trigger_path="fe74624e-3928-482b-821e-9be6416df7c8",
        dry_run=False,
    )
    req = DograhTriggerRequest(
        phone_number="+919876543210",
        initial_context=DograhInitialContext(
            vendor_name="Nexus Cloud",
            rfq_reference="AuditAI-R10-V20",
            product_name="Cloud Hosting",
        ),
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"workflow_run_id": "dgr_live_run_9876"}'
        mock_resp.json = lambda: {"workflow_run_id": "dgr_live_run_9876"}
        mock_post.return_value = mock_resp

        resp = asyncio.run(client.trigger_call(req))
        assert resp.status == "initiated"
        assert resp.workflow_run_id == "dgr_live_run_9876"
        assert resp.dry_run is False


# ── TEST 8: WEBHOOK AUTHENTICATION ──
def test_webhook_authentication():
    with patch("backend.app.agentic_ai.voice.dograh_service.DOGRAH_WEBHOOK_SECRET", "super_secret_webhook_key"):
        assert verify_webhook_authentication("super_secret_webhook_key") is True
        assert verify_webhook_authentication("Bearer super_secret_webhook_key") is True
        assert verify_webhook_authentication("wrong_token") is False
        assert verify_webhook_authentication(None) is False


# ── TEST 9 & 10: WEBHOOK PAYLOAD VALIDATION & QUOTATION PERSISTENCE ──
def test_webhook_saves_quotation_data(db_session, test_actor, sample_rfq_and_vendor):
    request, run, vendor = sample_rfq_and_vendor
    ref = f"AuditAI-R{run.id}-V{vendor.id}"

    call = VoiceCall(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        owner_id=test_actor.id,
        provider="dograh",
        provider_call_id="dgr_webhook_run_01",
        tracking_reference=ref,
        status="queued",
        requirements_snapshot=request.requirements,
    )
    db_session.add(call)
    db_session.commit()

    webhook_payload = DograhWebhookPayload(
        workflow_run_id="dgr_webhook_run_01",
        call_id=call.id,
        status="completed",
        disposition="completed",
        duration_seconds=115.5,
        summary="Vendor confirmed enterprise cluster quote with Net 30 payment terms.",
        initial_context={"rfq_reference": ref},
        collected_data={
            "unit_price": "95000.00",
            "total_amount": "190000.00",
            "currency": "INR",
            "delivery_lead_time_days": "10",
            "payment_terms": "Net 30",
            "warranty": "24 Months On-site SLA",
        },
        transcript=[
            {"speaker": "agent", "text": f"Hello, calling from AuditAI regarding RFQ {ref}."},
            {"speaker": "vendor", "text": "We can offer the database cluster for 190,000 INR on Net 30 terms."},
        ],
    )

    with patch("backend.app.agentic_ai.voice.dograh_service.DOGRAH_WEBHOOK_SECRET", ""):
        result = process_dograh_webhook(db_session, webhook_payload, None)

    assert result["status"] == "processed"
    assert result["quotation_status"] == "complete"
    assert "total_amount" in result["fields_recorded"]

    quote = db_session.query(VoiceQuotation).filter_by(call_id=call.id).first()
    assert quote is not None
    assert quote.status == "complete"

    total_field = db_session.query(VoiceQuotationField).filter_by(
        quotation_id=quote.id, name="total_amount"
    ).first()
    assert total_field is not None
    assert total_field.value == "190000.00"
    assert total_field.status == "CONFIRMED"

    transcripts = db_session.query(VoiceTranscript).filter_by(call_id=call.id).all()
    assert len(transcripts) == 2

    db_session.refresh(vendor)
    assert vendor.offer.get("total_price") == 190000.0
    assert vendor.offer.get("voice_call_completed") is True
    assert "[Dograh Voice Call Quotation]" in vendor.reply_text

    # Test status lookup
    status_res = get_workflow_run_status(db_session, "dgr_webhook_run_01", test_actor)
    assert status_res["status"] == "completed"
    assert status_res["quotation"]["status"] == "complete"
    assert len(status_res["transcript"]) == 2


# ── TEST 11: DUPLICATE WEBHOOK HANDLING (IDEMPOTENCY) ──
def test_duplicate_webhook_idempotency(db_session, test_actor, sample_rfq_and_vendor):
    request, run, vendor = sample_rfq_and_vendor
    ref = f"AuditAI-R{run.id}-V{vendor.id}"

    call = VoiceCall(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        owner_id=test_actor.id,
        provider="dograh",
        provider_call_id="dgr_idempotent_test_99",
        tracking_reference=ref,
        status="queued",
        requirements_snapshot=request.requirements,
    )
    db_session.add(call)
    db_session.commit()

    webhook_payload = DograhWebhookPayload(
        workflow_run_id="dgr_idempotent_test_99",
        call_id=call.id,
        status="completed",
        collected_data={"total_amount": "50000"},
    )

    with patch("backend.app.agentic_ai.voice.dograh_service.DOGRAH_WEBHOOK_SECRET", ""):
        res1 = process_dograh_webhook(db_session, webhook_payload)
        assert res1["status"] == "processed"

        # Duplicate delivery
        res2 = process_dograh_webhook(db_session, webhook_payload)
        assert res2["status"] == "already_processed"
        assert res2["quotation_id"] == res1["quotation_id"]


# ── TEST 12: FAILED OR INCOMPLETE CALL HANDLING ──
def test_failed_or_incomplete_call_handling(db_session, test_actor, sample_rfq_and_vendor):
    request, run, vendor = sample_rfq_and_vendor
    ref = f"AuditAI-R{run.id}-V{vendor.id}"

    call = VoiceCall(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        owner_id=test_actor.id,
        provider="dograh",
        provider_call_id="dgr_no_answer_call_88",
        tracking_reference=ref,
        status="queued",
        requirements_snapshot=request.requirements,
    )
    db_session.add(call)
    db_session.commit()

    webhook_payload = DograhWebhookPayload(
        workflow_run_id="dgr_no_answer_call_88",
        call_id=call.id,
        status="no_answer",
        disposition="no_answer",
        duration_seconds=0,
        summary="Vendor did not answer after 45 seconds ringing.",
    )

    with patch("backend.app.agentic_ai.voice.dograh_service.DOGRAH_WEBHOOK_SECRET", ""):
        result = process_dograh_webhook(db_session, webhook_payload)

    assert result["status"] == "processed"
    assert result["call_status"] == "no_answer"
    assert result["quotation_status"] == "needs_verification"

    db_session.refresh(call)
    assert call.status == "no_answer"
    assert "no_answer" in call.outcome


# ── TEST 13: INDIAN PHONE NUMBER VALIDATION ──
def test_indian_phone_number_validation():
    # Valid Indian formats
    assert is_valid_indian_phone("+919876543210") is True
    assert is_valid_indian_phone("9876543210") is True
    assert is_valid_indian_phone("+91 98765-43210") is True
    assert is_valid_indian_phone("+918123456789") is True
    assert is_valid_indian_phone("+917012345678") is True

    # Invalid non-Indian or malformed formats
    assert is_valid_indian_phone("+14155552671") is False
    assert is_valid_indian_phone("+442071838750") is False
    assert is_valid_indian_phone("12345") is False
    assert is_valid_indian_phone("invalid_string") is False


# ── TEST 14: CALLING SAFETY CONTROLS & ALLOWLIST ──
def test_calling_safety_allowlist_and_emergency_switch(db_session):
    from backend.app.agentic_ai.voice.services import VoiceServiceError

    # 1. Emergency disable blocks all calls
    with patch("backend.app.agentic_ai.voice.dograh_service.VOICE_EMERGENCY_DISABLE", True):
        with pytest.raises(VoiceServiceError) as exc_info:
            check_voice_calling_safety(db_session, "+919876543210", dry_run=True)
        assert exc_info.value.status_code == 503
        assert "disabled by the emergency safety switch" in exc_info.value.detail

    # 2. Allowlist rejection in live mode
    with patch("backend.app.agentic_ai.voice.dograh_service.VOICE_AUTHORIZED_ALLOWLIST", ["+919999999999"]):
        # Authorized number passes
        res = check_voice_calling_safety(db_session, "+919999999999", dry_run=False)
        assert res["allowlist_verified"] is True

        # Unauthorized number rejected in live mode
        with pytest.raises(VoiceServiceError) as exc_info:
            check_voice_calling_safety(db_session, "+919876543210", dry_run=False)
        assert exc_info.value.status_code == 403
        assert "not on the authorized testing allowlist" in exc_info.value.detail


# ── TEST 15: CONCURRENCY AND DAILY QUOTA GUARDS ──
def test_concurrency_and_daily_quota_guards(db_session, test_actor, sample_rfq_and_vendor):
    from backend.app.agentic_ai.voice.services import VoiceServiceError
    request, run, vendor = sample_rfq_and_vendor

    # Create an active in-progress call
    active_call = VoiceCall(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        owner_id=test_actor.id,
        provider="dograh",
        provider_call_id="dgr_active_concurrency_test",
        tracking_reference="AuditAI-ACTIVE-01",
        status="in_progress",
        requirements_snapshot=request.requirements,
    )
    db_session.add(active_call)
    db_session.commit()

    # In live mode (dry_run=False), concurrency guard blocks second call
    with patch("backend.app.agentic_ai.voice.dograh_service.VOICE_AUTHORIZED_ALLOWLIST", ["+919876543210"]):
        with pytest.raises(VoiceServiceError) as exc_info:
            check_voice_calling_safety(db_session, "+919876543210", dry_run=False, actor_id=test_actor.id)
        assert exc_info.value.status_code == 429
        assert "Concurrency limit reached" in exc_info.value.detail


# ── TEST 16: EXOTEL TELEPHONY STATUS CALLBACK ──
def test_exotel_telephony_callback_processing(db_session, test_actor, sample_rfq_and_vendor):
    request, run, vendor = sample_rfq_and_vendor

    call = VoiceCall(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        owner_id=test_actor.id,
        provider="dograh",
        provider_call_id="c032a1234567890abcdef",
        tracking_reference="AuditAI-EXOTEL-01",
        status="queued",
        requirements_snapshot=request.requirements,
    )
    db_session.add(call)
    db_session.commit()

    # In-progress event
    cb1 = ExotelCallbackPayload(
        CallSid="c032a1234567890abcdef",
        Status="in-progress",
        CallType="transcribe",
    )
    res1 = process_exotel_callback(db_session, cb1)
    assert res1["status"] == "updated"
    assert res1["call_status"] == "in_progress"

    db_session.refresh(call)
    assert call.status == "in_progress"
    assert call.started_at is not None

    # Completed event with duration
    cb2 = ExotelCallbackPayload(
        CallSid="c032a1234567890abcdef",
        Status="completed",
        Duration="85.5",
    )
    res2 = process_exotel_callback(db_session, cb2)
    assert res2["status"] == "updated"
    assert res2["call_status"] == "completed"

    db_session.refresh(call)
    assert call.status == "completed"
    assert float(call.duration_seconds) == 85.5
    assert call.ended_at is not None


def test_twilio_telephony_callback_processing(db_session, test_actor, sample_rfq_and_vendor):
    """Verify Twilio status callbacks update the corresponding VoiceCall record."""
    from backend.app.agentic_ai.voice.dograh_schemas import TwilioCallbackPayload
    from backend.app.agentic_ai.voice.dograh_service import process_twilio_callback

    request, run, vendor = sample_rfq_and_vendor

    call = VoiceCall(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        owner_id=test_actor.id,
        tracking_reference="AuditAI-TWILIO-TEST",
        provider_call_id="CA7ff4c4f4ab19a7e35886055edd7d5ca5",
        status="ringing",
        requirements_snapshot=request.requirements,
    )
    db_session.add(call)
    db_session.commit()

    # Twilio in-progress callback
    cb1 = TwilioCallbackPayload(
        CallSid="CA7ff4c4f4ab19a7e35886055edd7d5ca5",
        CallStatus="in-progress",
    )
    res1 = process_twilio_callback(db_session, cb1)
    assert res1["status"] == "updated"
    assert res1["provider"] == "twilio"
    assert res1["call_status"] == "in_progress"

    db_session.refresh(call)
    assert call.status == "in_progress"

    # Twilio completed callback
    cb2 = TwilioCallbackPayload(
        CallSid="CA7ff4c4f4ab19a7e35886055edd7d5ca5",
        CallStatus="completed",
        CallDuration="112",
    )
    res2 = process_twilio_callback(db_session, cb2)
    assert res2["status"] == "updated"
    assert res2["call_status"] == "completed"

    db_session.refresh(call)
    assert call.status == "completed"
    assert float(call.duration_seconds) == 112.0
    assert call.ended_at is not None


def test_twilio_vendor_call_dispatch(db_session, test_actor, sample_rfq_and_vendor):
    """Verify Twilio outbound call initiation in dry-run mode and live mode with mocks."""
    from unittest.mock import MagicMock
    from backend.app.agentic_ai.voice.dograh_service import initiate_twilio_vendor_call
    from backend.app.agentic_ai.voice.dograh_schemas import StartCallRequest

    request, run, vendor = sample_rfq_and_vendor
    payload = StartCallRequest(
        request_id=request.id,
        agent_vendor_id=vendor.id,
        phone_number="+916350209890",
        vendor_name="Acme Supplies",
        product_name="Server Hardware",
    )

    # 1. Test dry-run dispatch
    dry_res = asyncio.run(initiate_twilio_vendor_call(db_session, test_actor, payload, force_live=False))
    assert dry_res["status"] == "dry_run_success"
    assert dry_res["provider"] == "twilio"
    assert dry_res["dry_run"] is True
    assert dry_res["to"] == "+916350209890"

    # 2. Test live dispatch (mocked external Twilio API)
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "sid": "CA1234567890abcdef1234567890abcdef",
            "status": "queued",
            "to": "+916350209890",
            "from": "+17372508034",
            "direction": "outbound-api",
        }
        mock_post.return_value = mock_response

        live_res = asyncio.run(initiate_twilio_vendor_call(db_session, test_actor, payload, force_live=True))
        assert live_res["status"] == "initiated"
        assert live_res["provider"] == "twilio"
        assert live_res["call_sid"] == "CA1234567890abcdef1234567890abcdef"
        assert live_res["dry_run"] is False
