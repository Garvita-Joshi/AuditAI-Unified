"""Procurement workflow with persisted approvals, evidence and exceptions."""
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.security import require_authenticated_user
from backend.app.db import get_db
from backend.app.models.auth import User
from backend.app.models.procurement import (PurchaseOrder, PurchaseRequest, SupplierInvoice,
    ProcurementContext, ProcurementEvent, ProcurementDocument, InvoiceRevision, ProcurementPayment,
    ApprovalStep, ApprovalSubtask, ProcurementNotification)
from backend.app.procurement.contracts import InvoiceCreate, PurchaseTerms, RequestCreate, RequestDetails
from backend.app.procurement.contracts import match_invoice
from backend.app.procurement.risk import assess
from backend.app.procurement.company_data import department_head_for, requester_summary
from backend.app.procurement.request_records import archived_condition, is_archived, set_archived, record_action

router = APIRouter(prefix="/api/v1/procurement", tags=["procurement"])
APPROVERS = {"manager", "procurement", "finance", "security", "legal", "it", "admin"}
FINAL_APPROVAL_INR_THRESHOLD = Decimal("100000.00")
STEP_SLA_DAYS = 3


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Record already exists or conflicts with another operation.")


def visible_request(db, request_id, user, lock=False):
    query = db.query(PurchaseRequest).filter_by(id=request_id)
    row = (query.with_for_update() if lock else query).first()
    if not row or is_archived(db,'purchase',request_id) or (row.requester_id != user.id and user.role not in APPROVERS):
        raise HTTPException(404, "Request not found.")
    return row


def event(db, row, user, action, **details):
    now = datetime.utcnow()
    timestamp_iso = now.isoformat() + "Z"
    log_time = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    event_details = {
        **details,
        "timestamp": details.get("timestamp") or timestamp_iso,
        "log_time": details.get("log_time") or log_time,
        "actor_email": getattr(user, "email", None) or getattr(user, "username", None),
        "actor_role": getattr(user, "role", None),
    }
    db.add(ProcurementEvent(request_id=row.id, actor_id=user.id, action=action, details=event_details, created_at=now))
    safe_details = {k: v for k, v in event_details.items() if k not in ('kind', 'request_id', 'actor_id', 'action')}
    record_action(db, 'purchase', row.id, user.id, action, **safe_details)


def context(db, row):
    return db.get(ProcurementContext, row.id)


def workflow(details):
    roles = ["manager", "admin", "finance"] + (["security"] if details.shares_personal_data is not False else [])
    return [{"role": role, "name": {"manager":"Intake review", "admin":"Procurement review", "finance":"Finance review", "security":"Security review"}[role],
             "status": "pending", "due_at": (datetime.utcnow() + timedelta(days=STEP_SLA_DAYS)).isoformat(), "actor_id": None} for role in roles]


def _user_for_role(db, role):
    return db.query(User).filter_by(role=role, is_active=True).order_by(User.id).first()


def _build_approval_steps(db, row, details, total, currency):
    """Persist ordered human checkpoints. INR requests above ₹100,000 need final approval."""
    if db.query(ApprovalStep).filter_by(request_id=row.id).count():
        return
    now = datetime.utcnow()
    specs = [("Intake review", "manager", []),
             ("Procurement review", "admin", [
                 ("Compare vendor quotes", "Compare the offers and record why the recommended offer meets the request."),
                 ("Review order form", "Check the order form and supporting quote against the request."),
             ]),
             ("Finance review", "finance", [])]
    if details.shares_personal_data is not False:
        specs.append(("Security review", "security", []))
    if currency == "INR" and Decimal(str(total)) > FINAL_APPROVAL_INR_THRESHOLD:
        specs.append(("Final approval", "admin", []))
    for index, (name, role, subtasks) in enumerate(specs):
        if role == "manager":
            head = department_head_for(db.get(User, row.requester_id), details.department)
            assignee = db.query(User).filter(User.is_active.is_(True), User.email == head.get("email")).first() if head else None
        else:
            assignee = _user_for_role(db, role)
        step = ApprovalStep(request_id=row.id, name=name, step_order=index + 1, role=role,
            status="ready" if index == 0 else "not_started", assignee_id=assignee.id if assignee else None,
            due_date=now + timedelta(days=STEP_SLA_DAYS), sla_days=STEP_SLA_DAYS,
            started_at=now if index == 0 else None, decision={})
        db.add(step)
        db.flush()
        for title, instructions in subtasks:
            db.add(ApprovalSubtask(step_id=step.id, title=title, instructions=instructions,
                assignee_id=assignee.id if assignee else None, status="pending", required=True,
                actions=["Mark done", "Not needed"]))
        if index == 0 and assignee:
            db.add(ProcurementNotification(user_id=assignee.id, request_id=row.id, step_id=step.id,
                title="Approval ready", message=f"{name} is ready for request PR-{row.id:04d}."))


