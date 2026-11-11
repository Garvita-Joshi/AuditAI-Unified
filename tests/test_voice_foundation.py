"""Voice foundation checks on disposable SQLite and opt-in PostgreSQL schemas."""
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from backend.app.api.sourcing import SourcingRequest
from backend.app.api.voice_calls import router
from backend.app.auth.security import get_current_user
from backend.app.db import get_db
from backend.app.models.auth import AuthUser
from backend.app.agentic_ai.records import AgentActivity, AgentRun, AgentVendor
from backend.app.agentic_ai.voice.migration import upgrade
from backend.app.agentic_ai.voice.models import (
    VOICE_TABLES, VoiceCall, VoiceCallback, VoiceOperation, VoiceQuotation,
    VoiceQuotationAudit, VoiceTranscript,
)
from backend.app.agentic_ai.voice.schemas import QuotationFieldInput, REQUIRED_FIELDS
from backend.app.agentic_ai.voice import services
from backend.app.agentic_ai.voice.schemas import CallDraftCreate


@pytest.fixture(params=["sqlite", "postgresql"])
def workspace(request, tmp_path, monkeypatch):
    root_engine = None
    schema = None
    if request.param == "postgresql":
        url = os.getenv("VOICE_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Set VOICE_TEST_POSTGRES_URL to test an isolated PostgreSQL schema.")
        root_engine = create_engine(url)
        schema = "test_voice_" + uuid4().hex
        with root_engine.begin() as conn:
            conn.execute(CreateSchema(schema))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'voice.db'}", connect_args={"check_same_thread": False})
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    try:
        for model in (AuthUser, SourcingRequest, AgentRun, AgentVendor, AgentActivity):
            model.__table__.create(engine)
        upgrade(engine)
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        users = [AuthUser(email=f"voice-{i}@example.test", employee_id=f"VOICE-{i}",
                         display_name=f"Test account {i}", roles=["employee"], role="employee",
                         password_hash="unused-test-hash", active=True) for i in range(2)]
        db.add_all(users)
        db.flush()
        requests = []
        runs = []
        vendors = []
        for i, user in enumerate(users):
            rfq = SourcingRequest(owner_id=user.id, status="ready_for_research", requirements={
                "product": "USB headsets", "quantity": 2, "budget": "10000.00", "currency": "INR",
                "delivery_deadline": "2030-12-01", "delivery_location": "Jaipur, India", "line_items": [],
            })
            db.add(rfq)
            db.flush()
            run = AgentRun(request_id=rfq.id, owner_id=user.id, status="outreach_in_progress", summary={})
            db.add(run)
            db.flush()
            vendor = AgentVendor(run_id=run.id, vendor_id=f"V-{i}", offer_id=f"O-{i}",
                vendor_name=f"Test supplier {i}", vendor_email=f"vendor-{i}@example.test", synthetic=1,
                rank=1, score=90, reasons=["Test product match"], status="rfq_sent",
                offer={"phone": "+919000000000", "contact_name": "Test contact", "synthetic": True},
                rfq_subject="Test RFQ", rfq_body="Temporary fixture only.")
            db.add(vendor)
            db.flush()
            requests.append(rfq)
            runs.append(run)
            vendors.append(vendor)
        db.commit()
        actor = {"user": users[0]}
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: actor["user"]
        # An accidental external effect is a test failure, not a simulated send.
        def forbidden(*_args, **_kwargs):
            pytest.fail("The voice foundation attempted an external call or email.")
        import httpx
        import smtplib
        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
        monkeypatch.setattr(smtplib, "SMTP", forbidden)
        monkeypatch.setattr(smtplib, "SMTP_SSL", forbidden)
        with TestClient(app) as client:
            yield {"db": db, "client": client, "engine": engine, "actor": actor,
                   "users": users, "requests": requests, "runs": runs, "vendors": vendors}
        db.close()
    finally:
        engine.dispose()
        if root_engine is not None:
            with root_engine.begin() as conn:
                conn.execute(DropSchema(schema, cascade=True))
            root_engine.dispose()


