"""Domain service for Dograh Voice AI.
Coordinates between AuditAI's procurement sourcing models and Dograh Voice AI.
Handles outbound trigger preparation, dry-run safety, webhook processing,
Exotel OpenVBX telephony integration, and quotation persistence.
"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.agentic_ai.records import AgentActivity, AgentRun, AgentVendor
from backend.app.agentic_ai.voice.dograh_client import DograhClientError, dograh_client
from backend.app.agentic_ai.voice.dograh_schemas import (
    DograhInitialContext,
    DograhTriggerRequest,
    DograhTriggerResponse,
    DograhWebhookPayload,
    ExotelCallbackPayload,
    TwilioCallbackPayload,
    StartCallRequest,
    clean_phone_number,
    is_valid_indian_phone,
)
from backend.app.agentic_ai.voice.models import (
    VoiceCall,
    VoiceOperation,
    VoiceQuotation,
    VoiceQuotationField,
    VoiceTranscript,
    utcnow,
)
from backend.app.agentic_ai.voice.schemas import CallDraftCreate
from backend.app.agentic_ai.voice.services import (
    VoiceServiceError,
    owned_rfq,
    owned_vendor,
    prepare_call,
)
from backend.app.config import (
    DOGRAH_WEBHOOK_SECRET,
    EXOTEL_ACCOUNT_SID,
    EXOTEL_API_KEY,
    EXOTEL_CALLER_ID,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    VOICE_AUTHORIZED_ALLOWLIST,
    VOICE_EMERGENCY_DISABLE,
    VOICE_MAX_DAILY_CALLS,
    VOICE_MAX_DURATION_SECONDS,
)
from backend.app.models.auth import AuthUser
from backend.app.sourcing.requirements import Requirements

logger = logging.getLogger("auditai.voice.dograh_service")


def check_voice_calling_safety(
    db: Session,
    phone_number: str,
    dry_run: bool,
    actor_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Enforce strict multi-layered calling safety rules:
    1. Emergency disable switch (VOICE_EMERGENCY_DISABLE).
    2. Indian phone number E.164 format (+91XXXXXXXXXX).
    3. Allowlist verification for test calls (VOICE_AUTHORIZED_ALLOWLIST).
    4. Concurrency lock (maximum 1 concurrent call).
    5. Daily quota limit (maximum calls per 24 hours).
    """
    cleaned_phone = clean_phone_number(phone_number)

    # 1. Emergency disable switch
    if VOICE_EMERGENCY_DISABLE:
        logger.error("Voice calling is globally blocked by VOICE_EMERGENCY_DISABLE=True")
        raise VoiceServiceError(
            503,
            "Voice calling is currently disabled by the emergency safety switch (VOICE_EMERGENCY_DISABLE=true).",
        )

    # 2. Indian phone number validation
    if not is_valid_indian_phone(cleaned_phone):
        raise VoiceServiceError(
            422,
            f"Invalid Indian phone number '{phone_number}'. Must be a valid 10-digit Indian number prefixed with +91 (e.g. +919876543210).",
        )

    # 3. Allowlist check (if allowlist is populated)
    allowlist = [clean_phone_number(n) for n in VOICE_AUTHORIZED_ALLOWLIST if n]
    allowlist_verified = False
    if allowlist:
        if cleaned_phone not in allowlist:
            if not dry_run:
                raise VoiceServiceError(
                    403,
                    f"Phone number '{phone_number}' is not on the authorized testing allowlist. Live calls are restricted to pre-approved numbers.",
                )
        else:
            allowlist_verified = True

    # 4. Concurrency check (Max 1 simultaneous call in active states)
    active_calls = db.query(VoiceCall).filter(
        VoiceCall.status.in_(["ringing", "in_progress", "queued"])
    ).count()
    if active_calls >= 1 and not dry_run:
        raise VoiceServiceError(
            429,
            "Concurrency limit reached: Another voice call is currently active. Only 1 simultaneous call is permitted.",
        )

    # 5. Daily quota check (Max calls per 24 hours)
    if not dry_run and actor_id is not None:
        one_day_ago = utcnow() - timedelta(hours=24)
        daily_calls = db.query(VoiceCall).filter(
            VoiceCall.created_at >= one_day_ago,
            VoiceCall.status.in_(["completed", "ringing", "in_progress", "queued"]),
        ).count()
        if daily_calls >= VOICE_MAX_DAILY_CALLS:
            raise VoiceServiceError(
                429,
                f"Daily quota reached: Maximum {VOICE_MAX_DAILY_CALLS} live voice call(s) permitted per 24 hours.",
            )

    twilio_configured = bool(
        (os.getenv("TWILIO_ACCOUNT_SID") or TWILIO_ACCOUNT_SID)
        and (os.getenv("TWILIO_AUTH_TOKEN") or TWILIO_AUTH_TOKEN)
        and (os.getenv("TWILIO_PHONE_NUMBER") or TWILIO_PHONE_NUMBER)
    )

    return {
        "cleaned_phone": cleaned_phone,
        "allowlist_verified": allowlist_verified,
        "max_duration_seconds": VOICE_MAX_DURATION_SECONDS,
        "exotel_configured": bool(EXOTEL_ACCOUNT_SID and EXOTEL_API_KEY and EXOTEL_CALLER_ID),
        "twilio_configured": twilio_configured,
    }


