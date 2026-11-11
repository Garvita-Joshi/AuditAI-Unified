"""FastAPI routes for Dograh Voice AI integration.
Provides endpoints to trigger outbound vendor RFQ calls, receive post-call webhooks,
and query execution/quotation status.
"""
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.agentic_ai.voice.dograh_client import DograhClientError, dograh_client
from backend.app.agentic_ai.voice.dograh_schemas import (
    DograhTriggerResponse,
    DograhWebhookPayload,
    ExotelCallbackPayload,
    TwilioCallbackPayload,
    StartCallRequest,
)
from backend.app.agentic_ai.voice.dograh_service import (
    initiate_vendor_rfq_call,
    initiate_twilio_vendor_call,
    process_dograh_webhook,
    process_exotel_callback,
    process_twilio_callback,
    get_workflow_run_status,
)
from backend.app.agentic_ai.voice.services import VoiceServiceError
from backend.app.auth.security import get_current_user
from backend.app.config import (
    DOGRAH_API_KEY,
    DOGRAH_DRY_RUN,
    DOGRAH_TRIGGER_PATH,
    DOGRAH_WEBHOOK_SECRET,
    EXOTEL_ACCOUNT_SID,
    EXOTEL_API_KEY,
    EXOTEL_BASE_URL,
    EXOTEL_CALLER_ID,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    VOICE_AUTHORIZED_ALLOWLIST,
    VOICE_EMERGENCY_DISABLE,
    VOICE_MAX_DAILY_CALLS,
    VOICE_MAX_DURATION_SECONDS,
)
from backend.app.db import get_db
from backend.app.models.auth import AuthUser

router = APIRouter(tags=["Dograh Voice AI"])

Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[AuthUser, Depends(get_current_user)]


@router.get("/api/v1/voice/dograh/config")
@router.get("/voice/dograh/config")
@router.get("/dograh/config")
def get_dograh_config(actor: Actor):
    """Inspect Dograh integration configuration and Exotel telephony status safely.
    Secrets and authorization headers are never exposed.
    """
    import os
    from backend.app.config import reload_env
    reload_env()

    current_key = os.getenv("DOGRAH_API_KEY") or DOGRAH_API_KEY or dograh_client.api_key
    current_webhook_secret = os.getenv("DOGRAH_WEBHOOK_SECRET") or DOGRAH_WEBHOOK_SECRET
    current_dry_run = os.getenv("DOGRAH_DRY_RUN", str(DOGRAH_DRY_RUN)).lower() in ("true", "1", "yes")

    exotel_sid = os.getenv("EXOTEL_ACCOUNT_SID") or EXOTEL_ACCOUNT_SID
    exotel_key = os.getenv("EXOTEL_API_KEY") or EXOTEL_API_KEY
    exotel_caller = os.getenv("EXOTEL_CALLER_ID") or EXOTEL_CALLER_ID
    exotel_configured = bool(exotel_sid and exotel_key and exotel_caller)

    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID") or TWILIO_ACCOUNT_SID
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN") or TWILIO_AUTH_TOKEN
    twilio_phone = os.getenv("TWILIO_PHONE_NUMBER") or TWILIO_PHONE_NUMBER
    twilio_configured = bool(twilio_sid and twilio_token and twilio_phone)

    telephony_provider = "twilio" if twilio_configured or twilio_sid else ("exotel" if exotel_configured else "twilio")

    allowlist = [n.strip() for n in os.getenv("VOICE_AUTHORIZED_ALLOWLIST", "").split(",") if n.strip()] or VOICE_AUTHORIZED_ALLOWLIST
    emergency_disable = os.getenv("VOICE_EMERGENCY_DISABLE", str(VOICE_EMERGENCY_DISABLE)).lower() in ("true", "1", "yes")
    max_daily = int(os.getenv("VOICE_MAX_DAILY_CALLS", str(VOICE_MAX_DAILY_CALLS)))
    max_duration = int(os.getenv("VOICE_MAX_DURATION_SECONDS", str(VOICE_MAX_DURATION_SECONDS)))

    return {
        "provider": "dograh",
        "agent_name": "AuditAI Vendor RFQ Follow-up",
        "telephony_provider": telephony_provider,
        "trigger_path_configured": bool(DOGRAH_TRIGGER_PATH),
        "trigger_path": DOGRAH_TRIGGER_PATH,
        "dry_run_active": current_dry_run,
        "api_key_configured": bool(current_key and current_key.strip()),
        "webhook_secret_configured": bool(current_webhook_secret and current_webhook_secret.strip()),
        "twilio": {
            "configured": twilio_configured,
            "account_sid_configured": bool(twilio_sid),
            "phone_number_configured": bool(twilio_phone),
            "phone_number": twilio_phone if twilio_phone else None,
        },
        "exotel": {
            "configured": exotel_configured,
            "account_sid_configured": bool(exotel_sid),
            "caller_id_configured": bool(exotel_caller),
            "caller_id": exotel_caller if exotel_caller else None,
            "base_url": os.getenv("EXOTEL_BASE_URL", EXOTEL_BASE_URL),
        },
        "safety_controls": {
            "allowlist_active": bool(allowlist),
            "allowlist_count": len(allowlist),
            "emergency_disable_active": emergency_disable,
            "max_daily_calls": max_daily,
            "max_duration_seconds": max_duration,
            "telephony_calls_prevented": current_dry_run,
            "zero_dollar_spend_guaranteed": current_dry_run,
        },
        "safeguards": {
            "telephony_calls_prevented": current_dry_run,
            "zero_dollar_spend_guaranteed": current_dry_run,
        },
    }


