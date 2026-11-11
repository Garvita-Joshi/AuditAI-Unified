"""Validated voice data contracts; no inferred commercial terms."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FieldStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    NOT_PROVIDED = "NOT_PROVIDED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"


class QuotationFieldName(str, Enum):
    PRODUCT = "product_or_service"
    QUANTITY = "quantity"
    UNIT_PRICE = "unit_price"
    TOTAL_PRICE = "total_price"
    CURRENCY = "currency"
    SHIPPING = "shipping"
    TAXES = "taxes"
    AVAILABILITY = "availability"
    LEAD_TIME = "delivery_lead_time"
    DELIVERY_DATE = "expected_delivery_date"
    WARRANTY = "warranty"
    PAYMENT_TERMS = "payment_terms"
    REMARKS = "vendor_remarks"
    VALIDITY = "quotation_validity"
    VENDOR_NAME = "vendor_name"
    TRACKING_REFERENCE = "rfq_tracking_reference"


REQUIRED_FIELDS = tuple(field.value for field in QuotationFieldName)
MONEY_FIELDS = {"unit_price", "total_price", "shipping", "taxes"}
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
RecordId = Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]


class QuotationFieldInput(InputModel):
    name: QuotationFieldName
    value: str | None = Field(default=None, max_length=6000)
    original_response: str | None = Field(default=None, max_length=6000)
    status: FieldStatus = FieldStatus.NOT_PROVIDED
    confirmation_note: str | None = Field(default=None, max_length=2000)

    @field_validator("value", mode="before")
    @classmethod
    def exact_values(cls, value):
        if value is None or isinstance(value, str):
            return value
        if type(value) is int or isinstance(value, Decimal):
            return str(value)
        raise ValueError("Use a string for monetary/decimal values; booleans and floating point are not accepted.")

    @model_validator(mode="after")
    def validate_field(self):
        if self.status in (FieldStatus.UNKNOWN, FieldStatus.NOT_PROVIDED):
            if self.value is not None:
                raise ValueError("Unknown and unprovided fields must have a null value.")
            return self
        if not self.value or not self.original_response:
            raise ValueError("A supplied value requires the vendor's original response.")
        if self.status == FieldStatus.CONFIRMED and not self.confirmation_note:
            raise ValueError("Confirmed fields require a note describing the confirmation evidence.")
        name = self.name.value
        if name in MONEY_FIELDS or name == "quantity":
            try:
                number = Decimal(self.value)
            except InvalidOperation:
                raise ValueError("Enter an exact decimal number without currency symbols or separators.")
            places = 4 if name in ("quantity", "unit_price") else 2
            if not number.is_finite() or number < 0 or number >= Decimal("1000000000000"):
                raise ValueError("Numeric values must be finite, nonnegative and below one trillion.")
            if name == "quantity" and number == 0:
                raise ValueError("Quantity must be greater than zero.")
            if number.as_tuple().exponent < -places:
                raise ValueError(f"{name} supports up to {places} decimal places.")
            self.value = format(number, "f")
        elif name == "currency":
            normalized = self.value.upper()
            if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
                raise ValueError("Currency must be a three-letter code such as INR.")
            self.value = normalized
        elif name == "expected_delivery_date":
            try:
                parsed = date.fromisoformat(self.value)
            except ValueError:
                raise ValueError("Delivery dates must use YYYY-MM-DD.")
            if parsed.isoformat() != self.value:
                raise ValueError("Delivery dates must use YYYY-MM-DD.")
        return self


class CallDraftCreate(InputModel):
    request_id: int = Field(gt=0)
    agent_vendor_id: int = Field(gt=0)
    idempotency_key: IdempotencyKey


class CallDraftCancel(InputModel):
    idempotency_key: IdempotencyKey
    reason: str = Field(min_length=3, max_length=2000)


class QuotationCreate(InputModel):
    call_id: RecordId
    idempotency_key: IdempotencyKey
    fields: list[QuotationFieldInput] = Field(default_factory=list, max_length=len(REQUIRED_FIELDS))

    @model_validator(mode="after")
    def unique_fields(self):
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("Each quotation field may appear only once.")
        return self


class QuotationFieldUpdate(InputModel):
    field: QuotationFieldInput
    version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=2000)


class TranscriptMessage(InputModel):
    message_key: str = Field(min_length=1, max_length=150)
    speaker: str = Field(pattern=r"^(assistant|vendor)$")
    message: str = Field(min_length=1, max_length=10000)
    offset_seconds: Decimal | None = Field(default=None, ge=0, le=86400, decimal_places=3)
    spoken_at: datetime | None = None

    @field_validator("spoken_at")
    @classmethod
    def aware_time(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Transcript timestamps must include a timezone.")
        return value


class TranscriptAppend(InputModel):
    idempotency_key: IdempotencyKey
    messages: list[TranscriptMessage] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_messages(self):
        keys = [message.message_key for message in self.messages]
        if len(keys) != len(set(keys)):
            raise ValueError("Message keys must be unique within a batch.")
        return self


class CallbackCreate(InputModel):
    idempotency_key: IdempotencyKey
    callback_at: datetime
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("callback_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Callback time must include a timezone.")
        return value
