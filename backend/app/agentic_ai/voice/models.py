"""Additive voice tables linked to the existing sourcing records."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric,
    String, Text, UniqueConstraint, text,
)

from backend.app.db import Base
from . import DEFAULT_VOICE_PROVIDER


def utcnow():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid4())


class VoiceCall(Base):
    __tablename__ = "procurement_voice_calls"
    __table_args__ = (
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="voice_duration_nonnegative"),
        CheckConstraint("status IN ('prepared','queued','ringing','in_progress','completed','no_answer','busy','failed','cancelled')", name="voice_call_status"),
        Index("voice_one_open_call_per_vendor", "agent_vendor_id", unique=True,
              sqlite_where=text("status IN ('prepared','queued','ringing','in_progress')"),
              postgresql_where=text("status IN ('prepared','queued','ringing','in_progress')")),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    request_id = Column(Integer, ForeignKey("sourcing_requests.id"), nullable=False, index=True)
    agent_vendor_id = Column(Integer, ForeignKey("sourcing_agent_vendors.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    provider = Column(String(30), nullable=False, default=DEFAULT_VOICE_PROVIDER)
    provider_call_id = Column(String(150), unique=True, nullable=True)
    tracking_reference = Column(String(150), nullable=False)
    status = Column(String(30), nullable=False, default="prepared")
    outcome = Column(String(100), nullable=True)
    requirements_snapshot = Column(JSON, nullable=False)
    summary = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Numeric(12, 3), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class VoiceQuotation(Base):
    __tablename__ = "procurement_voice_quotations"
    __table_args__ = (
        CheckConstraint("version > 0", name="voice_quote_positive_version"),
        CheckConstraint("status IN ('incomplete','needs_verification','complete')", name="voice_quote_status"),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    call_id = Column(String(36), ForeignKey("procurement_voice_calls.id"), nullable=False, unique=True)
    request_id = Column(Integer, ForeignKey("sourcing_requests.id"), nullable=False, index=True)
    agent_vendor_id = Column(Integer, ForeignKey("sourcing_agent_vendors.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="incomplete")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class VoiceQuotationField(Base):
    __tablename__ = "procurement_voice_quotation_fields"
    __table_args__ = (
        UniqueConstraint("quotation_id", "name", name="voice_quote_unique_field"),
        CheckConstraint("status IN ('CONFIRMED','UNKNOWN','NOT_PROVIDED','NEEDS_VERIFICATION')", name="voice_field_status"),
        CheckConstraint("(status IN ('UNKNOWN','NOT_PROVIDED') AND value IS NULL) OR (status IN ('CONFIRMED','NEEDS_VERIFICATION') AND value IS NOT NULL)", name="voice_field_value_status"),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    quotation_id = Column(String(36), ForeignKey("procurement_voice_quotations.id"), nullable=False, index=True)
    name = Column(String(60), nullable=False)
    # Store exact decimal strings rather than binary floating point. Schemas
    # normalize money, dates, quantities, and currency before this boundary.
    value = Column(Text, nullable=True)
    original_response = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="NOT_PROVIDED")
    confirmation_note = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class VoiceQuotationAudit(Base):
    __tablename__ = "procurement_voice_quotation_audit"

    id = Column(String(36), primary_key=True, default=new_id)
    quotation_id = Column(String(36), ForeignKey("procurement_voice_quotations.id"), nullable=False, index=True)
    field_name = Column(String(60), nullable=False)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=False)
    source = Column(String(30), nullable=False)
    actor_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class VoiceTranscript(Base):
    __tablename__ = "procurement_voice_transcripts"
    __table_args__ = (
        UniqueConstraint("call_id", "message_key", name="voice_transcript_unique_message"),
        CheckConstraint("offset_seconds IS NULL OR offset_seconds >= 0", name="voice_transcript_nonnegative_offset"),
        CheckConstraint("speaker IN ('assistant','vendor')", name="voice_transcript_speaker"),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    call_id = Column(String(36), ForeignKey("procurement_voice_calls.id"), nullable=False, index=True)
    message_key = Column(String(150), nullable=False)
    speaker = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    offset_seconds = Column(Numeric(12, 3), nullable=True)
    spoken_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class VoiceCallback(Base):
    __tablename__ = "procurement_voice_callbacks"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled','cancelled','fulfilled')", name="voice_callback_status"),
        UniqueConstraint("call_id", "callback_at", name="voice_unique_callback_time"),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    call_id = Column(String(36), ForeignKey("procurement_voice_calls.id"), nullable=False, index=True)
    callback_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="scheduled")
    created_by = Column(Integer, ForeignKey("auth_users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class VoiceOperation(Base):
    """Transaction-scoped idempotency receipts; never a queue for live calls."""
    __tablename__ = "procurement_voice_operations"
    __table_args__ = (
        UniqueConstraint("owner_id", "operation", "key", name="voice_operation_unique_key"),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    owner_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False)
    operation = Column(String(40), nullable=False)
    key = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


VOICE_TABLES = tuple(model.__table__ for model in (
    VoiceCall, VoiceQuotation, VoiceQuotationField, VoiceQuotationAudit,
    VoiceTranscript, VoiceCallback, VoiceOperation,
))
