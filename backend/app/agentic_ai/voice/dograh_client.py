"""Asynchronous client for interacting with the official Dograh Voice AI API.
Implements strict dry-run safeguards, authentication headers, error handling,
and structured payload transmission.
"""
import logging
import os
from typing import Any, Dict, Optional
from uuid import uuid4
import httpx

from backend.app.config import (
    DOGRAH_API_KEY,
    DOGRAH_API_URL,
    DOGRAH_DRY_RUN,
    DOGRAH_TEST_API_URL,
    DOGRAH_TIMEOUT_SECONDS,
    DOGRAH_TRIGGER_PATH,
)
from backend.app.agentic_ai.voice.dograh_schemas import (
    DograhTriggerRequest,
    DograhTriggerResponse,
)

logger = logging.getLogger("auditai.voice.dograh")


class DograhClientError(Exception):
    """Encapsulates Dograh API client exceptions with status codes."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DograhClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        test_api_url: Optional[str] = None,
        trigger_path: Optional[str] = None,
        dry_run: Optional[bool] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self._api_key = api_key
        self.api_url = (api_url or DOGRAH_API_URL).rstrip("/")
        self.test_api_url = (test_api_url or DOGRAH_TEST_API_URL).rstrip("/")
        self._trigger_path = trigger_path
        self._dry_run = dry_run
        self.timeout_seconds = timeout_seconds or DOGRAH_TIMEOUT_SECONDS

    @property
    def api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        return os.getenv("DOGRAH_API_KEY") or DOGRAH_API_KEY or ""

    @api_key.setter
    def api_key(self, value: Optional[str]):
        self._api_key = value

    @property
    def trigger_path(self) -> str:
        if self._trigger_path is not None:
            return self._trigger_path
        return os.getenv("DOGRAH_TRIGGER_PATH") or DOGRAH_TRIGGER_PATH or ""

    @trigger_path.setter
    def trigger_path(self, value: Optional[str]):
        self._trigger_path = value

    @property
    def dry_run(self) -> bool:
        if self._dry_run is not None:
            return self._dry_run
        env_val = os.getenv("DOGRAH_DRY_RUN")
        if env_val is not None:
            return env_val.lower() in ("true", "1", "yes")
        return DOGRAH_DRY_RUN

    def get_trigger_url(self, test_mode: bool = False) -> str:
        """Derive the exact trigger URL according to Dograh documentation.
        Production: https://api.dograh.com/api/v1/public/agent/<trigger_path>
        Test:       https://api.dograh.com/api/v1/public/agent/test/<trigger_path>
        """
        base = self.test_api_url if test_mode else self.api_url
        if not self.trigger_path:
            raise DograhClientError(500, "DOGRAH_TRIGGER_PATH is not configured.")
        return f"{base}/{self.trigger_path}"

    async def trigger_call(
        self,
        request: DograhTriggerRequest,
        test_mode: bool = False,
        call_id: Optional[str] = None,
    ) -> DograhTriggerResponse:
        """Initiate an outbound voice call via Dograh API Trigger.
        In dry-run mode (default), prepares and validates the payload locally
        WITHOUT initiating any telephony session or dialing.
        """
        payload_dict = request.model_dump()

        # ── 1. SAFE TESTING (DRY-RUN) MODE ──
        # Checked strictly BEFORE any external network connection or live credentials check
        if self.dry_run:
            base = self.test_api_url if test_mode else self.api_url
            simulated_endpoint = f"{base}/{self.trigger_path or 'fe74624e-3928-482b-821e-9be6416df7c8'}"
            simulated_run_id = f"sim_dgr_{uuid4().hex[:12]}"
            logger.info(
                "Dograh dry-run mode active. Simulated call for ref=%s to phone=%s (Zero network dial)",
                request.initial_context.rfq_reference,
                request.phone_number[:6] + "XXXX",
            )
            return DograhTriggerResponse(
                status="dry_run_success",
                workflow_run_id=simulated_run_id,
                call_id=call_id,
                tracking_reference=request.initial_context.rfq_reference,
                phone_number=request.phone_number,
                message="Dry-run simulation mode active: Payload validated, zero telephony sessions or dials initiated.",
                dry_run=True,
                endpoint_used=simulated_endpoint,
                prepared_payload=payload_dict,
            )

        # ── 2. LIVE PRODUCTION CALL MODE ──
        target_url = self.get_trigger_url(test_mode=test_mode)

        if not self.api_key:
            raise DograhClientError(
                401,
                "DOGRAH_API_KEY environment variable is missing. Cannot make live Dograh API calls.",
            )

        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "AuditAI-Autonomous-Procurement-Agent/1.0",
        }

        logger.info(
            "Dispatching outbound Dograh call trigger for ref=%s to endpoint=%s",
            request.initial_context.rfq_reference,
            target_url,
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(target_url, json=payload_dict, headers=headers)

            if response.status_code in (200, 201, 202):
                data = response.json() if response.content else {}
                # Extract workflow run identifier (Dograh returns id or run_id or workflow_run_id)
                workflow_run_id = str(
                    data.get("workflow_run_id")
                    or data.get("run_id")
                    or data.get("id")
                    or data.get("call_id")
                    or f"dgr_{uuid4().hex[:12]}"
                )
                return DograhTriggerResponse(
                    status="initiated",
                    workflow_run_id=workflow_run_id,
                    call_id=call_id,
                    tracking_reference=request.initial_context.rfq_reference,
                    phone_number=request.phone_number,
                    message="Outbound call initiated successfully via Dograh Voice AI.",
                    dry_run=False,
                    endpoint_used=target_url,
                    prepared_payload=None,
                )
            elif response.status_code == 401:
                raise DograhClientError(401, "Dograh authentication failed: Invalid or expired X-API-Key.")
            elif response.status_code == 404:
                raise DograhClientError(404, f"Dograh trigger endpoint not found: Check DOGRAH_TRIGGER_PATH ({target_url}).")
            elif response.status_code == 422:
                raise DograhClientError(422, f"Dograh rejected payload with validation error: {response.text}")
            else:
                raise DograhClientError(
                    response.status_code,
                    f"Dograh API returned unexpected status {response.status_code}: {response.text}",
                )

        except httpx.TimeoutException as exc:
            logger.error("Dograh API request timed out after %ds", self.timeout_seconds)
            raise DograhClientError(504, f"Dograh API timed out after {self.timeout_seconds}s.") from exc
        except httpx.RequestError as exc:
            logger.error("Dograh network connectivity error: %s", str(exc))
            raise DograhClientError(502, f"Failed to connect to Dograh API: {str(exc)}") from exc


# Default global client instance
dograh_client = DograhClient()