def _extract_rfq_context(request_row, vendor_row, phone_number: str) -> DograhInitialContext:
    """Build structured context matching Dograh voice agent prompt template variables."""
    snapshot = Requirements.model_validate(request_row.requirements).model_dump(mode="json")
    line_items = snapshot.get("line_items") or []

    # Product/service name
    product_name = (
        snapshot.get("product")
        or (line_items[0].get("description") if line_items else None)
        or "Procurement Goods and Services"
    )

    # Quantity
    quantity = line_items[0].get("quantity", 1) if line_items else 1

    # Currency
    currency = snapshot.get("currency") or "INR"

    # Delivery location
    delivery_location = (
        snapshot.get("delivery_location")
        or (line_items[0].get("location") if line_items else None)
        or "Standard Destination"
    )

    # Target date
    target_date = (
        snapshot.get("contract_end")
        or snapshot.get("contract_start")
        or "Immediate / Standard SLA"
    )

    tracking_reference = f"AuditAI-R{vendor_row.run_id}-V{vendor_row.id}"

    return DograhInitialContext(
        vendor_name=vendor_row.vendor_name,
        vendor_contact_number=phone_number,
        rfq_reference=tracking_reference,
        product_name=str(product_name)[:300],
        quantity=quantity,
        currency=str(currency).upper()[:5],
        delivery_location=str(delivery_location)[:200],
        target_date=str(target_date)[:50],
    )