@router.post(
    "/api/v1/voice/dograh/start-call",
    response_model=DograhTriggerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger outbound RFQ follow-up call via Dograh Voice AI",
)
@router.post(
    "/voice/dograh/start-call",
    response_model=DograhTriggerResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/dograh/start-call",
    response_model=DograhTriggerResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=True,
)
async def start_call(payload: StartCallRequest, db: Db, actor: Actor):
    """Accepts structured RFQ & vendor information, validates requirements,
    and initiates an outbound voice conversation through the Dograh API Trigger.

    CRITICAL SAFEGUARD:
    When DOGRAH_DRY_RUN=true (the default), no external call is placed,
    no phone number is dialed, and a simulated execution response is returned.
    """
    try:
        response = await initiate_vendor_rfq_call(db, actor, payload)
        return response
    except VoiceServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except DograhClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred while preparing Dograh call: {str(exc)}",
        ) from exc


@router.post(
    "/api/v1/voice/twilio/start-call",
    status_code=status.HTTP_201_CREATED,
    summary="Trigger outbound RFQ follow-up call via Twilio Voice Telephony",
)
@router.post(
    "/voice/twilio/start-call",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/twilio/start-call",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=True,
)
async def start_twilio_call(
    payload: StartCallRequest,
    db: Db,
    actor: Actor,
    force_live: bool = False,
):
    """Triggers automated outbound voice outreach using Twilio Voice.
    Enforces allowlist verification, maximum concurrency, and duration limits.
    """
    try:
        response = await initiate_twilio_vendor_call(db, actor, payload, force_live=force_live)
        return response
    except VoiceServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error initiating Twilio call: {str(exc)}",
        ) from exc


@router.post(
    "/api/v1/voice/dograh/webhook",
    status_code=status.HTTP_200_OK,
    summary="Receive post-call conversation webhook from Dograh",
)
@router.post(
    "/dograh/webhook",
    status_code=status.HTTP_200_OK,
    include_in_schema=True,
)
def dograh_webhook(
    payload: DograhWebhookPayload,
    db: Db,
    authorization: Optional[str] = Header(None),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    x_dograh_secret: Optional[str] = Header(None, alias="X-Dograh-Secret"),
):
    """Receives post-call conversation results from Dograh Voice AI.
    Extracts quotation data, saves full transcript, updates vendor quotation status,
    and records immutable audit activity trail.

    Idempotent: Duplicate webhook deliveries return the existing processed receipt.
    """
    # Accept token from Authorization header or X-Webhook-Secret or X-Dograh-Secret
    secret_token = x_webhook_secret or x_dograh_secret or authorization

    try:
        result = process_dograh_webhook(db, payload, secret_token)
        return result
    except VoiceServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing Dograh webhook: {str(exc)}",
        ) from exc


@router.get(
    "/api/v1/voice/dograh/status/{workflow_run_id}",
    summary="Query status and collected quotation by Dograh workflow_run_id or call ID",
)
@router.get(
    "/dograh/status/{workflow_run_id}",
    include_in_schema=True,
)
def get_call_status(workflow_run_id: str, db: Db, actor: Actor):
    """Returns the execution status, call outcome, collected quotation fields,
    and transcript for a given Dograh workflow run or call UUID.
    """
    try:
        return get_workflow_run_status(db, workflow_run_id, actor)
    except VoiceServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving Dograh run status: {str(exc)}",
        ) from exc


@router.post(
    "/api/v1/voice/exotel/callback",
    status_code=status.HTTP_200_OK,
    summary="Receive real-time telephony status callback from Exotel OpenVBX",
)
@router.post(
    "/exotel/callback",
    status_code=status.HTTP_200_OK,
    include_in_schema=True,
)
async def exotel_status_callback(request: Request, db: Db):
    """Processes real-time telephony status callbacks from Exotel OpenVBX.
    Tracks low-level PSTN events (ringing, in-progress, completed, busy, no-answer, failed)
    and maps CallSid to AuditAI VoiceCall records.
    Handles both JSON and form-urlencoded payloads.
    """
    content_type = request.headers.get("content-type", "")
    data = {}
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        form = await request.form()
        data = dict(form)

    payload = ExotelCallbackPayload.model_validate(data)
    result = process_exotel_callback(db, payload)
    return result


@router.post(
    "/api/v1/voice/twilio/callback",
    status_code=status.HTTP_200_OK,
    summary="Receive real-time telephony status callback from Twilio Voice",
)
@router.post(
    "/twilio/callback",
    status_code=status.HTTP_200_OK,
    include_in_schema=True,
)
async def twilio_status_callback(request: Request, db: Db):
    """Processes real-time telephony status callbacks from Twilio Voice.
    Tracks PSTN events (queued, ringing, in-progress, completed, busy, failed, no-answer)
    and maps CallSid to AuditAI VoiceCall records.
    Handles both JSON and form-urlencoded payloads.
    """
    content_type = request.headers.get("content-type", "")
    data = {}
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        form = await request.form()
        data = dict(form)

    payload = TwilioCallbackPayload.model_validate(data)
    result = process_twilio_callback(db, payload)
    return result
