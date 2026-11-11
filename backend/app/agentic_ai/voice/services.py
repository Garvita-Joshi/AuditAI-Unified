"""Owner-scoped persistence services. Callers own commit/rollback boundaries.

These services never call a voice provider, send mail, approve a purchase, or
commit a quotation as a purchase order. Phase 3 tools will reuse this boundary.
"""
import hashlib
import json
import re
from datetime import timezone
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from backend.app.agentic_ai.records import AgentActivity, AgentRun, AgentVendor
from backend.app.sourcing.requirements import Requirements
from . import DEFAULT_VOICE_PROVIDER
from .models import (
    VoiceCall, VoiceCallback, VoiceOperation, VoiceQuotation, VoiceQuotationAudit,
    VoiceQuotationField, VoiceTranscript, utcnow,
)
from .schemas import (
    REQUIRED_FIELDS, CallDraftCancel, CallDraftCreate, CallbackCreate, QuotationCreate,
    QuotationFieldInput, QuotationFieldUpdate, TranscriptAppend,
)


class VoiceServiceError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _actor_id(actor):
    if not getattr(actor, "id", None) or not getattr(actor, "active", False):
        raise VoiceServiceError(403, "An active company account is required.")
    return actor.id


def owned_rfq(db, request_id, actor):
    # Existing model is reused, not copied into a second RFQ table. This lazy
    # import avoids a cycle while the legacy sourcing router registers models.
    from backend.app.api.sourcing import SourcingRequest
    row = db.query(SourcingRequest).filter_by(id=request_id, owner_id=_actor_id(actor)).first()
    if row is None:
        raise VoiceServiceError(404, "Sourcing request not found.")
    return row


def owned_vendor(db, request_id, vendor_record_id, actor):
    owned_rfq(db, request_id, actor)
    row = db.query(AgentVendor).join(AgentRun, AgentRun.id == AgentVendor.run_id).filter(
        AgentVendor.id == vendor_record_id, AgentRun.request_id == request_id,
        AgentRun.owner_id == actor.id,
    ).first()
    if row is None:
        raise VoiceServiceError(404, "Vendor was not found in this request's shortlist.")
    return row


def owned_call(db, call_id, actor, *, lock=False):
    query = db.query(VoiceCall).filter_by(id=call_id, owner_id=_actor_id(actor))
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise VoiceServiceError(404, "Call not found.")
    owned_vendor(db, row.request_id, row.agent_vendor_id, actor)
    return row


def owned_quotation(db, quotation_id, actor, *, lock=False):
    query = db.query(VoiceQuotation).join(VoiceCall, VoiceCall.id == VoiceQuotation.call_id).filter(
        VoiceQuotation.id == quotation_id, VoiceCall.owner_id == _actor_id(actor),
    )
    if lock:
        query = query.with_for_update(of=VoiceQuotation)
    row = query.first()
    if row is None:
        raise VoiceServiceError(404, "Quotation not found.")
    owned_call(db, row.call_id, actor)
    return row


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _idempotent(db, actor, operation, key, payload, effect):
    fingerprint = _fingerprint(payload)

    def existing_receipt():
        row = db.query(VoiceOperation).filter_by(owner_id=actor.id, operation=operation, key=key).first()
        if row is not None and row.fingerprint != fingerprint:
            raise VoiceServiceError(409, "This idempotency key was already used for different data.")
        return row

    existing = existing_receipt()
    if existing is not None:
        return existing.result
    if db.get_bind().dialect.name == "sqlite":
        connection = db.connection()
        # Python sqlite's legacy transaction mode does not BEGIN on SELECT.
        # Ensure SAVEPOINT release cannot commit before the caller commits.
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    try:
        # Claim the key before applying changes, in the same transaction. A
        # repeated request cannot leave a second quotation/audit/transcript.
        with db.begin_nested():
            receipt = VoiceOperation(owner_id=actor.id, operation=operation, key=key, fingerprint=fingerprint)
            db.add(receipt)
            db.flush()
            receipt.result = effect()
            db.flush()
            result = receipt.result
        return result
    except IntegrityError:
        existing = existing_receipt()
        if existing is not None:
            return existing.result
        raise VoiceServiceError(409, "A concurrent update already created this record. Reload before retrying.")