def prepare(workspace, **changes):
    payload = {"request_id": workspace["requests"][0].id,
               "agent_vendor_id": workspace["vendors"][0].id,
               "idempotency_key": "test-call-0001", **changes}
    response = workspace["client"].post("/api/v1/voice/calls/drafts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_quote(workspace, call, fields=None, key="test-quote-0001"):
    response = workspace["client"].post("/api/v1/voice/quotations", json={
        "call_id": call["id"], "idempotency_key": key, "fields": fields or [],
    })
    assert response.status_code == 201, response.text
    return response.json()


def supplied(name, value, status="NEEDS_VERIFICATION"):
    result = {"name": name, "value": value, "status": status,
              "original_response": f"Vendor said {value}."}
    if status == "CONFIRMED":
        result["confirmation_note"] = "Vendor confirmed the read-back."
    return result


def test_prepared_call_reuses_existing_rfq_vendor_and_never_changes_email_status(workspace, monkeypatch):
    monkeypatch.setenv("VOICE_CALLS_ENABLED", "true")
    call = prepare(workspace)
    assert call["status"] == "prepared" and call["provider_call_id"] is None
    assert call["provider"] == "dograh"
    assert call["live_call_started"] is False
    assert call["requirements"]["currency"] == "INR"
    assert call["tracking_reference"] == f"AuditAI-R{workspace['runs'][0].id}-V{workspace['vendors'][0].id}"
    assert workspace["db"].get(AgentVendor, workspace["vendors"][0].id).status == "rfq_sent"
    assert workspace["client"].get("/api/v1/voice/config").json()["live_calling_available"] is False
    timeline = workspace["client"].get(f"/api/v1/voice/calls/{call['id']}/timeline").json()
    assert [entry["event"] for entry in timeline] == ["voice_call_prepared"]
    assert timeline[0]["details"]["provider"] == "dograh"
    assert "+919000000000" not in str(timeline)


def test_duplicate_call_requests_and_repeated_page_actions_do_not_create_attempts(workspace):
    first = prepare(workspace)
    assert prepare(workspace)["id"] == first["id"]
    assert prepare(workspace, idempotency_key="different-click-key")["id"] == first["id"]
    assert workspace["db"].query(VoiceCall).count() == 1
    assert workspace["db"].query(AgentActivity).count() == 1
    assert len(workspace["client"].get("/api/v1/voice/calls").json()) == 1


def test_changed_brief_does_not_silently_reuse_an_old_call_preview(workspace):
    original = prepare(workspace)
    rfq = workspace["requests"][0]
    rfq.requirements = {**rfq.requirements, "quantity": 5}
    workspace["db"].commit()
    client = workspace["client"]
    for key in ("test-call-0001", "new-call-click-key"):
        response = client.post("/api/v1/voice/calls/drafts", json={
            "request_id": rfq.id, "agent_vendor_id": workspace["vendors"][0].id, "idempotency_key": key,
        })
        assert response.status_code == 409
    assert workspace["db"].query(VoiceCall).count() == 1
    assert client.get(f"/api/v1/voice/calls/{original['id']}").json()["requirements"]["quantity"] == 2


def test_cancel_old_preview_allows_updated_brief_and_preserves_history(workspace):
    call = prepare(workspace)
    client = workspace["client"]
    path = f"/api/v1/voice/calls/{call['id']}/cancel"
    payload = {"idempotency_key": "cancel-preview-001", "reason": "Purchase quantity changed."}
    workspace["actor"]["user"] = workspace["users"][1]
    assert client.post(path, json=payload).status_code == 404
    workspace["actor"]["user"] = workspace["users"][0]
    assert client.post(path, json=payload).json()["status"] == "cancelled"
    assert client.post(path, json=payload).json()["status"] == "cancelled"
    request = workspace["requests"][0]
    request.requirements = {**request.requirements, "quantity": 5}
    workspace["db"].commit()
    updated = prepare(workspace, idempotency_key="updated-preview-001")
    assert updated["id"] != call["id"] and updated["requirements"]["quantity"] == 5
    assert workspace["db"].query(VoiceCall).count() == 2
    events = client.get(f"/api/v1/voice/calls/{call['id']}/timeline").json()
    assert len([entry for entry in events if entry["event"] == "voice_call_draft_cancelled"]) == 1


def test_cross_request_vendor_and_another_account_are_rejected(workspace):
    client = workspace["client"]
    assert client.post("/api/v1/voice/calls/drafts", json={
        "request_id": workspace["requests"][0].id,
        "agent_vendor_id": workspace["vendors"][1].id,
        "idempotency_key": "wrong-vendor-0001",
    }).status_code == 404
    call = prepare(workspace)
    quote = create_quote(workspace, call)
    workspace["actor"]["user"] = workspace["users"][1]
    for suffix in ("", "/timeline", "/transcript", "/callbacks"):
        assert client.get(f"/api/v1/voice/calls/{call['id']}{suffix}").status_code == 404
    for suffix in ("", "/audit"):
        assert client.get(f"/api/v1/voice/quotations/{quote['id']}{suffix}").status_code == 404
    assert client.get("/api/v1/voice/calls").json() == []
    assert client.get("/api/v1/voice/quotations").json() == []
    assert client.patch(f"/api/v1/voice/quotations/{quote['id']}/fields", json={
        "field": supplied("total_price", "50.00"), "version": 1, "reason": "Attempted other account edit",
    }).status_code == 404


def test_contact_lookup_and_tracking_reference_are_owner_scoped(workspace):
    client = workspace["client"]
    request = workspace["requests"][0]
    vendor = workspace["vendors"][0]
    details = client.get(f"/api/v1/voice/rfqs/{request.id}/vendors/{vendor.id}").json()
    assert details["phone_number"] == "+919000000000"
    assert details["synthetic"] is True
    assert client.get("/api/v1/voice/rfqs/by-reference", params={"reference": details["tracking_reference"]}).json()["id"] == request.id
    assert len(client.get(f"/api/v1/voice/rfqs/{request.id}/required-fields").json()["fields"]) == len(REQUIRED_FIELDS)
    assert len(client.get(f"/api/v1/voice/rfqs/{request.id}/vendors").json()) == 1
    workspace["actor"]["user"] = workspace["users"][1]
    assert client.get("/api/v1/voice/rfqs/by-reference", params={"reference": details["tracking_reference"]}).status_code == 404
    assert client.get(f"/api/v1/voice/rfqs/{request.id}/vendors").status_code == 404


def test_missing_quote_information_is_null_and_not_invented(workspace):
    quote = create_quote(workspace, prepare(workspace), [supplied("unit_price", "950.2500")])
    fields = {field["name"]: field for field in quote["fields"]}
    assert quote["status"] == "needs_verification"
    assert fields["unit_price"]["value"] == "950.2500"
    assert fields["unit_price"]["original_response"] == "Vendor said 950.2500."
    for name in ("total_price", "shipping", "taxes", "warranty", "payment_terms", "currency"):
        assert fields[name]["value"] is None
        assert fields[name]["status"] == "NOT_PROVIDED"
        assert name in quote["missing_fields"]
    assert quote["requires_human_purchase_approval"] is True


def test_quote_retry_is_idempotent_and_reused_key_cannot_change_data(workspace):
    call = prepare(workspace)
    fields = [supplied("total_price", "2000.00")]
    first = create_quote(workspace, call, fields)
    assert create_quote(workspace, call, fields)["id"] == first["id"]
    client = workspace["client"]
    assert client.post("/api/v1/voice/quotations", json={
        "call_id": call["id"], "idempotency_key": "test-quote-0001",
        "fields": [supplied("total_price", "3000.00")],
    }).status_code == 409
    assert client.post("/api/v1/voice/quotations", json={
        "call_id": call["id"], "idempotency_key": "another-quote-key", "fields": fields,
    }).status_code == 409
    assert workspace["db"].query(VoiceQuotation).count() == 1
    assert workspace["db"].query(VoiceQuotationAudit).count() == 1


def test_manual_correction_preserves_evidence_reason_actor_and_version(workspace):
    client = workspace["client"]
    quote = create_quote(workspace, prepare(workspace), [supplied("total_price", "2000.00")])
    path = f"/api/v1/voice/quotations/{quote['id']}"
    correction = {"field": supplied("total_price", "1900.00", "CONFIRMED"), "version": 1,
                  "reason": "Verified corrected amount with the vendor."}
    response = client.patch(path + "/fields", json=correction)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert client.patch(path + "/fields", json=correction).status_code == 409
    audit = client.get(path + "/audit").json()
    assert len(audit) == 2
    entry = next(entry for entry in audit if entry["old_value"] is not None)
    assert entry["old_value"]["value"] == "2000.00"
    assert entry["new_value"]["value"] == "1900.00"
    assert entry["source"] == "manual" and entry["actor_id"] == workspace["users"][0].id
    assert entry["reason"] == correction["reason"]
    assert entry["created_at"].endswith("+00:00")
    assert client.patch(path + "/fields", json={**correction, "version": 2, "reason": " "}).status_code == 422


def test_unknown_answers_preserve_original_words_and_identity_is_bound_to_call(workspace):
    call = prepare(workspace)
    quote = create_quote(workspace, call, [{"name": "shipping", "status": "UNKNOWN",
                                          "original_response": "I do not know the delivery charge."}])
    shipping = next(field for field in quote["fields"] if field["name"] == "shipping")
    assert shipping["value"] is None and shipping["status"] == "UNKNOWN"
    assert shipping["original_response"] == "I do not know the delivery charge."
    for field in (supplied("vendor_name", "Another supplier"), supplied("rfq_tracking_reference", "Wrong-RFQ")):
        assert workspace["client"].patch(f"/api/v1/voice/quotations/{quote['id']}/fields", json={
            "field": field, "version": 1, "reason": "Attempt to change quote identity",
        }).status_code == 422
    assert workspace["db"].get(VoiceQuotation, quote["id"]).version == 1


def test_transcript_retry_deduplication_and_conflict_roll_back_whole_batch(workspace):
    call = prepare(workspace)
    client = workspace["client"]
    path = f"/api/v1/voice/calls/{call['id']}/transcript"
    payload = {"idempotency_key": "transcript-batch-001", "messages": [
        {"message_key": "utterance-1", "speaker": "vendor", "message": "Price is 950 rupees.", "offset_seconds": "1.250"},
    ]}
    assert client.post(path, json=payload).json() == {"inserted": 1}
    assert client.post(path, json=payload).status_code == 200
    assert client.post(path, json={**payload, "idempotency_key": "transcript-batch-002"}).json() == {"inserted": 0}
    conflict = {"idempotency_key": "transcript-batch-003", "messages": [
        {"message_key": "new-message", "speaker": "assistant", "message": "Please confirm."},
        {**payload["messages"][0], "message": "Changed original utterance"},
    ]}
    assert client.post(path, json=conflict).status_code == 409
    assert len(client.get(path).json()) == 1
    assert workspace["db"].query(VoiceTranscript).count() == 1


def test_callback_timezone_future_time_and_retries_without_automatic_dial(workspace):
    client = workspace["client"]
    call = prepare(workspace)
    path = f"/api/v1/voice/calls/{call['id']}/callbacks"
    future = datetime.now(timezone.utc) + timedelta(days=2)
    payload = {"idempotency_key": "callback-request-001", "callback_at": future.isoformat(),
               "reason": "Vendor requested a callback."}
    first = client.post(path, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["automatic_dial"] is False
    assert client.post(path, json=payload).json()["id"] == first.json()["id"]
    assert workspace["db"].query(VoiceCallback).count() == 1
    assert client.post(path, json={**payload, "idempotency_key": "callback-request-002",
        "callback_at": "2020-01-01T10:00:00+05:30"}).status_code == 422
    assert client.post(path, json={**payload, "callback_at": "2030-01-01T10:00:00"}).status_code == 422
    assert workspace["db"].get(VoiceCall, call["id"]).status == "prepared"


def test_additive_migration_is_repeatable_and_records_persist_across_sessions(workspace):
    call = prepare(workspace)
    quote = create_quote(workspace, call)
    engine = workspace["engine"]
    upgrade(engine)
    upgrade(engine)
    assert {table.name for table in VOICE_TABLES} <= set(inspect(engine).get_table_names())
    with sessionmaker(bind=engine)() as fresh:
        assert fresh.get(VoiceCall, call["id"]).request_id == workspace["requests"][0].id
        assert fresh.get(VoiceQuotation, quote["id"]).call_id == call["id"]
        assert fresh.query(AuthUser).count() == 2
        assert fresh.query(SourcingRequest).count() == 2


def test_service_failure_can_roll_back_records_idempotency_and_audit_together(workspace):
    db = workspace["db"]
    payload = CallDraftCreate(request_id=workspace["requests"][0].id,
        agent_vendor_id=workspace["vendors"][0].id, idempotency_key="rollback-call-001")
    services.prepare_call(db, workspace["users"][0], payload)
    db.rollback()  # Simulate failure later in the enclosing API operation.
    with sessionmaker(bind=workspace["engine"])() as fresh:
        assert fresh.query(VoiceCall).count() == 0
        assert fresh.query(VoiceOperation).count() == 0
        assert fresh.query(AgentActivity).count() == 0


def test_complete_quote_and_budget_flags_do_not_approve_purchase(workspace):
    call = prepare(workspace)
    values = {name: "Vendor confirmed this term" for name in REQUIRED_FIELDS}
    values.update(product_or_service="USB headsets", quantity="2", unit_price="950.00", total_price="2360.00",
                  currency="INR", shipping="100.00", taxes="360.00", expected_delivery_date="2030-11-25",
                  vendor_name=workspace["vendors"][0].vendor_name, rfq_tracking_reference=call["tracking_reference"])
    quote = create_quote(workspace, call, [supplied(name, value, "CONFIRMED") for name, value in values.items()])
    assert quote["status"] == "complete"
    assert quote["missing_fields"] == quote["unverified_fields"] == []
    assert quote["requires_human_purchase_approval"] is True
    assert workspace["requests"][0].status == "ready_for_research"
    response = workspace["client"].patch(f"/api/v1/voice/quotations/{quote['id']}/fields", json={
        "version": 1, "field": supplied("total_price", "10001.00", "CONFIRMED"),
        "reason": "Vendor confirmed a higher price.",
    })
    assert response.json()["status"] == "needs_verification"
    assert "exceeds" in response.json()["issues"][0]


@pytest.mark.parametrize("field", [
    supplied("unit_price", -1), supplied("shipping", "0.001"), supplied("quantity", "0"),
    supplied("taxes", "NaN"), supplied("total_price", "Infinity"), supplied("total_price", 2.50),
    supplied("quantity", True), supplied("currency", "RUPEES"), supplied("expected_delivery_date", "01/12/2030"),
    {"name": "shipping", "status": "UNKNOWN", "value": "0"},
    {"name": "total_price", "status": "CONFIRMED", "value": "100", "original_response": "100 rupees"},
    {"name": "total_price", "status": "NEEDS_VERIFICATION", "value": "100"},
    {**supplied("unit_price", "100"), "execute_sql": "DROP TABLE calls"},
])
def test_quote_schema_rejects_invalid_or_unsupported_values(field):
    with pytest.raises(ValidationError):
        QuotationFieldInput.model_validate(field)


def test_api_requires_authentication_and_has_no_live_dial_or_webhook_route():
    app = FastAPI()
    app.include_router(router)
    # Override the DB only: authentication itself must reject missing credentials.
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.get("/api/v1/voice/config").status_code == 401
        assert client.post("/api/v1/voice/calls/outbound", json={}).status_code in (404, 405)
        assert client.post("/api/v1/voice/dograh/webhook", json={}).status_code == 404


def test_dograh_settings_replace_legacy_provider_without_enabling_calls(workspace, monkeypatch):
    for key in ("DOGRAH_BASE_URL", "DOGRAH_API_KEY", "DOGRAH_TRIGGER_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VAPI_PRIVATE_API_KEY", "legacy-test-key")
    monkeypatch.setenv("VAPI_ASSISTANT_ID", "legacy-test-assistant")
    monkeypatch.setenv("VAPI_PHONE_NUMBER_ID", "legacy-test-number")
    config = workspace["client"].get("/api/v1/voice/config").json()
    assert config["provider"] == "dograh" and config["provider_settings_present"] is False
    monkeypatch.setenv("DOGRAH_BASE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("DOGRAH_API_KEY", "dgr_test_only")
    monkeypatch.setenv("DOGRAH_TRIGGER_PATH", "test-trigger")
    monkeypatch.setenv("VOICE_CALLS_ENABLED", "true")
    config = workspace["client"].get("/api/v1/voice/config").json()
    assert config["provider_settings_present"] is True
    assert config["live_calling_available"] is False
    assert "dgr_test_only" not in str(config)


def test_legacy_call_history_is_preserved_and_not_relabeled_as_dograh(workspace):
    call = prepare(workspace)
    stored = workspace["db"].get(VoiceCall, call["id"])
    stored.provider = "vapi"
    workspace["db"].commit()
    response = workspace["client"].post("/api/v1/voice/calls/drafts", json={
        "request_id": workspace["requests"][0].id, "agent_vendor_id": workspace["vendors"][0].id,
        "idempotency_key": "new-dograh-preview-key",
    })
    assert response.status_code == 409
    assert workspace["client"].get(f"/api/v1/voice/calls/{call['id']}").json()["provider"] == "vapi"