async def initiate_vendor_rfq_call(
    db: Session,
    actor: AuthUser,
    payload: StartCallRequest,
) -> DograhTriggerResponse:
    """Initiate an outbound vendor call through Dograh API Trigger.
    Always respects DOGRAH_DRY_RUN (default=True) to prevent actual phone calls
    unless explicitly configured.

    Supports both:
    1. Database-backed execution (via `request_id` and `agent_vendor_id`).
    2. Synthetic / direct dry-run testing (via direct vendor/RFQ fields).
    """
    request_row = None
    vendor_row = None
    if payload.request_id and payload.agent_vendor_id:
        try:
            request_row = owned_rfq(db, payload.request_id, actor)
            vendor_row = owned_vendor(db, request_row.id, payload.agent_vendor_id, actor)
        except VoiceServiceError as exc:
            # In dry-run mode or synthetic testing, gracefully fall back to direct simulation
            # instead of returning a hard 404 error when records are from different sessions.
            if not (dograh_client.dry_run or payload.test_mode):
                raise
            logger.info("Falling back to synthetic dry-run call execution: %s", exc.detail)
            request_row = None
            vendor_row = None

    if request_row and vendor_row:
        # Resolve phone number: payload override > vendor offer > vendor catalog
        offer = vendor_row.offer or {}
        phone_number = (
            payload.phone_number
            or offer.get("phone")
            or offer.get("contact_phone")
            or offer.get("phone_number")
        )

        # In dry-run mode, provide a mock fallback phone if vendor didn't have one
        if not phone_number and dograh_client.dry_run:
            phone_number = "+919876543210"

        if not phone_number:
            raise VoiceServiceError(
                422,
                f"Vendor '{vendor_row.vendor_name}' does not have a contact phone number on file. "
                "Please provide a phone_number in the request.",
            )

        # Enforce multi-layered calling safety rules (emergency switch, Indian phone format, allowlist, concurrency, daily quota)
        safety_info = check_voice_calling_safety(
            db=db,
            phone_number=phone_number,
            dry_run=dograh_client.dry_run,
            actor_id=actor.id if actor else None,
        )
        phone_number = safety_info["cleaned_phone"]

        # 1. Prepare VoiceCall record and validate requirements via existing service
        draft_key = payload.idempotency_key or f"call_{request_row.id}_{vendor_row.id}_{uuid4().hex[:8]}"
        draft_payload = CallDraftCreate(
            request_id=request_row.id,
            agent_vendor_id=vendor_row.id,
            idempotency_key=draft_key,
        )
        voice_call = prepare_call(db, actor, draft_payload)

        # 2. Build structured Dograh context & trigger request
        initial_context = _extract_rfq_context(request_row, vendor_row, phone_number)

        # Apply overrides if provided in payload
        if payload.vendor_name:
            initial_context.vendor_name = payload.vendor_name
        if payload.rfq_reference:
            initial_context.rfq_reference = payload.rfq_reference
        if payload.product_name:
            initial_context.product_name = payload.product_name
        if payload.quantity is not None:
            initial_context.quantity = payload.quantity
        if payload.currency:
            initial_context.currency = payload.currency
        if payload.delivery_location:
            initial_context.delivery_location = payload.delivery_location
        if payload.target_date or payload.target_delivery_date:
            initial_context.target_date = payload.target_date or payload.target_delivery_date

        trigger_request = DograhTriggerRequest(
            phone_number=phone_number,
            initial_context=initial_context,
        )

        # 3. Dispatch through DograhClient (dry-run safe)
        response = await dograh_client.trigger_call(
            request=trigger_request,
            test_mode=payload.test_mode,
            call_id=voice_call.id,
        )
        response.exotel_telephony_configured = safety_info["exotel_configured"]
        response.twilio_telephony_configured = safety_info["twilio_configured"]
        response.allowlist_verified = safety_info["allowlist_verified"]
        response.max_duration_seconds = safety_info["max_duration_seconds"]

        # 4. Update VoiceCall record with provider run ID and status
        voice_call.provider_call_id = response.workflow_run_id
        voice_call.status = "queued" if not response.dry_run else "prepared"
        voice_call.summary = response.message
        voice_call.started_at = utcnow()

        # 5. Record activity in sourcing agent timeline
        db.add(
            AgentActivity(
                run_id=vendor_row.run_id,
                request_id=request_row.id,
                actor=f"user:{actor.id}",
                event="voice_call_triggered",
                details={
                    "call_id": voice_call.id,
                    "workflow_run_id": response.workflow_run_id,
                    "vendor_name": initial_context.vendor_name,
                    "dry_run": response.dry_run,
                    "tracking_reference": initial_context.rfq_reference,
                },
            )
        )
        db.commit()
        return response

    else:
        # Synthetic / direct test execution (ideal for Swagger testing with synthetic data)
        phone_number = payload.phone_number or "+919876543210"
        safety_info = check_voice_calling_safety(
            db=db,
            phone_number=phone_number,
            dry_run=dograh_client.dry_run,
            actor_id=None,
        )
        phone_number = safety_info["cleaned_phone"]

        vendor_name = payload.vendor_name or "Demo Electronics"
        rfq_ref = payload.rfq_reference or "AuditAI-TEST-001"
        product = payload.product_name or "DataSafe Standard"
        qty = payload.quantity if payload.quantity is not None else 1
        curr = payload.currency or "INR"
        location = payload.delivery_location or "India"
        target_dt = payload.target_date or payload.target_delivery_date or "2026-12-04"

        synthetic_context = DograhInitialContext(
            vendor_name=vendor_name,
            vendor_contact_number=phone_number,
            rfq_reference=rfq_ref,
            product_name=product,
            quantity=qty,
            currency=curr,
            delivery_location=location,
            target_date=target_dt,
        )

        trigger_request = DograhTriggerRequest(
            phone_number=phone_number,
            initial_context=synthetic_context,
        )

        call_id = f"sim_call_{uuid4().hex[:12]}"
        response = await dograh_client.trigger_call(
            request=trigger_request,
            test_mode=payload.test_mode,
            call_id=call_id,
        )
        response.exotel_telephony_configured = safety_info["exotel_configured"]
        response.twilio_telephony_configured = safety_info["twilio_configured"]
        response.allowlist_verified = safety_info["allowlist_verified"]
        response.max_duration_seconds = safety_info["max_duration_seconds"]
        return response