def _activity(db, call, actor, event, **details):
    vendor = db.get(AgentVendor, call.agent_vendor_id)
    db.add(AgentActivity(
        run_id=vendor.run_id, request_id=call.request_id,
        actor=f"user:{actor.id}", event=event,
        details={"call_id": call.id, "agent_vendor_id": vendor.id, **details},
    ))


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:  # SQLite drops UTC tzinfo when reading DateTime.
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def rfq_details(db, request_id, actor):
    row = owned_rfq(db, request_id, actor)
    return {"id": row.id, "status": row.status, "version": row.version,
            "requirements": Requirements.model_validate(row.requirements).model_dump(mode="json")}


def rfq_by_tracking_reference(db, reference, actor):
    match = re.fullmatch(r"AuditAI-R([1-9][0-9]{0,9})-V([1-9][0-9]{0,9})", reference)
    if not match:
        raise VoiceServiceError(404, "RFQ tracking reference not found.")
    run_id, vendor_id = map(int, match.groups())
    if run_id > 2147483647 or vendor_id > 2147483647:
        raise VoiceServiceError(404, "RFQ tracking reference not found.")
    run = db.query(AgentRun).filter_by(id=run_id, owner_id=_actor_id(actor)).first()
    if run is None:
        raise VoiceServiceError(404, "RFQ tracking reference not found.")
    vendor = owned_vendor(db, run.request_id, vendor_id, actor)
    if vendor.run_id != run_id:
        raise VoiceServiceError(404, "RFQ tracking reference not found.")
    return {**rfq_details(db, run.request_id, actor), "tracking_reference": reference, "agent_vendor_id": vendor.id}


def vendor_details(db, request_id, vendor_record_id, actor):
    row = owned_vendor(db, request_id, vendor_record_id, actor)
    offer = row.offer or {}
    return {"agent_vendor_id": row.id, "vendor_id": row.vendor_id,
            "company_name": row.vendor_name, "contact_person": offer.get("contact_name"),
            "email": row.vendor_email, "phone_number": offer.get("phone"),
            "address": offer.get("address"), "synthetic": bool(row.synthetic or offer.get("synthetic")),
            "tracking_reference": f"AuditAI-R{row.run_id}-V{row.id}",
            "live_calling_available": False}


def list_vendors(db, request_id, actor):
    owned_rfq(db, request_id, actor)
    rows = db.query(AgentVendor).join(AgentRun, AgentRun.id == AgentVendor.run_id).filter(
        AgentRun.request_id == request_id, AgentRun.owner_id == actor.id,
    ).order_by(AgentVendor.run_id.desc(), AgentVendor.rank, AgentVendor.id).all()
    return [vendor_details(db, request_id, row.id, actor) for row in rows]


def prepare_call(db, actor, payload: CallDraftCreate):
    payload = CallDraftCreate.model_validate(payload)
    request = owned_rfq(db, payload.request_id, actor)
    vendor = owned_vendor(db, request.id, payload.agent_vendor_id, actor)
    snapshot = Requirements.model_validate(request.requirements).model_dump(mode="json")
    if not snapshot.get("product") and not any(line.get("description") for line in snapshot["line_items"]):
        raise VoiceServiceError(422, "Describe the purchase before preparing a call.")

    def effect():
        existing = db.query(VoiceCall).filter(
            VoiceCall.agent_vendor_id == vendor.id,
            VoiceCall.status.in_(("prepared", "queued", "ringing", "in_progress")),
        ).first()
        if existing is not None:
            if existing.provider != DEFAULT_VOICE_PROVIDER:
                raise VoiceServiceError(409, "The open preview uses a different voice provider. Cancel it before preparing a Dograh call.")
            if existing.requirements_snapshot != snapshot:
                raise VoiceServiceError(409, "The brief changed after the open call was prepared.")
            return {"id": existing.id}
        call = VoiceCall(request_id=request.id, agent_vendor_id=vendor.id, owner_id=actor.id,
                         provider=DEFAULT_VOICE_PROVIDER,
                         requirements_snapshot=snapshot,
                         tracking_reference=f"AuditAI-R{vendor.run_id}-V{vendor.id}")
        db.add(call)
        db.flush()
        _activity(db, call, actor, "voice_call_prepared", provider=call.provider, live_call_started=False)
        return {"id": call.id}

    result = _idempotent(db, actor, "prepare_call", payload.idempotency_key,
                         {**payload.model_dump(mode="json", exclude={"idempotency_key"}),
                          "requirements_snapshot": snapshot, "provider": DEFAULT_VOICE_PROVIDER}, effect)
    return owned_call(db, result["id"], actor)


