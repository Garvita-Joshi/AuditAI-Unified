from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from backend.app.db import Base


class AgentRun(Base):
    __tablename__ = 'sourcing_agent_runs'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('sourcing_requests.id'), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey('auth_users.id'), nullable=False, index=True)
    status = Column(String(40), nullable=False, default='rfqs_queued')
    summary = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentVendor(Base):
    __tablename__ = 'sourcing_agent_vendors'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('sourcing_agent_runs.id'), nullable=False, index=True)
    vendor_id = Column(String(100), nullable=False)
    offer_id = Column(String(150), nullable=False)
    vendor_name = Column(String(200), nullable=False)
    vendor_email = Column(String(320), nullable=False)
    synthetic = Column(Integer, nullable=False, default=0)
    rank = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    reasons = Column(JSON, nullable=False, default=list)
    offer = Column(JSON, nullable=False, default=dict)
    rfq_subject = Column(String(500), nullable=False)
    rfq_body = Column(Text, nullable=False)
    rfq_approved = Column(Boolean, nullable=False, default=False)
    status = Column(String(40), nullable=False, default='draft_ready')
    sent_at = Column(DateTime, nullable=True)
    reply_at = Column(DateTime, nullable=True)
    reply_text = Column(Text, nullable=True)


class AgentActivity(Base):
    __tablename__ = 'sourcing_agent_activities'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('sourcing_agent_runs.id'), nullable=False, index=True)
    request_id = Column(Integer, ForeignKey('sourcing_requests.id'), nullable=False, index=True)
    actor = Column(String(100), nullable=False)
    event = Column(String(100), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