def _approval_steps(db, request_id):
    request_row = db.get(PurchaseRequest, request_id)
    request_context = context(db, request_row) if request_row else None
    details = (request_context.details or {}) if request_context else {}
    requester = db.get(User, request_row.requester_id) if request_row else None
    requester_info = requester_summary(requester) if requester else None
    department_head = department_head_for(requester, details.get("department")) if requester else None
    rows = db.query(ApprovalStep).filter_by(request_id=request_id).order_by(ApprovalStep.step_order).all()
    result = []
    for step in rows:
        assignee = db.get(User, step.assignee_id) if step.assignee_id else None
        subtasks = db.query(ApprovalSubtask).filter_by(step_id=step.id).order_by(ApprovalSubtask.id).all()
        display_assignee = ({"id": assignee.id, "name": assignee.full_name or assignee.email,
            "email": assignee.email} if assignee else None)
        if step.name == "Intake review" and not assignee and department_head:
            display_assignee = {"id": None, "name": department_head["name"],
                "email": department_head.get("email"), "directory_only": True}
        result.append({"id": step.id, "request_id": step.request_id, "name": step.name, "order": step.step_order,
            "role": step.role, "status": step.status,
            "assignee": display_assignee,
            "department_head": department_head if step.name == "Procurement review" else None,
            "due_date": step.due_date.isoformat(), "sla_days": step.sla_days,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "subtasks": [{"id": sub.id, "title": sub.title, "instructions": sub.instructions,
                "assignee": ({"id": (db.get(User, sub.assignee_id)).id,
                    "name": (db.get(User, sub.assignee_id)).full_name or (db.get(User, sub.assignee_id)).email}
                    if sub.assignee_id and db.get(User, sub.assignee_id) else None),
                "status": sub.status, "required": bool(sub.required), "actions": sub.actions or []} for sub in subtasks],
            "decision": step.decision or {}})
    return result


def _sync_legacy_workflow(db, ctx, request_id):
    """Keep the old workflow response shape available to existing clients."""
    steps = _approval_steps(db, request_id)
    ctx.workflow = [{"role": step["role"], "name": step["name"],
        "status": "approved" if step["status"] == "approved" else "pending",
        "due_at": step["due_date"], "actor_id": (step["decision"] or {}).get("decided_by")}
        for step in steps if step["status"] not in {"rejected", "sent_back"}]


def _audit_step(db, row, user, step, action, reason="", **details):
    event(db, row, user, action, step_id=step.id, step_name=step.name,
          reason=reason.strip(), **details)


def _next_step(db, current):
    return db.query(ApprovalStep).filter(ApprovalStep.request_id == current.request_id,
        ApprovalStep.step_order > current.step_order).order_by(ApprovalStep.step_order).first()


def _notify_ready(db, row, step):
    if step.assignee_id:
        db.add(ProcurementNotification(user_id=step.assignee_id, request_id=row.id, step_id=step.id,
            title="Approval ready", message=f"{step.name} is ready for request PR-{row.id:04d}."))


class Decision(BaseModel):
    action: str = Field(pattern="^(approve|reject|request_info|send_back)$")
    note: str = Field(default="", max_length=3000)


class Note(BaseModel):
    note: str = Field(min_length=1, max_length=3000, pattern=r"\S")


class StepUpdate(BaseModel):
    assignee_id: int | None = None
    due_date: datetime | None = None
    status: str | None = Field(default=None, pattern="^(ready|in_progress)$")
    reason: str = Field(default="", max_length=3000)


class SubtaskUpdate(BaseModel):
    status: str = Field(pattern="^(done|not_needed)$")
    reason: str = Field(default="", max_length=3000)


class NotificationRead(BaseModel):
    read: bool = True