def call_details(db, call_id, actor):
    row = owned_call(db, call_id, actor)
    vendor = db.get(AgentVendor, row.agent_vendor_id)
    quote = db.query(VoiceQuotation).filter_by(call_id=row.id).first()
    return {"id": row.id, "request_id": row.request_id, "agent_vendor_id": row.agent_vendor_id,
            "vendor_name": vendor.vendor_name, "tracking_reference": row.tracking_reference,
            "provider": row.provider, "provider_call_id": row.provider_call_id,
            "status": row.status, "outcome": row.outcome, "summary": row.summary,
            "requirements": row.requirements_snapshot, "quotation_id": quote.id if quote else None,
            "created_at": _iso(row.created_at), "started_at": _iso(row.started_at),
            "ended_at": _iso(row.ended_at),
            "duration_seconds": str(row.duration_seconds) if row.duration_seconds is not None else None,
            "live_call_started": row.provider_call_id is not None}


def cancel_call_draft(db, actor, call_id, payload: CallDraftCancel):
    payload = CallDraftCancel.model_validate(payload)
    call = owned_call(db, call_id, actor, lock=True)

    def effect():
        if call.status == "cancelled":
            return {"id": call.id}
        if call.status != "prepared" or call.provider_call_id is not None:
            raise VoiceServiceError(409, "Only an unstarted call draft can be cancelled here.")
        changed = db.execute(update(VoiceCall).where(
            VoiceCall.id == call.id, VoiceCall.status == "prepared", VoiceCall.provider_call_id.is_(None),
        ).values(status="cancelled", outcome="cancelled_before_call", ended_at=utcnow())
            .execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise VoiceServiceError(409, "The call state changed. Reload before cancelling.")
        db.refresh(call)
        _activity(db, call, actor, "voice_call_draft_cancelled", reason=payload.reason)
        return {"id": call.id}

    result = _idempotent(db, actor, "cancel_call_draft", payload.idempotency_key,
                         {"call_id": call.id, "reason": payload.reason}, effect)
    return owned_call(db, result["id"], actor)


def _field_snapshot(field):
    return {"name": field.name, "value": field.value, "original_response": field.original_response,
            "status": field.status, "confirmation_note": field.confirmation_note}


def _field_rows(db, quote_id):
    rows = db.query(VoiceQuotationField).filter_by(quotation_id=quote_id).all()
    return sorted(rows, key=lambda row: REQUIRED_FIELDS.index(row.name))


def _assessment(db, quote):
    rows = _field_rows(db, quote.id)
    missing = [row.name for row in rows if row.status in ("NOT_PROVIDED", "UNKNOWN")]
    unverified = [row.name for row in rows if row.status == "NEEDS_VERIFICATION"]
    fields = {row.name: row for row in rows}
    call = db.get(VoiceCall, quote.call_id)
    currency = fields["currency"]
    total = fields["total_price"]
    issues = []
    expected_currency = call.requirements_snapshot.get("currency")
    if currency.value and expected_currency and currency.value != expected_currency:
        issues.append("Quoted currency differs from the request; no exchange rate has been assumed.")
    budget = call.requirements_snapshot.get("budget")
    if (budget and currency.status == "CONFIRMED" and currency.value == expected_currency
            and total.status == "CONFIRMED" and Decimal(total.value) > Decimal(budget)):
        issues.append("The vendor's quoted total exceeds the request budget.")
    status = "needs_verification" if issues or unverified else "incomplete" if missing else "complete"
    return {"status": status, "missing_fields": missing, "unverified_fields": unverified,
            "issues": issues, "requires_human_purchase_approval": True}


def _check_identity(call, vendor, field):
    if field.value is None:
        return
    if field.name.value == "rfq_tracking_reference" and field.value != call.tracking_reference:
        raise VoiceServiceError(422, "The tracking reference does not belong to this call.")
    if field.name.value == "vendor_name" and field.value.casefold() != vendor.vendor_name.casefold():
        raise VoiceServiceError(422, "The quotation vendor does not match this call.")


def create_quotation(db, actor, payload: QuotationCreate):
    payload = QuotationCreate.model_validate(payload)
    call = owned_call(db, payload.call_id, actor, lock=True)
    vendor = db.get(AgentVendor, call.agent_vendor_id)
    for field in payload.fields:
        _check_identity(call, vendor, field)

    def effect():
        if db.query(VoiceQuotation).filter_by(call_id=call.id).first() is not None:
            raise VoiceServiceError(409, "This call already has a quotation. Update its fields instead.")
        quote = VoiceQuotation(call_id=call.id, request_id=call.request_id, agent_vendor_id=call.agent_vendor_id)
        db.add(quote)
        db.flush()
        supplied = {field.name.value: field for field in payload.fields}
        for name in REQUIRED_FIELDS:
            field = supplied.get(name, QuotationFieldInput(name=name))
            row = VoiceQuotationField(quotation_id=quote.id, **field.model_dump(mode="json"))
            db.add(row)
            if name in supplied:
                db.add(VoiceQuotationAudit(quotation_id=quote.id, field_name=name,
                    old_value=None, new_value=field.model_dump(mode="json"), source="manual",
                    actor_id=actor.id, reason="Initial quotation information recorded by the request owner."))
        db.flush()
        quote.status = _assessment(db, quote)["status"]
        _activity(db, call, actor, "voice_quotation_created", quotation_id=quote.id, supplied_fields=len(supplied))
        return {"id": quote.id}

    result = _idempotent(db, actor, "create_quotation", payload.idempotency_key,
                         payload.model_dump(mode="json", exclude={"idempotency_key"}), effect)
    return owned_quotation(db, result["id"], actor)


def quotation_details(db, quotation_id, actor):
    row = owned_quotation(db, quotation_id, actor)
    return {"id": row.id, "call_id": row.call_id, "request_id": row.request_id,
            "agent_vendor_id": row.agent_vendor_id, "version": row.version,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
            "fields": [_field_snapshot(field) for field in _field_rows(db, row.id)],
            **_assessment(db, row)}


def update_quotation_field(db, actor, quotation_id, payload: QuotationFieldUpdate):
    payload = QuotationFieldUpdate.model_validate(payload)
    quote = owned_quotation(db, quotation_id, actor, lock=True)
    call = owned_call(db, quote.call_id, actor)
    vendor = db.get(AgentVendor, call.agent_vendor_id)
    _check_identity(call, vendor, payload.field)
    changed = db.execute(update(VoiceQuotation).where(
        VoiceQuotation.id == quotation_id, VoiceQuotation.version == payload.version,
    ).values(version=payload.version + 1, updated_at=utcnow()).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise VoiceServiceError(409, "Quotation changed. Reload the latest version before editing.")
    field = db.query(VoiceQuotationField).filter_by(quotation_id=quotation_id, name=payload.field.name.value).one()
    before = _field_snapshot(field)
    after = payload.field.model_dump(mode="json")
    for name, value in after.items():
        setattr(field, name, value)
    field.updated_at = utcnow()
    db.add(VoiceQuotationAudit(quotation_id=quote.id, field_name=field.name, old_value=before,
                              new_value=after, source="manual", actor_id=actor.id, reason=payload.reason))
    db.flush()
    db.refresh(quote)
    quote.status = _assessment(db, quote)["status"]
    _activity(db, call, actor, "voice_quotation_field_updated", quotation_id=quote.id,
              field_name=field.name, reason=payload.reason)
    return quote


def quotation_audit(db, quotation_id, actor):
    owned_quotation(db, quotation_id, actor)
    rows = db.query(VoiceQuotationAudit).filter_by(quotation_id=quotation_id).order_by(
        VoiceQuotationAudit.created_at, VoiceQuotationAudit.id,
    ).all()
    return [{"id": row.id, "quotation_id": row.quotation_id, "field_name": row.field_name,
             "old_value": row.old_value, "new_value": row.new_value, "source": row.source,
             "actor_id": row.actor_id, "reason": row.reason, "created_at": _iso(row.created_at)} for row in rows]


def append_transcript(db, actor, call_id, payload: TranscriptAppend):
    payload = TranscriptAppend.model_validate(payload)
    call = owned_call(db, call_id, actor, lock=True)

    def effect():
        count = 0
        for message in payload.messages:
            row = db.query(VoiceTranscript).filter_by(call_id=call.id, message_key=message.message_key).first()
            if row is not None:
                same = (row.speaker == message.speaker and row.message == message.message
                        and row.offset_seconds == message.offset_seconds and _iso(row.spoken_at) == _iso(message.spoken_at))
                if not same:
                    raise VoiceServiceError(409, "Transcript message key was reused with different content.")
                continue
            db.add(VoiceTranscript(call_id=call.id, **message.model_dump()))
            count += 1
        if count:
            _activity(db, call, actor, "voice_transcript_recorded", message_count=count, source="manual")
        return {"inserted": count}

    return _idempotent(db, actor, "append_transcript", payload.idempotency_key,
                       {"call_id": call.id, **payload.model_dump(mode="json", exclude={"idempotency_key"})}, effect)


def transcript_details(db, call_id, actor):
    owned_call(db, call_id, actor)
    rows = db.query(VoiceTranscript).filter_by(call_id=call_id).order_by(
        VoiceTranscript.offset_seconds.asc().nullslast(), VoiceTranscript.created_at, VoiceTranscript.id,
    ).all()
    return [{"id": row.id, "message_key": row.message_key, "speaker": row.speaker,
             "message": row.message, "offset_seconds": str(row.offset_seconds) if row.offset_seconds is not None else None,
             "spoken_at": _iso(row.spoken_at)} for row in rows]


def schedule_callback(db, actor, call_id, payload: CallbackCreate):
    payload = CallbackCreate.model_validate(payload)
    call = owned_call(db, call_id, actor, lock=True)

    def effect():
        if payload.callback_at <= utcnow():
            raise VoiceServiceError(422, "Callback time must be in the future.")
        row = db.query(VoiceCallback).filter_by(call_id=call.id, callback_at=payload.callback_at).first()
        if row is not None and (row.reason != payload.reason or row.status != "scheduled"):
            raise VoiceServiceError(409, "A different callback record already exists for this time.")
        if row is None:
            row = VoiceCallback(call_id=call.id, callback_at=payload.callback_at,
                                reason=payload.reason, created_by=actor.id)
            db.add(row)
            db.flush()
            _activity(db, call, actor, "voice_callback_scheduled", callback_id=row.id,
                      callback_at=_iso(row.callback_at), reason=payload.reason, automatic_dial=False)
        return {"id": row.id}

    result = _idempotent(db, actor, "schedule_callback", payload.idempotency_key,
                         {"call_id": call.id, **payload.model_dump(mode="json", exclude={"idempotency_key"})}, effect)
    return db.get(VoiceCallback, result["id"])


def callback_details(db, call_id, actor):
    owned_call(db, call_id, actor)
    rows = db.query(VoiceCallback).filter_by(call_id=call_id).order_by(VoiceCallback.callback_at).all()
    return [{"id": row.id, "call_id": row.call_id, "callback_at": _iso(row.callback_at),
             "status": row.status, "reason": row.reason, "automatic_dial": False} for row in rows]


def call_timeline(db, call_id, actor):
    call = owned_call(db, call_id, actor)
    # Existing activity table stores both email and voice events. Filter by
    # call_id so email/other vendors' messages do not appear in this timeline.
    rows = db.query(AgentActivity).filter(
        AgentActivity.request_id == call.request_id,
        AgentActivity.details["call_id"].as_string() == call.id,
    ).order_by(AgentActivity.created_at, AgentActivity.id).all()
    return [{"id": row.id, "request_id": row.request_id, "actor": row.actor,
             "event": row.event, "details": row.details, "created_at": _iso(row.created_at)} for row in rows]