async def initiate_twilio_vendor_call(
    db: Session,
    actor: AuthUser,
    payload: StartCallRequest,
    force_live: bool = False,
) -> Dict[str, Any]:
    """Initiates an automated outbound procurement call via Twilio Voice.
    Strictly verifies allowlist, concurrency, and emergency disable safeguards.
    """
    from backend.app.agentic_ai.voice.twilio_client import twilio_voice_client, TwilioClientError

    phone_number = payload.phone_number or "+916350209890"
    vendor_name = payload.vendor_name or "Vendor Contact"
    rfq_reference = payload.rfq_reference or "AuditAI-TWILIO-001"
    product_name = payload.product_name or "Procurement Requirement"

    is_dry_run = dograh_client.dry_run and not force_live

    # 1. Enforce safety checks
    safety_info = check_voice_calling_safety(
        db=db,
        phone_number=phone_number,
        dry_run=is_dry_run,
        actor_id=actor.id if actor else None,
    )
    phone_number = safety_info["cleaned_phone"]

    if not twilio_voice_client.is_configured():
        raise VoiceServiceError(500, "Twilio telephony credentials are not configured in .env.")

    # 2. Dry run handling
    if is_dry_run:
        sim_sid = f"sim_CA{uuid4().hex[:30]}"
        return {
            "status": "dry_run_success",
            "provider": "twilio",
            "call_sid": sim_sid,
            "to": phone_number,
            "from": twilio_voice_client.phone_number,
            "tracking_reference": rfq_reference,
            "message": "Twilio call simulated successfully. Dry-run mode active (no live phone dialed).",
            "dry_run": True,
            "allowlist_verified": safety_info["allowlist_verified"],
        }

    # 3. Live call execution
    try:
        call_res = await twilio_voice_client.initiate_call(
            to_phone=phone_number,
            vendor_name=vendor_name,
            rfq_reference=rfq_reference,
            product_name=product_name,
        )
    except TwilioClientError as exc:
        raise VoiceServiceError(exc.status_code, f"Twilio dispatch failed: {exc.detail}")

    call_sid = call_res.get("call_sid")

    # 4. Record in database if request_id and vendor_id provided
    if payload.request_id and payload.agent_vendor_id:
        req = owned_rfq(db, payload.request_id, actor)
        vnd = owned_vendor(db, req.id, payload.agent_vendor_id, actor)
        vc = VoiceCall(
            request_id=req.id,
            agent_vendor_id=vnd.id,
            owner_id=actor.id,
            provider="twilio",
            provider_call_id=call_sid,
            tracking_reference=rfq_reference,
            status="queued",
            requirements_snapshot=req.requirements,
            started_at=utcnow(),
        )
        db.add(vc)
        db.commit()

    return {
        "status": "initiated",
        "provider": "twilio",
        "call_sid": call_sid,
        "to": phone_number,
        "from": twilio_voice_client.phone_number,
        "tracking_reference": rfq_reference,
        "message": f"Twilio outbound call placed to {phone_number}.",
        "dry_run": False,
        "allowlist_verified": safety_info["allowlist_verified"],
    }


