"""Pydantic schemas for Dograh Voice AI API integration and Webhook processing."""
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re


def clean_phone_number(phone: str) -> str:
    """Standardize phone number to E.164 format with leading +."""
    cleaned = re.sub(r"[\s\-\(\)\.]", "", str(phone or ""))
    if not cleaned.startswith("+"):
        if cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = f"+{cleaned}"
        elif len(cleaned) == 10 and cleaned[0] in "123456789":
            cleaned = f"+91{cleaned}"
        else:
            cleaned = f"+{cleaned}"
    return cleaned


def is_valid_indian_phone(phone: str) -> bool:
    """Validate whether phone number conforms to Indian PSTN/Mobile E.164 format (+91 followed by 10 digits)."""
    cleaned = clean_phone_number(phone)
    return bool(re.match(r"^\+91[1-9]\d{9}$", cleaned))


class DograhInitialContext(BaseModel):
    """Context variables mapped to Dograh Voice Agent template variables:
    {{vendor_name}}, {{vendor_contact_number}}, {{rfq_reference}},
    {{product_name}}, {{quantity}}, {{currency}}, {{delivery_location}}, {{target_date}}
    """
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    vendor_name: str = Field(..., min_length=1, max_length=200, description="Name of the supplier or business")
    vendor_contact_number: Optional[str] = Field(None, max_length=50, description="Contact phone or mobile number")
    rfq_reference: str = Field(..., min_length=3, max_length=150, description="Tracking reference e.g. AuditAI-R18-V160")
    product_name: str = Field(..., min_length=1, max_length=300, description="Primary product or service description")
    quantity: Union[int, float, str] = Field(default=1, description="Quantity or service units requested")
    currency: str = Field(default="INR", min_length=3, max_length=5, description="ISO Currency code")
    delivery_location: Optional[str] = Field(default="Standard Destination", max_length=200)
    target_date: Optional[str] = Field(None, max_length=50, description="Desired completion or delivery date")


class DograhTriggerRequest(BaseModel):
    """Payload sent to Dograh API Trigger endpoint:
    POST https://api.dograh.com/api/v1/public/agent/<trigger_path>
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    phone_number: str = Field(..., min_length=7, max_length=30, description="E.164 formatted phone number e.g. +919876543210")
    initial_context: DograhInitialContext

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        # Standardize and validate phone number format (+ and digits)
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
            raise ValueError("Phone number must contain between 7 and 15 digits, optionally prefixed with '+'.")
        if not cleaned.startswith("+"):
            cleaned = f"+{cleaned}"
        return cleaned


class DograhTriggerResponse(BaseModel):
    """Response returned to AuditAI callers when initiating a Dograh call."""
    model_config = ConfigDict(extra="allow")

    status: str = Field(..., description="Execution status: initiated | dry_run_success | queued | failed")
    workflow_run_id: str = Field(..., description="Unique Dograh workflow run identifier or simulated run ID")
    call_id: Optional[str] = Field(None, description="AuditAI internal VoiceCall UUID")
    tracking_reference: str
    phone_number: str
    message: str
    dry_run: bool = Field(default=True, description="True if no actual telephony session or dial was executed")
    endpoint_used: Optional[str] = None
    prepared_payload: Optional[Dict[str, Any]] = Field(None, description="Prepared API payload available in dry-run mode for inspection")
    exotel_telephony_configured: bool = Field(default=False, description="True if Exotel credentials and caller ID are configured")
    twilio_telephony_configured: bool = Field(default=False, description="True if Twilio credentials and phone number are configured")
    allowlist_verified: bool = Field(default=False, description="True if phone number was checked against authorized test allowlist")
    max_duration_seconds: Optional[int] = Field(default=120, description="Enforced maximum call duration limit")


class DograhCollectedData(BaseModel):
    """Commercial terms extracted during voice conversation by Dograh."""
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    unit_price: Optional[Union[str, float, int]] = None
    total_amount: Optional[Union[str, float, int]] = None
    currency: Optional[str] = "INR"
    shipping_charges: Optional[Union[str, float, int]] = None
    taxes: Optional[Union[str, float, int]] = None
    product_availability: Optional[str] = None
    delivery_lead_time_days: Optional[Union[int, str]] = None
    warranty: Optional[str] = None
    payment_terms: Optional[str] = None
    discounts: Optional[str] = None
    vendor_confirmed: Optional[bool] = None
    exotel_call_sid: Optional[str] = None
    notes: Optional[str] = None


class TranscriptItem(BaseModel):
    """Single turn in a conversation transcript."""
    model_config = ConfigDict(extra="allow")

    speaker: str = Field(default="agent", description="agent | vendor | customer | user")
    text: str = Field(..., description="Spoken utterance text")
    offset_seconds: Optional[float] = None


class DograhWebhookPayload(BaseModel):
    """Incoming post-call webhook payload from Dograh.
    Handles flexible nesting and standard Dograh webhook field names.
    """
    model_config = ConfigDict(extra="allow")

    workflow_run_id: Optional[str] = None
    call_id: Optional[str] = None
    exotel_call_sid: Optional[str] = None
    trigger_path: Optional[str] = None
    phone_number: Optional[str] = None
    status: Optional[str] = "completed"
    disposition: Optional[str] = Field(default="completed", description="completed | no_answer | busy | failed | unanswered")
    duration_seconds: Optional[Union[float, int]] = None
    initial_context: Optional[Dict[str, Any]] = None
    collected_data: Optional[Dict[str, Any]] = None
    variables: Optional[Dict[str, Any]] = None
    transcript: Optional[Union[List[Dict[str, Any]], str]] = None
    summary: Optional[str] = None


class ExotelCallbackPayload(BaseModel):
    """Incoming status callback payload from Exotel OpenVBX.
    Maps Exotel telephony events (ringing, in-progress, completed, busy, failed).
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    CallSid: Optional[str] = Field(None, alias="CallSid")
    From: Optional[str] = Field(None, alias="From")
    To: Optional[str] = Field(None, alias="To")
    Status: Optional[str] = Field(None, alias="Status")
    CallType: Optional[str] = Field(None, alias="CallType")
    Duration: Optional[Union[int, float, str]] = Field(None, alias="Duration")
    RecordingUrl: Optional[str] = Field(None, alias="RecordingUrl")
    StartTime: Optional[str] = Field(None, alias="StartTime")
    EndTime: Optional[str] = Field(None, alias="EndTime")
    CustomField: Optional[str] = Field(None, alias="CustomField")