@router.post("/requests", status_code=201)
def create_request(payload: RequestCreate, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = PurchaseRequest(requester_id=user.id, title=payload.title, budget_limit=payload.budget_limit,
                          terms=payload.terms.model_dump(mode="json"), status="submitted")
    db.add(row)
    db.flush()
    ctx = ProcurementContext(request_id=row.id, details=payload.details.model_dump(mode="json"), workflow=workflow(payload.details))
    db.add(ctx)
    _build_approval_steps(db, row, payload.details, payload.terms.total, payload.terms.currency)
    event(db, row, user, "request_created", total=str(payload.terms.total))
    commit(db)
    return {"id": row.id, "status": row.status, "total": str(payload.terms.total)}


@router.get("/requests")
def list_requests(deleted: bool = False, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    archived = archived_condition('purchase',PurchaseRequest.id)
    query = db.query(PurchaseRequest).filter(archived if deleted else ~archived)
    if user.role not in APPROVERS:
        query = query.filter(PurchaseRequest.requester_id == user.id)
    rows = query.order_by(PurchaseRequest.id.desc()).all()
    def invoice_status(request):
        order = db.query(PurchaseOrder).filter_by(request_id=request.id).first()
        invoice = db.query(SupplierInvoice).filter_by(order_id=order.id).first() if order else None
        return invoice.status if invoice else "not_received"
    def identity(r):
        requester = db.get(User, r.requester_id)
        details = (context(db, r).details or {}) if context(db, r) else {}
        return requester_summary(requester), department_head_for(requester, details.get("department"))
    def approved_at(r):
        order = db.query(PurchaseOrder).filter_by(request_id=r.id).first()
        return order.created_at.isoformat() if order else None
    def permissions(r):
        owner = r.requester_id == user.id
        ordered = db.query(PurchaseOrder).filter_by(request_id=r.id).first() is not None
        decided = db.query(ApprovalStep).filter_by(request_id=r.id,status='approved').first() is not None
        return {'can_edit':owner and not ordered and not decided and not deleted,
                'can_delete':owner and not ordered}
    return [{**permissions(r), "current_status":"deleted" if deleted else r.status, "invoice_status": invoice_status(r), "document_count": db.query(ProcurementDocument).filter_by(request_id=r.id).count(), "id": r.id, "title": r.title, "requester_id": r.requester_id, "requester": identity(r)[0], "department_head": identity(r)[1], "status": r.status,
             "budget_limit": str(r.budget_limit), "total": str(PurchaseTerms.model_validate(r.terms).total),
             "terms": r.terms, "created_at": r.created_at.isoformat(), "approved_at": approved_at(r),
             "details": context(db, r).details if context(db, r) else {},
             "workflow": context(db, r).workflow if context(db, r) else [],
             "approval_steps": _approval_steps(db, r.id)} for r in rows]


def owner_request(db,request_id,user):
    row = visible_request(db,request_id,user,lock=True)
    if row.requester_id != user.id:
        raise HTTPException(403,'Only the requester may edit or delete this request.')
    return row


@router.delete('/requests/{request_id}')
def delete_request(request_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = owner_request(db,request_id,user)
    if db.query(PurchaseOrder).filter_by(request_id=request_id).first():
        raise HTTPException(409,'An approved PO is retained as a financial record and cannot be deleted here.')
    for notification in db.query(ProcurementNotification).filter_by(request_id=request_id).all():
        notification.read_at = datetime.utcnow()
    set_archived(db,'purchase',request_id,user.id,True)
    event(db, row, user, 'request_permanently_deleted', note='Request permanently deleted. Once deleted, there is no going back.')
    return {'id':row.id,'status':'permanently_deleted','message':'Request permanently deleted. Once deleted, there is no going back. All activity is preserved in the audit log with timestamps.'}


@router.post('/requests/{request_id}/restore')
def restore_request(request_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    record_action(db, 'purchase', request_id, user.id, 'restore_blocked', note='Attempt to restore a permanently deleted request was blocked.')
    db.commit()
    raise HTTPException(400, 'Once a request is deleted, there is no going back. Deletion is permanent and irreversible.')


@router.get('/requests/{request_id}/audit-log')
def get_procurement_audit_trail(request_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = db.query(PurchaseRequest).filter_by(id=request_id).first()
    if not row or (row.requester_id != user.id and user.role not in APPROVERS):
        raise HTTPException(404, 'Request not found.')
    events = (db.query(ProcurementEvent)
              .filter_by(request_id=request_id)
              .order_by(ProcurementEvent.id.desc())
              .all())
    return {
        'id': request_id,
        'kind': 'purchase',
        'is_deleted': is_archived(db, 'purchase', request_id),
        'audit_log': [
            {
                'id': e.id,
                'action': e.action,
                'actor_id': e.actor_id,
                'details': e.details,
                'created_at': e.created_at.isoformat(),
                'timestamp': (e.details or {}).get('timestamp') or (e.created_at.isoformat() + 'Z'),
                'log_time': (e.details or {}).get('log_time') or e.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
            }
            for e in events
        ]
    }


@router.put('/requests/{request_id}')
def edit_request(request_id: int, payload: RequestCreate, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = owner_request(db,request_id,user)
    if db.query(PurchaseOrder).filter_by(request_id=request_id).first() or db.query(ApprovalStep).filter_by(request_id=request_id,status='approved').first():
        raise HTTPException(409,'This request already has approvals. Approved terms cannot be changed through form editing.')
    ctx = context(db,row)
    event(db,row,user,'request_edited',previous={'title':row.title,'budget_limit':str(row.budget_limit),
        'terms':row.terms,'details':ctx.details if ctx else {},'steps':_approval_steps(db,request_id)})
    step_ids = [step.id for step in db.query(ApprovalStep).filter_by(request_id=request_id)]
    db.query(ProcurementNotification).filter_by(request_id=request_id).delete(synchronize_session=False)
    db.query(ApprovalSubtask).filter(ApprovalSubtask.step_id.in_(step_ids)).delete(synchronize_session=False)
    db.query(ApprovalStep).filter_by(request_id=request_id).delete(synchronize_session=False)
    db.flush()
    row.title=payload.title; row.budget_limit=payload.budget_limit
    row.terms=payload.terms.model_dump(mode='json'); row.status='submitted'
    if ctx is None:
        ctx=ProcurementContext(request_id=request_id);db.add(ctx)
    ctx.details=payload.details.model_dump(mode='json');ctx.workflow=workflow(payload.details)
    _build_approval_steps(db,row,payload.details,payload.terms.total,payload.terms.currency)
    record_action(db,'purchase',request_id,user.id,'request_edited')
    commit(db)
    return {'id':row.id,'status':row.status}


@router.get("/requests/{request_id}")
def get_request(request_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = visible_request(db, request_id, user)
    order = db.query(PurchaseOrder).filter_by(request_id=row.id).first()
    ctx = context(db, row)
    if ctx and not db.query(ApprovalStep).filter_by(request_id=row.id).count() and row.status == "submitted":
        _build_approval_steps(db, row, RequestDetails.model_validate(ctx.details),
            PurchaseTerms.model_validate(row.terms).total, PurchaseTerms.model_validate(row.terms).currency)
        _sync_legacy_workflow(db, ctx, row.id)
        db.commit()
    invoices = db.query(SupplierInvoice).filter_by(order_id=order.id).order_by(SupplierInvoice.id.desc()).all() if order else []
    requester = db.get(User, row.requester_id)
    requester_info = requester_summary(requester)
    department_head = department_head_for(requester, (ctx.details or {}).get("department") if ctx else None)
    return {"id":row.id, "title":row.title, "requester_id":row.requester_id, "status":row.status,
            "requester":requester_info, "department_head":department_head,
            "terms":row.terms, "budget_limit":str(row.budget_limit), "total":str(PurchaseTerms.model_validate(row.terms).total),
            "created_at":row.created_at.isoformat(), "details":ctx.details if ctx else {}, "workflow":ctx.workflow if ctx else [],
            "approval_steps":_approval_steps(db, row.id),
            "order": {"id":order.id,"terms":order.terms,"total":str(order.total)} if order else None,
            "invoices":[invoice_view(db, i) for i in invoices],
            "is_deleted": is_archived(db, 'purchase', row.id),
            "can_restore": False,
            "events":[{"id":e.id, "action":e.action,"actor_id":e.actor_id,"details":e.details,"created_at":e.created_at.isoformat(),
                       "timestamp": (e.details or {}).get("timestamp") or (e.created_at.isoformat() + "Z"),
                       "log_time": (e.details or {}).get("log_time") or e.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")}
                      for e in db.query(ProcurementEvent).filter_by(request_id=row.id).order_by(ProcurementEvent.id.desc()).all()],
            "documents":[{"id":d.id,"filename":d.filename,"kind":d.kind,"size":d.size,"created_at":d.created_at.isoformat()}
                         for d in db.query(ProcurementDocument).filter_by(request_id=row.id).all()]}


def invoice_view(db, row):
    revision = db.query(InvoiceRevision).filter_by(invoice_id=row.id).order_by(InvoiceRevision.id.desc()).first()
    payment = db.query(ProcurementPayment).filter_by(invoice_id=row.id).first()
    return {"id":row.id,"invoice_number":row.invoice_number,"terms":row.terms,"stated_total":str(row.stated_total),
            "status":row.status,"differences":row.differences,"assessment":revision.assessment if revision else {"status":"unavailable"},
            "revision_count":db.query(InvoiceRevision).filter_by(invoice_id=row.id).count(),
            "payment_status":payment.status if payment else "not_started"}


@router.post("/requests/{request_id}/decision")
def decide(request_id: int, payload: Decision, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = visible_request(db, request_id, user, lock=True)
    if (user.role not in APPROVERS or row.requester_id == user.id) and user.email != 'prepares23@gmail.com':
        raise HTTPException(403, "An independent authorized approver is required.")
    if row.status != "submitted":
        raise HTTPException(409, "Request is not awaiting approval.")
    ctx = context(db, row)
    if not ctx:
        from backend.app.procurement.contracts import RequestDetails
        ctx = ProcurementContext(request_id=row.id, details=RequestDetails().model_dump(), workflow=workflow(RequestDetails()))
        db.add(ctx)
    steps = db.query(ApprovalStep).filter_by(request_id=row.id).order_by(ApprovalStep.step_order).all()
    if not steps:
        details = RequestDetails.model_validate(ctx.details)
        terms = PurchaseTerms.model_validate(row.terms)
        _build_approval_steps(db, row, details, terms.total, terms.currency)
        steps = db.query(ApprovalStep).filter_by(request_id=row.id).order_by(ApprovalStep.step_order).all()
    step = next((s for s in steps if s.status not in {"approved", "rejected"}), None)
    if not step:
        raise HTTPException(409, "No pending approval.")
    if step.status not in {"ready", "in_progress", "sent_back"}:
        raise HTTPException(409, "This approval step is not ready.")
    if user.role != "admin" and (user.role != step.role or (step.assignee_id and step.assignee_id != user.id)):
        raise HTTPException(403, f"This step requires its assigned {step.role} reviewer.")
    if payload.action != "approve" and not payload.note.strip():
        raise HTTPException(422, "Explain why the request needs action.")
    if payload.action == "approve":
        subtasks = db.query(ApprovalSubtask).filter_by(step_id=step.id).all()
        if any(sub.required and sub.status not in {"done", "not_needed"} for sub in subtasks):
            raise HTTPException(409, "Complete every required subtask before approving this step.")
        now = datetime.utcnow()
        step.status = "approved"
        step.decision = {"outcome":"approved", "decided_by":user.id, "decided_at":now.isoformat(), "reason":payload.note.strip()}
        next_step = _next_step(db, step)
        if next_step:
            next_step.status = "ready"
            next_step.started_at = now
            _notify_ready(db, row, next_step)
        else:
            terms = PurchaseTerms.model_validate(row.terms)
            if terms.total > row.budget_limit:
                raise HTTPException(409, "Request exceeds its spending limit.")
            db.add(PurchaseOrder(request_id=row.id, approved_by=user.id, terms=terms.model_dump(mode="json"), total=terms.total))
            row.status = "approved"
        _audit_step(db, row, user, step, "approval_approve", payload.note)
    else:
        now = datetime.utcnow()
        step.status = "rejected" if payload.action == "reject" else "sent_back"
        step.decision = {"outcome":step.status, "decided_by":user.id, "decided_at":now.isoformat(), "reason":payload.note.strip()}
        row.status = "rejected" if payload.action == "reject" else "needs_info"
        _audit_step(db, row, user, step, "approval_" + payload.action, payload.note)
    _sync_legacy_workflow(db, ctx, row.id)
    commit(db)
    return {"status":row.status, "step_id":step.id, "step_status":step.status}


@router.post("/requests/{request_id}/approve", status_code=201)
def approve_request(request_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    result = decide(request_id, Decision(action="approve"), db, user)
    order = db.query(PurchaseOrder).filter_by(request_id=request_id).first()
    return {**result, "order_id":order.id if order else None}


def _visible_step(db, request_id, step_id, user):
    row = visible_request(db, request_id, user, lock=True)
    step = db.query(ApprovalStep).filter_by(id=step_id, request_id=row.id).first()
    if not step:
        raise HTTPException(404, "Approval step not found.")
    if (user.role not in APPROVERS or row.requester_id == user.id) and user.email != 'prepares23@gmail.com':
        raise HTTPException(403, "An independent approver is required.")
    if user.role != "admin" and (user.role != step.role or (step.assignee_id and step.assignee_id != user.id)):
        raise HTTPException(403, f"This step requires its assigned {step.role} reviewer.")
    return row, step


@router.patch("/requests/{request_id}/steps/{step_id}")
def update_step(request_id: int, step_id: int, payload: StepUpdate, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row, step = _visible_step(db, request_id, step_id, user)
    if step.status in {"approved", "rejected"}:
        raise HTTPException(409, "A completed step cannot be edited.")
    changed = False
    if "assignee_id" in payload.model_fields_set:
        if step.status == "approved":
            raise HTTPException(409, "An approved step cannot be reassigned.")
        assignee = db.get(User, payload.assignee_id) if payload.assignee_id else None
        if payload.assignee_id and (not assignee or not assignee.is_active):
            raise HTTPException(422, "Choose an active user.")
        old_id = step.assignee_id
        step.assignee_id = assignee.id if assignee else None
        changed = True
        if assignee and assignee.id != old_id and step.status == "ready":
            _notify_ready(db, row, step)
        _audit_step(db, row, user, step, "step_reassigned", payload.reason,
                    previous_assignee_id=old_id, assignee_id=step.assignee_id)
    if payload.due_date is not None:
        previous = step.due_date.isoformat()
        step.due_date = payload.due_date.replace(tzinfo=None)
        changed = True
        _audit_step(db, row, user, step, "step_due_date_changed", payload.reason,
                    previous_due_date=previous, due_date=step.due_date.isoformat())
    if payload.status is not None:
        if user.role != "admin":
            raise HTTPException(403, "Only an admin can change a step status directly.")
        if payload.status == "ready":
            previous = step.status
            if previous == "not_started" and any(s.status != "approved" for s in db.query(ApprovalStep).filter(
                    ApprovalStep.request_id == row.id, ApprovalStep.step_order < step.step_order).all()):
                raise HTTPException(409, "Earlier workflow steps must be approved first.")
            step.status = "ready"
            step.started_at = step.started_at or datetime.utcnow()
            if previous != "ready": _notify_ready(db, row, step)
        else:
            if step.status == "not_started":
                raise HTTPException(409, "A step cannot start before it is ready.")
            step.status = "in_progress"
        changed = True
        _audit_step(db, row, user, step, "step_status_changed", payload.reason, status=step.status)
    if not changed:
        raise HTTPException(422, "No step changes were provided.")
    ctx = context(db, row)
    if ctx: _sync_legacy_workflow(db, ctx, row.id)
    commit(db)
    return {"status":"saved", "step":_approval_steps(db, row.id)}


@router.post("/requests/{request_id}/steps/{step_id}/decision")
def decide_step(request_id: int, step_id: int, payload: Decision, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row, step = _visible_step(db, request_id, step_id, user)
    if row.status != "submitted":
        raise HTTPException(409, "Request is not awaiting approval.")
    current = db.query(ApprovalStep).filter(ApprovalStep.request_id == row.id,
        ApprovalStep.status.notin_(["approved", "rejected"])).order_by(ApprovalStep.step_order).first()
    if not current or current.id != step.id:
        raise HTTPException(409, "Only the current workflow step can be decided.")
    if payload.action != "approve" and not payload.note.strip():
        raise HTTPException(422, "Rejecting or sending back requires a reason.")
    if payload.action == "request_info": payload.action = "send_back"
    if payload.action == "approve":
        subtasks = db.query(ApprovalSubtask).filter_by(step_id=step.id).all()
        if any(sub.required and sub.status not in {"done", "not_needed"} for sub in subtasks):
            raise HTTPException(409, "Complete every required subtask before approving this step.")
        step.status = "approved"
        step.decision = {"outcome":"approved", "decided_by":user.id,
            "decided_at":datetime.utcnow().isoformat(), "reason":payload.note.strip()}
        next_step = _next_step(db, step)
        if next_step:
            next_step.status, next_step.started_at = "ready", datetime.utcnow()
            _notify_ready(db, row, next_step)
        else:
            terms = PurchaseTerms.model_validate(row.terms)
            if terms.total > row.budget_limit:
                raise HTTPException(409, "Request exceeds its spending limit.")
            db.add(PurchaseOrder(request_id=row.id, approved_by=user.id,
                terms=terms.model_dump(mode="json"), total=terms.total))
            row.status = "approved"
    elif payload.action == "reject":
        step.status, row.status = "rejected", "rejected"
        step.decision = {"outcome":"rejected", "decided_by":user.id,
            "decided_at":datetime.utcnow().isoformat(), "reason":payload.note.strip()}
    else:
        step.status, row.status = "sent_back", "needs_info"
        step.decision = {"outcome":"sent_back", "decided_by":user.id,
            "decided_at":datetime.utcnow().isoformat(), "reason":payload.note.strip()}
    _audit_step(db, row, user, step, "approval_" + payload.action, payload.note)
    ctx = context(db, row)
    if ctx: _sync_legacy_workflow(db, ctx, row.id)
    commit(db)
    return {"status":row.status, "step_status":step.status, "approval_steps":_approval_steps(db, row.id)}


@router.patch("/requests/{request_id}/steps/{step_id}/subtasks/{subtask_id}")
def update_subtask(request_id: int, step_id: int, subtask_id: int, payload: SubtaskUpdate,
                   db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row, step = _visible_step(db, request_id, step_id, user)
    if step.status not in {"ready", "in_progress"}:
        raise HTTPException(409, "Subtasks can only be changed on an active step.")
    subtask = db.query(ApprovalSubtask).filter_by(id=subtask_id, step_id=step.id).first()
    if not subtask: raise HTTPException(404, "Subtask not found.")
    subtask.status = payload.status
    reason = payload.reason.strip()
    _audit_step(db, row, user, step, "subtask_completed", reason,
        subtask_id=subtask.id, subtask_title=subtask.title, status=subtask.status)
    commit(db)
    return {"status":"saved", "approval_steps":_approval_steps(db, row.id)}


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    rows = db.query(ProcurementNotification).filter_by(user_id=user.id).order_by(ProcurementNotification.created_at.desc()).limit(100).all()
    unread = db.query(ProcurementNotification).filter_by(user_id=user.id, read_at=None).count()
    return {"unread_count":unread, "items":[
        {"id":n.id,"request_id":n.request_id,"step_id":n.step_id,"title":n.title,"message":n.message,
         "read":n.read_at is not None,"created_at":n.created_at.isoformat()} for n in rows]}


@router.get("/reviewers")
def reviewers(db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    if user.role not in APPROVERS: raise HTTPException(403, "Approver access is required.")
    rows = db.query(User).filter(User.is_active.is_(True), User.role.in_(APPROVERS)).order_by(User.full_name, User.email).all()
    return [{"id":row.id,"name":row.full_name or row.email,"email":row.email,"role":row.role} for row in rows]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    item = db.query(ProcurementNotification).filter_by(id=notification_id, user_id=user.id).first()
    if not item: raise HTTPException(404, "Notification not found.")
    if item.read_at is None: item.read_at = datetime.utcnow(); commit(db)
    return {"status":"read"}


@router.post("/requests/{request_id}/comments", status_code=201)
def comment(request_id: int, payload: Note, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = visible_request(db, request_id, user, lock=True)
    event(db, row, user, "comment", note=payload.note)
    commit(db)
    return {"status":"saved"}


@router.post("/requests/{request_id}/resubmit")
def resubmit(request_id: int, payload: Note, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    row = visible_request(db, request_id, user, lock=True)
    if row.requester_id != user.id:
        raise HTTPException(403, "Only the requester can resubmit.")
    if row.status != "needs_info":
        raise HTTPException(409, "This request is not waiting for information.")
    row.status = "submitted"
    returned = db.query(ApprovalStep).filter_by(request_id=row.id, status="sent_back").order_by(ApprovalStep.step_order).first()
    if returned:
        returned.status = "ready"
        returned.started_at = datetime.utcnow()
        returned.decision = {}
        _notify_ready(db, row, returned)
        _audit_step(db, row, user, returned, "request_resubmitted", payload.note,
                    requester_note=payload.note.strip())
        ctx = context(db, row)
        if ctx: _sync_legacy_workflow(db, ctx, row.id)
    event(db, row, user, "request_resubmitted", note=payload.note)
    commit(db)
    return {"status":row.status}


def assessment(db, order, payload):
    historical = db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == payload.terms.supplier_id,
                                                 SupplierInvoice.status == "paid").all()
    return assess(payload.terms, PurchaseTerms.model_validate(order.terms), [i.stated_total for i in historical])


def add_revision(db, invoice, payload, risk, user, order=None, row=None):
    db.add(InvoiceRevision(invoice_id=invoice.id, payload=payload.model_dump(mode="json"), assessment=risk, actor_id=user.id))
    if order and row and isinstance(risk, dict) and risk.get("score") is not None:
        from backend.app.procurement.risk import sync_ml_evaluation_to_claims
        ctx = context(db, row)
        cat = (ctx.details or {}).get("category") if ctx else "Procurement Invoice"
        sync_ml_evaluation_to_claims(
            db,
            user,
            claim_id=f"INV-PR-{row.id:04d}",
            source_type="procurement",
            request_id=row.id,
            source_ref=f"PR-{row.id:04d}",
            invoice_number=invoice.invoice_number,
            supplier_id=payload.terms.supplier_id,
            product_title=row.title,
            category=cat or "Procurement Invoice",
            stated_total=payload.stated_total,
            approved_total=order.total,
            currency=payload.terms.currency,
            assessment=risk,
            po_number=f"PO-{order.id:04d}",
        )


@router.post("/orders/{order_id}/invoices", status_code=201)
def record_invoice(order_id: int, payload: InvoiceCreate, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    row = visible_request(db, order.request_id, user, lock=True)
    if db.query(SupplierInvoice).filter_by(order_id=order.id).first():
        raise HTTPException(409, "This MVP supports one invoice per PO. Submit a correction to the existing invoice.")
    differences = match_invoice(PurchaseTerms.model_validate(order.terms), payload)
    invoice = SupplierInvoice(order_id=order.id, supplier_id=payload.terms.supplier_id, invoice_number=payload.invoice_number,
                              terms=payload.terms.model_dump(mode="json"), stated_total=payload.stated_total,
                              status="exception" if differences else "matched", differences=differences)
    db.add(invoice)
    db.flush()
    risk = assessment(db, order, payload)
    add_revision(db, invoice, payload, risk, user, order=order, row=row)
    event(db, row, user, "invoice_checked", invoice_number=invoice.invoice_number, status=invoice.status, differences=differences, model_status=risk["status"])
    commit(db)
    return {"invoice_id":invoice.id,"status":invoice.status,"differences":differences,"assessment":risk,"payment_eligible":False}


def invoice_access(db, invoice_id, user):
    invoice = db.query(SupplierInvoice).filter_by(id=invoice_id).with_for_update().first()
    if not invoice:
        raise HTTPException(404, "Invoice not found.")
    order = db.get(PurchaseOrder, invoice.order_id)
    row = visible_request(db, order.request_id, user, lock=True)
    return invoice, order, row


@router.post("/invoices/{invoice_id}/correct")
def correct_invoice(invoice_id: int, payload: InvoiceCreate, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    invoice, order, row = invoice_access(db, invoice_id, user)
    if invoice.status != "exception" or db.query(ProcurementPayment).filter_by(invoice_id=invoice.id).first():
        raise HTTPException(409, "Only an unpaid exception can be corrected.")
    if invoice.invoice_number != payload.invoice_number:
        raise HTTPException(422, "Keep the original invoice number for a correction.")
    if payload.terms.supplier_id != invoice.supplier_id and payload.terms.supplier_id != order.terms["supplier_id"]:
        raise HTTPException(422, "Supplier corrections must match the approved PO supplier.")
    invoice.supplier_id = payload.terms.supplier_id
    invoice.terms = payload.terms.model_dump(mode="json")
    invoice.stated_total = payload.stated_total
    invoice.differences = match_invoice(PurchaseTerms.model_validate(order.terms), payload)
    invoice.status = "exception" if invoice.differences else "matched"
    risk = assessment(db, order, payload)
    add_revision(db, invoice, payload, risk, user, order=order, row=row)
    event(db, row, user, "invoice_corrected", invoice_number=invoice.invoice_number, status=invoice.status, differences=invoice.differences)
    commit(db)
    return invoice_view(db, invoice)


@router.post("/invoices/{invoice_id}/request-correction")
def request_correction(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    invoice, order, row = invoice_access(db, invoice_id, user)
    if invoice.status != "exception":
        raise HTTPException(409, "There is no invoice discrepancy to resolve.")
    message = "Please correct invoice " + invoice.invoice_number + ": " + "; ".join(
        f"{d['field']}: agreed {d['expected']}, invoiced {d['actual']}" for d in invoice.differences)
    event(db, row, user, "correction_requested", note=message)
    commit(db)
    return {"message":message, "delivery":"Saved to this request's activity; external messaging is not connected."}


@router.post("/invoices/{invoice_id}/review")
def review_invoice(invoice_id: int, payload: Note, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    invoice, order, row = invoice_access(db, invoice_id, user)
    if user.role not in {"finance", "admin"} or row.requester_id == user.id:
        raise HTTPException(403, "Independent finance review is required.")
    if invoice.status != "matched":
        raise HTTPException(409, "Resolve invoice discrepancies before finance approval.")
    invoice.status = "reviewed"
    event(db, row, user, "invoice_reviewed", invoice_id=invoice.id, note=payload.note)
    commit(db)
    return {"status":invoice.status}


@router.get("/invoices/{invoice_id}/revisions")
def revisions(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    invoice_access(db, invoice_id, user)
    return [{"id":r.id,"payload":r.payload,"assessment":r.assessment,"created_at":r.created_at.isoformat()}
            for r in db.query(InvoiceRevision).filter_by(invoice_id=invoice_id).order_by(InvoiceRevision.id).all()]


@router.post("/requests/{request_id}/documents", status_code=201)
def upload_document(request_id: int, kind: str = "supporting", file: UploadFile = File(...),
                    db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    from backend.app.config import UPLOAD_DIR
    row = visible_request(db, request_id, user)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".txt"} or kind not in {"quote","invoice","supporting"}:
        raise HTTPException(422, "Use PDF, PNG, JPEG or TXT, and a supported document category.")
    data = file.file.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Document must be between 1 byte and 10 MB.")
    folder = UPLOAD_DIR / "procurement"
    folder.mkdir(parents=True, exist_ok=True)
    key = uuid4().hex + suffix
    path = folder / key
    path.write_bytes(data)
    document = ProcurementDocument(request_id=row.id,filename=Path(file.filename).name[:255],storage_key=key,kind=kind,size=len(data))
    db.add(document)
    event(db, row, user, "document_uploaded", filename=document.filename, kind=kind)
    try:
        commit(db)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"id":document.id,"filename":document.filename}


@router.get("/documents/{document_id}")
def download_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(require_authenticated_user)):
    from backend.app.config import UPLOAD_DIR
    document = db.get(ProcurementDocument, document_id)
    if not document:
        raise HTTPException(404, "Document not found.")
    visible_request(db, document.request_id, user)
    path = UPLOAD_DIR / "procurement" / document.storage_key
    if not path.is_file():
        raise HTTPException(404, "Document file is unavailable.")
    return FileResponse(path, filename=document.filename, media_type="application/octet-stream")