def verify_webhook_authentication(auth_header: Optional[str]) -> bool:
    """Validate incoming Dograh webhook using DOGRAH_WEBHOOK_SECRET if configured."""
    secret = DOGRAH_WEBHOOK_SECRET
    if not secret:
        # If no secret configured, accept webhook (log warning)
        logger.warning("DOGRAH_WEBHOOK_SECRET is not configured; skipping signature verification.")
        return True

    if not auth_header:
        return False

    # Check for direct match or Bearer prefix
    clean_token = auth_header.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    return clean_token == secret.strip()


def process_dograh_webhook(
    db: Session,
    payload: DograhWebhookPayload,
    secret_header: Optional[str] = None,
) -> Dict[str, Any]:
    """Process post-call conversation webhook from Dograh.
    Extracts commercial quote data, stores transcripts, creates/updates VoiceQuotation,
    and updates vendor status idempotently.
    """
    if not verify_webhook_authentication(secret_header):
        raise VoiceServiceError(401, "Invalid or missing Dograh webhook secret.")

    # 1. Resolve tracking reference (AuditAI-R{run}-V{vendor})
    ref = None
    if payload.initial_context and isinstance(payload.initial_context, dict):
        ref = payload.initial_context.get("rfq_reference")

    if not ref and payload.collected_data and isinstance(payload.collected_data, dict):
        ref = payload.collected_data.get("rfq_reference")

    # Match by reference or provider_call_id
    call = None
    if payload.workflow_run_id:
        call = db.query(VoiceCall).filter_by(provider_call_id=str(payload.workflow_run_id)).first()

    if not call and payload.call_id:
        call = db.query(VoiceCall).filter_by(id=str(payload.call_id)).first()

    if not call and ref:
        match = re.fullmatch(r"AuditAI-R([1-9][0-9]{0,9})-V([1-9][0-9]{0,9})", ref)
        if match:
            run_id, vendor_id = map(int, match.groups())
            call = db.query(VoiceCall).filter_by(
                request_id=db.query(AgentRun.request_id).filter_by(id=run_id).scalar(),
                agent_vendor_id=vendor_id,
            ).order_by(VoiceCall.created_at.desc()).first()

    if not call:
        logger.warning("Dograh webhook received for unknown call or reference: %s (run_id=%s)", ref, payload.workflow_run_id)
        return {
            "status": "unmatched_call_recorded",
            "reference": ref,
            "workflow_run_id": payload.workflow_run_id,
            "message": "Webhook received but call could not be matched to an active AuditAI RFQ.",
        }

    # 2. Idempotency Check: if quotation is already finalized with this workflow_run_id
    existing_quote = db.query(VoiceQuotation).filter_by(call_id=call.id).first()
    if existing_quote and existing_quote.status == "complete" and call.status == "completed":
        logger.info("Dograh webhook duplicate received for finalized call %s; returning existing receipt.", call.id)
        return {
            "status": "already_processed",
            "call_id": call.id,
            "quotation_id": existing_quote.id,
            "tracking_reference": call.tracking_reference,
            "message": "Webhook was already processed idempotently.",
        }

    # 3. Update Call Status & Duration
    call_status = str(payload.status or payload.disposition or "completed").lower()
    if call_status in ("completed", "answered", "success"):
        call.status = "completed"
        call.outcome = "Quote received via voice conversation"
    elif call_status in ("no_answer", "busy", "failed", "unanswered"):
        call.status = call_status
        call.outcome = f"Call outcome: {call_status}"
    else:
        call.status = "completed"
        call.outcome = call_status

    if payload.duration_seconds is not None:
        call.duration_seconds = payload.duration_seconds
    call.ended_at = utcnow()
    if payload.summary:
        call.summary = payload.summary

    # 4. Save Transcript Turns
    transcript_text_lines = []
    if payload.transcript:
        if isinstance(payload.transcript, list):
            for idx, turn in enumerate(payload.transcript):
                raw_speaker = str(turn.get("speaker") or turn.get("role") or "assistant").lower()
                speaker = "assistant" if raw_speaker in ("agent", "assistant", "ai", "system", "bot") else "vendor"
                text = str(turn.get("text") or turn.get("content") or "").strip()
                if text:
                    transcript_text_lines.append(f"{speaker.capitalize()}: {text}")
                    db.add(
                        VoiceTranscript(
                            call_id=call.id,
                            speaker=speaker,
                            message=text,
                            message_key=f"turn_{idx}_{uuid4().hex[:6]}",
                            offset_seconds=turn.get("offset_seconds"),
                        )
                    )
        elif isinstance(payload.transcript, str) and payload.transcript.strip():
            transcript_text_lines.append(payload.transcript.strip())
            db.add(
                VoiceTranscript(
                    call_id=call.id,
                    speaker="assistant",
                    message=payload.transcript.strip(),
                    message_key=f"raw_{uuid4().hex[:8]}",
                )
            )

    full_transcript_str = "\n".join(transcript_text_lines)

    # 5. Extract & Normalize Quotation Fields
    collected = payload.collected_data or payload.variables or {}
    total_val = collected.get("total_amount") or collected.get("total_price") or collected.get("quoted_price")
    unit_val = collected.get("unit_price") or collected.get("rate")
    lead_time_val = collected.get("delivery_lead_time_days") or collected.get("lead_time")
    payment_terms_val = collected.get("payment_terms")
    warranty_val = collected.get("warranty")
    shipping_val = collected.get("shipping_charges") or collected.get("freight")
    tax_val = collected.get("taxes") or collected.get("tax")
    avail_val = collected.get("product_availability") or collected.get("availability")

    # Create or update VoiceQuotation
    if not existing_quote:
        quote = VoiceQuotation(
            call_id=call.id,
            request_id=call.request_id,
            agent_vendor_id=call.agent_vendor_id,
            status="complete" if (total_val or unit_val) else "needs_verification",
        )
        db.add(quote)
        db.flush()
    else:
        quote = existing_quote
        if total_val or unit_val:
            quote.status = "complete"
        quote.version += 1
        quote.updated_at = utcnow()

    # Save quotation fields with confirmation
    field_mappings = {
        "total_amount": total_val,
        "unit_price": unit_val,
        "delivery_lead_time_days": lead_time_val,
        "payment_terms": payment_terms_val,
        "warranty": warranty_val,
        "shipping_charges": shipping_val,
        "taxes": tax_val,
        "product_availability": avail_val,
    }

    for f_name, f_val in field_mappings.items():
        if f_val is not None:
            existing_f = db.query(VoiceQuotationField).filter_by(
                quotation_id=quote.id, name=f_name
            ).first()
            val_str = str(f_val).strip()
            if existing_f:
                existing_f.value = val_str
                existing_f.status = "CONFIRMED"
                existing_f.confirmation_note = "Confirmed via Dograh Voice AI conversation"
                existing_f.updated_at = utcnow()
            else:
                db.add(
                    VoiceQuotationField(
                        quotation_id=quote.id,
                        name=f_name,
                        value=val_str,
                        original_response=val_str,
                        status="CONFIRMED",
                        confirmation_note="Confirmed via Dograh Voice AI conversation",
                    )
                )

    # 6. Update AgentVendor in Sourcing Workspace
    vendor = db.get(AgentVendor, call.agent_vendor_id)
    if vendor:
        offer_data = dict(vendor.offer or {})
        if total_val:
            try:
                offer_data["total_price"] = float(str(total_val).replace(",", "").replace("₹", "").replace("$", ""))
            except (ValueError, TypeError):
                offer_data["total_price"] = str(total_val)
        if unit_val:
            try:
                offer_data["unit_price"] = float(str(unit_val).replace(",", "").replace("₹", "").replace("$", ""))
            except (ValueError, TypeError):
                offer_data["unit_price"] = str(unit_val)
        if payment_terms_val:
            offer_data["payment_terms"] = str(payment_terms_val)
        if warranty_val:
            offer_data["warranty"] = str(warranty_val)
        if lead_time_val:
            offer_data["lead_time"] = str(lead_time_val)

        offer_data["voice_call_completed"] = True
        offer_data["voice_call_id"] = call.id
        offer_data["workflow_run_id"] = payload.workflow_run_id
        vendor.offer = offer_data

        if full_transcript_str:
            vendor.reply_text = f"[Dograh Voice Call Quotation]\n{full_transcript_str}"

        # 7. Record Sourcing Activity Log
        db.add(
            AgentActivity(
                run_id=vendor.run_id,
                request_id=call.request_id,
                actor="dograh:voice_agent",
                event="voice_quotation_received",
                details={
                    "call_id": call.id,
                    "workflow_run_id": payload.workflow_run_id,
                    "vendor_id": vendor.id,
                    "vendor_name": vendor.vendor_name,
                    "quoted_total": total_val,
                    "call_status": call.status,
                    "duration_seconds": call.duration_seconds,
                },
            )
        )

    db.commit()

    return {
        "status": "processed",
        "call_id": call.id,
        "quotation_id": quote.id,
        "tracking_reference": call.tracking_reference,
        "call_status": call.status,
        "quotation_status": quote.status,
        "fields_recorded": [k for k, v in field_mappings.items() if v is not None],
        "transcript_turns": len(transcript_text_lines),
    }


