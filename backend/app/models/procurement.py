"""Separate procurement records; approved terms are snapshots, not live request data."""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from backend.app.db import Base
from backend.app.procurement.request_records import RequestArchive, RequestRecordEvent  # register tables for Base.metadata


class PurchaseRequest(Base):
    __tablename__ = "procurement_requests"
    id = Column(Integer, primary_key=True)
    requester_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    budget_limit = Column(Numeric(15, 2), nullable=False)
    terms = Column(JSON, nullable=False)
    status = Column(String(30), nullable=False, default="submitted")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PurchaseOrder(Base):
    __tablename__ = "procurement_orders"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("procurement_requests.id"), nullable=False, unique=True)
    approved_by = Column(Integer, ForeignKey("auth_users.id"), nullable=False)
    terms = Column(JSON, nullable=False)
    total = Column(Numeric(15, 2), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SupplierInvoice(Base):
    __tablename__ = "procurement_invoices"
    __table_args__ = (UniqueConstraint("supplier_id", "invoice_number", name="uq_procurement_supplier_invoice"),)
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("procurement_orders.id"), nullable=False, index=True)
    supplier_id = Column(String(100), nullable=False)
    invoice_number = Column(String(100), nullable=False)
    terms = Column(JSON, nullable=False)
    stated_total = Column(Numeric(15, 2), nullable=False)
    status = Column(String(30), nullable=False)
    differences = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProcurementContext(Base):
    __tablename__ = "procurement_contexts"
    request_id = Column(Integer, ForeignKey("procurement_requests.id"), primary_key=True)
    details = Column(JSON, nullable=False)
    workflow = Column(JSON, nullable=False)


class ApprovalStep(Base):
    __tablename__ = "procurement_approval_steps"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("procurement_requests.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    step_order = Column(Integer, nullable=False)
    role = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="not_started")
    assignee_id = Column(Integer, ForeignKey("auth_users.id"), nullable=True)
    due_date = Column(DateTime, nullable=False)
    sla_days = Column(Integer, nullable=False, default=3)
    started_at = Column(DateTime, nullable=True)
    decision = Column(JSON, nullable=False, default=dict)


class ApprovalSubtask(Base):
    __tablename__ = "procurement_approval_subtasks"
    id = Column(Integer, primary_key=True)
    step_id = Column(Integer, ForeignKey("procurement_approval_steps.id"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    instructions = Column(String(1000), nullable=False, default="")
    assignee_id = Column(Integer, ForeignKey("auth_users.id"), nullable=True)
    status = Column(String(30), nullable=False, default="pending")
    required = Column(Boolean, nullable=False, default=True)
    actions = Column(JSON, nullable=False, default=list)


class ProcurementNotification(Base):
    __tablename__ = "procurement_notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    request_id = Column(Integer, ForeignKey("procurement_requests.id"), nullable=False, index=True)
    step_id = Column(Integer, ForeignKey("procurement_approval_steps.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    message = Column(String(500), nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProcurementEvent(Base):
    __tablename__ = "procurement_events"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("procurement_requests.id"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProcurementDocument(Base):
    __tablename__ = "procurement_documents"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("procurement_requests.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    storage_key = Column(String(100), nullable=False)
    kind = Column(String(30), nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class InvoiceRevision(Base):
    __tablename__ = "procurement_invoice_revisions"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("procurement_invoices.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    assessment = Column(JSON, nullable=False)
    actor_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProcurementPayment(Base):
    __tablename__ = "procurement_payments"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("procurement_invoices.id"), nullable=False, unique=True)
    create_key = Column(String(36), nullable=False, unique=True)
    capture_key = Column(String(36), nullable=False, unique=True)
    provider_order_id = Column(String(100), nullable=True, unique=True)
    status = Column(String(40), nullable=False, default="created")
    provider_result = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
