"""Asynchronous client for Twilio Voice Telephony API.
Enables AuditAI to initiate automated outbound telephony calls, generate dynamic TwiML,
and monitor live call state.
"""
import logging
import os
from typing import Any, Dict, Optional
from uuid import uuid4
import httpx

from backend.app.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    VOICE_MAX_DURATION_SECONDS,
)

logger = logging.getLogger("auditai.voice.twilio")


class TwilioClientError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TwilioVoiceClient:
    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        phone_number: Optional[str] = None,
    ):
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._phone_number = phone_number

    @property
    def account_sid(self) -> str:
        return self._account_sid or os.getenv("TWILIO_ACCOUNT_SID") or TWILIO_ACCOUNT_SID or ""

    @property
    def auth_token(self) -> str:
        return self._auth_token or os.getenv("TWILIO_AUTH_TOKEN") or TWILIO_AUTH_TOKEN or ""

    @property
    def phone_number(self) -> str:
        return self._phone_number or os.getenv("TWILIO_PHONE_NUMBER") or TWILIO_PHONE_NUMBER or ""

    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.phone_number)

    def generate_twiml(self, vendor_name: str, rfq_reference: str, product_name: str) -> str:
        """Construct interactive TwiML for procurement voice agent dialogue."""
        text = (
            f"Hello {vendor_name}, this is AuditAI Autonomous Procurement calling regarding your request for quotation "
            f"reference {rfq_reference} for {product_name}. "
            "Our procurement system has received your quotation. Thank you for partnering with AuditAI. "
            "This call has been recorded and verified by AuditAI Telephony."
        )
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Pause length="1"/>
    <Say voice="Polly.Aditi" language="en-IN">{text}</Say>
    <Pause length="1"/>
    <Say voice="Polly.Aditi" language="en-IN">Goodbye and have a productive day.</Say>
</Response>"""
        return twiml

    async def initiate_call(
        self,
        to_phone: str,
        vendor_name: str,
        rfq_reference: str,
        product_name: str,
        status_callback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trigger an outbound automated voice call via Twilio REST API."""
        if not self.is_configured():
            raise TwilioClientError(
                500,
                "Twilio is not fully configured. Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER.",
            )

        api_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json"
        twiml_url = os.getenv("TWILIO_TWIML_URL", "http://demo.twilio.com/docs/voice.xml")

        form_data = {
            "To": to_phone,
            "From": self.phone_number,
            "Url": twiml_url,
        }
        if status_callback_url:
            form_data["StatusCallback"] = status_callback_url

        logger.info(
            "Initiating Twilio outbound call: from=%s, to=%s, rfq=%s",
            self.phone_number,
            to_phone[:6] + "XXXX",
            rfq_reference,
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    api_url,
                    auth=(self.account_sid, self.auth_token),
                    data=form_data,
                )

            if res.status_code in (200, 201):
                data = res.json()
                logger.info("Twilio call initiated successfully: CallSid=%s, Status=%s", data.get("sid"), data.get("status"))
                return {
                    "call_sid": data.get("sid"),
                    "status": data.get("status"),
                    "to": data.get("to"),
                    "from": data.get("from"),
                    "direction": data.get("direction"),
                }
            else:
                err_text = res.text
                logger.error("Twilio API error (%d): %s", res.status_code, err_text)
                raise TwilioClientError(
                    res.status_code,
                    f"Twilio API error ({res.status_code}): {err_text}",
                )
        except httpx.RequestError as exc:
            logger.error("Network error contacting Twilio: %s", str(exc))
            raise TwilioClientError(502, f"Failed to connect to Twilio: {str(exc)}") from exc


twilio_voice_client = TwilioVoiceClient()