def process_exotel_callback(
    db: Session,
    payload: ExotelCallbackPayload,
) -> Dict[str, Any]:
    """Process real-time status callback from Exotel OpenVBX.
    Maps CallSid, telephony lifecycle status (ringing, in-progress, completed, busy, no-answer, failed),
    duration, and recording URL to the corresponding VoiceCall record.
    """
    call_sid = payload.CallSid
    if not call_sid:
        return {"status": "ignored", "reason": "No CallSid provided in callback"}

    # Find call by provider_call_id or CustomField
    call = db.query(VoiceCall).filter(
        (VoiceCall.provider_call_id == call_sid) |
        (VoiceCall.id == payload.CustomField)
    ).first()

    if not call and payload.To:
        cleaned_to = clean_phone_number(payload.To)
        call = db.query(VoiceCall).filter(
            VoiceCall.status.in_(["prepared", "queued", "ringing", "in_progress"])
        ).order_by(VoiceCall.created_at.desc()).first()

    if not call:
        logger.info("Exotel callback for CallSid=%s could not be matched to an active call.", call_sid)
        return {"status": "unmatched", "call_sid": call_sid}

    # Map Exotel status to VoiceCall status
    raw_status = (payload.Status or "").lower()
    if raw_status in ("completed", "terminal"):
        call.status = "completed"
        call.ended_at = utcnow()
    elif raw_status in ("busy",):
        call.status = "busy"
        call.ended_at = utcnow()
    elif raw_status in ("no-answer", "no_answer"):
        call.status = "no_answer"
        call.ended_at = utcnow()
    elif raw_status in ("failed",):
        call.status = "failed"
        call.ended_at = utcnow()
    elif raw_status in ("in-progress", "in_progress"):
        call.status = "in_progress"
        if not call.started_at:
            call.started_at = utcnow()
    elif raw_status in ("ringing",):
        call.status = "ringing"

    if payload.Duration is not None:
        try:
            call.duration_seconds = float(payload.Duration)
        except (ValueError, TypeError):
            pass

    if not call.provider_call_id or call.provider_call_id.startswith("sim_dgr_"):
        call.provider_call_id = call_sid

    db.commit()
    logger.info("Exotel callback updated call_id=%s with status=%s CallSid=%s", call.id, call.status, call_sid)
    return {
        "status": "updated",
        "call_id": call.id,
        "call_status": call.status,
        "call_sid": call_sid,
    }


