"""Phase 2 voice data APIs. There is deliberately no outbound dialing route."""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.auth.security import get_current_user
from backend.app.db import get_db
from backend.app.models.auth import AuthUser
from backend.app.agentic_ai.voice import DEFAULT_VOICE_PROVIDER, services
from backend.app.agentic_ai.voice.models import VoiceCall, VoiceQuotation
from backend.app.agentic_ai.voice.schemas import (
    REQUIRED_FIELDS, CallDraftCancel, CallDraftCreate, CallbackCreate, QuotationCreate,
    QuotationFieldUpdate, RecordId, TranscriptAppend,
)

router = APIRouter(prefix="/api/v1/voice", tags=["procurement voice foundation"])
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[AuthUser, Depends(get_current_user)]


def _read(effect):
    try:
        return effect()
    except services.VoiceServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def _write(db, effect):
    try:
        result = effect()
        db.commit()
        return result
    except services.VoiceServiceError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.detail) from exc
    except Exception:
        db.rollback()
        raise


@router.get("/config")
def configuration(db: Db, actor: Actor):
    return {"phase": 2, "provider": DEFAULT_VOICE_PROVIDER, "storage_backend": db.get_bind().dialect.name,
            "live_calling_available": False,
            "provider_settings_present": all(bool(os.getenv(key)) for key in (
                "DOGRAH_BASE_URL", "DOGRAH_API_KEY", "DOGRAH_TRIGGER_PATH")),
            "message": "Backend foundation only. No live calls or automatic callbacks are enabled."}


@router.get("/rfqs/by-reference")
def rfq_by_reference(db: Db, actor: Actor, reference: str = Query(min_length=1, max_length=150)):
    return _read(lambda: services.rfq_by_tracking_reference(db, reference, actor))


@router.get("/rfqs/{request_id}")
def rfq(request_id: int, db: Db, actor: Actor):
    return _read(lambda: services.rfq_details(db, request_id, actor))


@router.get("/rfqs/{request_id}/required-fields")
def required_fields(request_id: int, db: Db, actor: Actor):
    _read(lambda: services.owned_rfq(db, request_id, actor))
    return {"request_id": request_id, "fields": list(REQUIRED_FIELDS)}


@router.get("/rfqs/{request_id}/vendors")
def vendors(request_id: int, db: Db, actor: Actor):
    return _read(lambda: services.list_vendors(db, request_id, actor))


@router.get("/rfqs/{request_id}/vendors/{vendor_record_id}")
def vendor(request_id: int, vendor_record_id: int, db: Db, actor: Actor):
    return _read(lambda: services.vendor_details(db, request_id, vendor_record_id, actor))


@router.post("/calls/drafts", status_code=201)
def prepare(payload: CallDraftCreate, db: Db, actor: Actor):
    """Save a call preview only: no provider request and no phone call."""
    def effect():
        call = services.prepare_call(db, actor, payload)
        return services.call_details(db, call.id, actor)
    return _write(db, effect)


@router.get("/calls")
def calls(db: Db, actor: Actor, request_id: int | None = Query(default=None, gt=0),
          limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    if request_id is not None:
        _read(lambda: services.owned_rfq(db, request_id, actor))
    query = db.query(VoiceCall).filter_by(owner_id=actor.id)
    if request_id is not None:
        query = query.filter_by(request_id=request_id)
    rows = query.order_by(VoiceCall.created_at.desc(), VoiceCall.id).offset(offset).limit(limit).all()
    return _read(lambda: [services.call_details(db, row.id, actor) for row in rows])


@router.get("/calls/{call_id}")
def call(call_id: RecordId, db: Db, actor: Actor):
    return _read(lambda: services.call_details(db, call_id, actor))


@router.get("/calls/{call_id}/timeline")
def timeline(call_id: RecordId, db: Db, actor: Actor):
    return _read(lambda: services.call_timeline(db, call_id, actor))


@router.post("/calls/{call_id}/cancel")
def cancel_draft(call_id: RecordId, payload: CallDraftCancel, db: Db, actor: Actor):
    def effect():
        row = services.cancel_call_draft(db, actor, call_id, payload)
        return services.call_details(db, row.id, actor)
    return _write(db, effect)


@router.get("/calls/{call_id}/transcript")
def transcript(call_id: RecordId, db: Db, actor: Actor):
    return _read(lambda: services.transcript_details(db, call_id, actor))


@router.post("/calls/{call_id}/transcript")
def append_transcript(call_id: RecordId, payload: TranscriptAppend, db: Db, actor: Actor):
    """Owner-entered evidence only; provider-authenticated ingestion is Phase 4."""
    return _write(db, lambda: services.append_transcript(db, actor, call_id, payload))


@router.get("/calls/{call_id}/callbacks")
def callbacks(call_id: RecordId, db: Db, actor: Actor):
    return _read(lambda: services.callback_details(db, call_id, actor))


@router.post("/calls/{call_id}/callbacks", status_code=201)
def schedule_callback(call_id: RecordId, payload: CallbackCreate, db: Db, actor: Actor):
    """Record the callback time. This does not schedule automatic dialing."""
    def effect():
        callback = services.schedule_callback(db, actor, call_id, payload)
        return next(row for row in services.callback_details(db, call_id, actor) if row["id"] == callback.id)
    return _write(db, effect)


@router.post("/quotations", status_code=201)
def create_quotation(payload: QuotationCreate, db: Db, actor: Actor):
    def effect():
        quote = services.create_quotation(db, actor, payload)
        return services.quotation_details(db, quote.id, actor)
    return _write(db, effect)


@router.get("/quotations")
def quotations(db: Db, actor: Actor, request_id: int | None = Query(default=None, gt=0),
               limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    if request_id is not None:
        _read(lambda: services.owned_rfq(db, request_id, actor))
    query = db.query(VoiceQuotation).join(VoiceCall, VoiceCall.id == VoiceQuotation.call_id).filter(VoiceCall.owner_id == actor.id)
    if request_id is not None:
        query = query.filter(VoiceQuotation.request_id == request_id)
    rows = query.order_by(VoiceQuotation.created_at.desc(), VoiceQuotation.id).offset(offset).limit(limit).all()
    return _read(lambda: [services.quotation_details(db, row.id, actor) for row in rows])


@router.get("/quotations/{quotation_id}")
def quotation(quotation_id: RecordId, db: Db, actor: Actor):
    return _read(lambda: services.quotation_details(db, quotation_id, actor))


@router.patch("/quotations/{quotation_id}/fields")
def update_field(quotation_id: RecordId, payload: QuotationFieldUpdate, db: Db, actor: Actor):
    def effect():
        services.update_quotation_field(db, actor, quotation_id, payload)
        return services.quotation_details(db, quotation_id, actor)
    return _write(db, effect)


@router.get("/quotations/{quotation_id}/audit")
def audit(quotation_id: RecordId, db: Db, actor: Actor):
    return _read(lambda: services.quotation_audit(db, quotation_id, actor))