class TwilioCallbackPayload(BaseModel):
    """Incoming status callback payload from Twilio Voice.
    Maps Twilio telephony events (queued, initiated, ringing, in-progress, completed, busy, failed, no-answer).
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    CallSid: Optional[str] = Field(None, alias="CallSid")
    AccountSid: Optional[str] = Field(None, alias="AccountSid")
    From: Optional[str] = Field(None, alias="From")
    To: Optional[str] = Field(None, alias="To")
    CallStatus: Optional[str] = Field(None, alias="CallStatus")
    CallDuration: Optional[Union[int, float, str]] = Field(None, alias="CallDuration")
    RecordingUrl: Optional[str] = Field(None, alias="RecordingUrl")
    SequenceNumber: Optional[Union[int, str]] = Field(None, alias="SequenceNumber")


class StartCallRequest(BaseModel):
    """API request body to trigger an outbound RFQ follow-up call via Dograh.
    Supports either:
    1. Database-linked calls via `request_id` and `agent_vendor_id`.
    2. Synthetic / direct test calls via explicit fields (`vendor_name`, `rfq_reference`, etc.).
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: Optional[int] = Field(None, gt=0, description="Sourcing request ID (optional if testing with synthetic context)")
    agent_vendor_id: Optional[int] = Field(None, gt=0, description="Shortlisted vendor record ID (optional if testing with synthetic context)")
    phone_number: Optional[str] = Field(None, description="Contact phone or mobile number (e.g. +919876543210)")
    vendor_name: Optional[str] = Field(None, description="Vendor name (e.g. Demo Electronics)")
    rfq_reference: Optional[str] = Field(None, description="RFQ Tracking reference (e.g. AuditAI-TEST-001)")
    product_name: Optional[str] = Field(None, description="Product or service name (e.g. DataSafe Standard)")
    quantity: Optional[Union[int, float, str]] = Field(None, description="Quantity or units")
    currency: Optional[str] = Field(None, description="ISO currency code (e.g. INR)")
    delivery_location: Optional[str] = Field(None, description="Delivery location or city")
    target_date: Optional[str] = Field(None, description="Desired delivery or completion date (e.g. 2026-12-04)")
    target_delivery_date: Optional[str] = Field(None, description="Alias for target_date")
    test_mode: bool = Field(default=False, description="When true, targets Dograh test draft endpoint instead of published production")
    idempotency_key: Optional[str] = Field(None, min_length=8, max_length=128, description="Client idempotency key to prevent duplicate calls")