def process_twilio_callback(db: Session, payload: TwilioCallbackPayload) -> Dict[str, Any]:
    """Process incoming status callback from Twilio Voice.
    Updates VoiceCall status (queued, ringing, in-progress, completed, busy, failed, no-answer).
    """
    call_sid = payload.CallSid
    if not call_sid:
        return {"status": "ignored", "reason": "missing CallSid"}

    # Look up call by provider_call_id or matching recent call
    call = db.query(VoiceCall).filter(
        (VoiceCall.provider_call_id == call_sid) | (VoiceCall.id == call_sid)
    ).first()

    if not call:
        # Match latest active call
        call = db.query(VoiceCall).order_by(VoiceCall.created_at.desc()).first()

    if not call:
        return {"status": "ignored", "reason": "no matching call found"}

    raw_status = (payload.CallStatus or "").lower()
    if raw_status in ("completed",):
        call.status = "completed"
        call.ended_at = utcnow()
    elif raw_status in ("busy",):
        call.status = "busy"
        call.ended_at = utcnow()
    elif raw_status in ("no-answer", "no_answer"):
        call.status = "no_answer"
        call.ended_at = utcnow()
    elif raw_status in ("failed", "canceled"):
        call.status = "failed"
        call.ended_at = utcnow()
    elif raw_status in ("in-progress", "in_progress"):
        call.status = "in_progress"
        if not call.started_at:
            call.started_at = utcnow()
    elif raw_status in ("ringing",):
        call.status = "ringing"
    elif raw_status in ("queued", "initiated"):
        call.status = "queued"

    if payload.CallDuration is not None:
        try:
            call.duration_seconds = float(payload.CallDuration)
        except (ValueError, TypeError):
            pass

    if not call.provider_call_id or call.provider_call_id.startswith("sim_dgr_"):
        call.provider_call_id = call_sid

    db.commit()
    logger.info("Twilio callback updated call_id=%s with status=%s CallSid=%s", call.id, call.status, call_sid)
    return {
        "status": "updated",
        "provider": "twilio",
        "call_id": call.id,
        "call_status": call.status,
        "call_sid": call_sid,
    }


def get_workflow_run_status(db: Session, workflow_run_id: str, actor: Optional[AuthUser] = None) -> Dict[str, Any]:
    """Retrieve call execution status and collected quotation by Dograh workflow_run_id or call ID."""
    call = db.query(VoiceCall).filter(
        (VoiceCall.provider_call_id == workflow_run_id) | (VoiceCall.id == workflow_run_id)
    ).first()

    if not call:
        raise VoiceServiceError(404, f"No voice call record found for workflow_run_id '{workflow_run_id}'.")

    # If actor provided, verify ownership
    if actor and call.owner_id != actor.id and getattr(actor, "role", "") != "admin":
        raise VoiceServiceError(403, "Not authorized to access this call record.")

    quote = db.query(VoiceQuotation).filter_by(call_id=call.id).first()
    fields = {}
    if quote:
        field_records = db.query(VoiceQuotationField).filter_by(quotation_id=quote.id).all()
        fields = {f.name: {"value": f.value, "status": f.status} for f in field_records}

    transcripts = db.query(VoiceTranscript).filter_by(call_id=call.id).order_by(VoiceTranscript.created_at).all()

    return {
        "call_id": call.id,
        "workflow_run_id": call.provider_call_id,
        "tracking_reference": call.tracking_reference,
        "status": call.status,
        "outcome": call.outcome,
        "duration_seconds": float(call.duration_seconds) if call.duration_seconds else None,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "quotation": {
            "id": quote.id if quote else None,
            "status": quote.status if quote else "not_started",
            "fields": fields,
        },
        "transcript": [{"speaker": t.speaker, "message": t.message} for t in transcripts],
    }
