"""
AuditAI Global AI Assistant & Copilot API.

Provides real-time system context and intelligent interactive assistance across all
AuditAI workflows (Procurement, Sourcing, Claims Fraud Detection, Review Queue,
PayPal Sandbox Payments, Master Data Ingestion, and Background Workers).
"""
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.auth.security import get_current_user
from backend.app.models.auth import AuthUser
from backend.app.models.procurement import PurchaseRequest, PurchaseOrder, SupplierInvoice, ProcurementPayment
from backend.app.api.sourcing import SourcingRequest, SourcingSearch
from backend.app.models.expense import ExpenseClaim
from backend.app.models.review_queue import ReviewRecord
from backend.app.models.master_data import VendorMaster, EmployeeMaster
from backend.app.config import GEMINI_MODEL

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    text: str = Field(..., min_length=1, max_length=5000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: Optional[List[ChatMessage]] = Field(default_factory=list)


def build_system_context(db: Session, user: AuthUser) -> Dict[str, Any]:
    """Compiles a complete, real-time snapshot of the platform state."""
    # 1. Procurement & Sourcing Requests
    sr_query = db.query(SourcingRequest).order_by(SourcingRequest.id.desc())
    total_sr = sr_query.count()
    recent_srs = sr_query.limit(10).all()

    sourcing_summary = []
    for sr in recent_srs:
        reqs = sr.requirements or {}
        # Check latest search/agent run for this request
        search = (
            db.query(SourcingSearch)
            .filter(SourcingSearch.request_id == sr.id)
            .order_by(SourcingSearch.id.desc())
            .first()
        )
        winner_name = None
        winner_price = None
        rfq_count = 0
        quote_count = 0
        po_number = None
        if search and search.evidence:
            ev = search.evidence
            winner_name = (ev.get("winner_vendor") or {}).get("name")
            winner_price = ev.get("winning_price") or (ev.get("winner_vendor") or {}).get("quote_price")
            rfq_count = len(ev.get("rfqs") or [])
            quote_count = len(ev.get("quotes") or [])
            po_number = ev.get("po_number")

        sourcing_summary.append({
            "id": f"SR-{sr.id:04d}",
            "numeric_id": sr.id,
            "product": reqs.get("product") or "Procurement Request",
            "quantity": reqs.get("quantity") or 1,
            "budget": reqs.get("budget"),
            "currency": reqs.get("currency") or "USD",
            "status": sr.status,
            "department": reqs.get("department") or "General",
            "created_at": sr.created_at.isoformat() if sr.created_at else None,
            "winner_vendor": winner_name,
            "winner_price": winner_price,
            "rfqs_sent": rfq_count,
            "quotes_received": quote_count,
            "po_number": po_number,
        })

    # Purchase orders
    po_count = db.query(PurchaseOrder).count()
    # Invoices
    inv_count = db.query(SupplierInvoice).count()

    # 2. Payments (PayPal Sandbox & Procurement Payments)
    payments = db.query(ProcurementPayment).order_by(ProcurementPayment.id.desc()).limit(10).all()
    payment_summary = []
    settled_payments = 0
    for p in payments:
        if p.status in ("settled", "completed", "approved"):
            settled_payments += 1
        payment_summary.append({
            "id": p.id,
            "invoice_id": p.invoice_id,
            "status": p.status,
            "provider_order_id": p.provider_order_id,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    # 3. Claims & Fraud Anomaly Detection
    total_claims = db.query(ExpenseClaim).count()
    flagged_claims_query = db.query(ExpenseClaim).filter(ExpenseClaim.status.in_(["flagged", "rejected"]))
    flagged_count = flagged_claims_query.count()
    recent_flagged = flagged_claims_query.order_by(ExpenseClaim.id.desc()).limit(5).all()

    flagged_summary = []
    for c in recent_flagged:
        flagged_summary.append({
            "claim_id": c.claim_id,
            "employee": c.employee_name,
            "vendor": c.vendor_name,
            "amount": float(c.claimed_amount) if c.claimed_amount is not None else 0.0,
            "status": c.status,
        })

    # 4. Review Queue
    review_records = db.query(ReviewRecord).order_by(ReviewRecord.id.desc()).all()
    review_count = len(review_records)
    open_reviews = [r for r in review_records if r.status in ("open", "pending", "awaiting_maker", "awaiting_checker")]
    review_summary = []
    for r in open_reviews[:5]:
        review_summary.append({
            "id": r.id,
            "source_key": r.source_key,
            "case_type": r.case_type,
            "severity": r.severity,
            "status": r.status,
            "reason": r.reason,
        })

    # 5. Master Data
    vendor_master_count = db.query(VendorMaster).count()
    employee_master_count = db.query(EmployeeMaster).count()

    # 6. Autonomous Background Worker Status
    from backend.app.agentic_ai.background_worker import get_worker_status
    worker_status = get_worker_status()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "user": {
            "name": user.display_name or user.email,
            "email": user.email,
            "roles": user.roles or [user.role],
        },
        "procurement": {
            "total_requests": total_sr,
            "purchase_orders": po_count,
            "invoices": inv_count,
            "recent_requests": sourcing_summary,
        },
        "payments": {
            "mode": "PayPal Sandbox",
            "total_records": len(payments),
            "settled_records": settled_payments,
            "recent": payment_summary,
        },
        "fraud_detection": {
            "total_claims": total_claims,
            "flagged_claims_count": flagged_count,
            "recent_flagged": flagged_summary,
        },
        "review_queue": {
            "total_cases": review_count,
            "open_cases_count": len(open_reviews),
            "recent_open": review_summary,
        },
        "master_data": {
            "vendor_master_rows": vendor_master_count,
            "employee_master_rows": employee_master_count,
        },
        "background_worker": worker_status,
    }


def generate_local_response(query: str, context: Dict[str, Any]) -> str:
    """High-accuracy semantic responder using the live platform database context."""
    q = query.lower().strip()
    proc = context["procurement"]
    fraud = context["fraud_detection"]
    review = context["review_queue"]
    pay = context["payments"]
    worker = context["background_worker"]

    # 1. Background tasks / what is running
    if any(k in q for k in ["running", "background", "worker", "status of system", "current status", "activity"]):
        w_state = "Active (Polling every 15s)" if worker.get("is_running") else "Standby"
        recent_req = proc["recent_requests"][0] if proc["recent_requests"] else None
        req_info = (
            f"Latest request is **{recent_req['id']}** ({recent_req['product']}) at status **{recent_req['status']}**."
            if recent_req else "No procurement requests yet."
        )
        return (
            f"**AuditAI Platform Live Status:**\n\n"
            f"• **Autonomous Sourcing Worker**: `{w_state}` (Autonomous vendor outreach, quote extraction, and negotiation enabled)\n"
            f"• **Procurement & Sourcing**: `{proc['total_requests']}` requests active. {req_info}\n"
            f"• **Expense Claims & Fraud Anomaly Detection**: `{fraud['total_claims']}` total claims, `{fraud['flagged_claims_count']}` flagged for review.\n"
            f"• **Shared Review Queue**: `{review['open_cases_count']}` cases awaiting action.\n"
            f"• **Payments Engine**: PayPal Sandbox mode ready."
        )

    # 2. Procurement / Specific PR / Orders
    pr_match = re.search(r'\b(pr|sr)[-_ ]?0*(\d+)\b', q)
    if pr_match or any(k in q for k in ["procurement", "request", "order", "purchase", "sourcing", "item"]):
        if pr_match:
            req_num = int(pr_match.group(2))
            found = next((r for r in proc["recent_requests"] if r["numeric_id"] == req_num), None)
            if found:
                currency = found.get("currency") or "USD"
                budget = found.get("budget")
                budget_str = f"{currency} {budget:,.2f}" if budget is not None else "Not set"
                winner = f", Winner: **{found['winner_vendor']}**" if found.get('winner_vendor') else ""
                po = f", PO: `{found['po_number']}`" if found.get('po_number') else ""
                return (
                    f"**Request {found['id']} Details:**\n\n"
                    f"• **Product**: {found['product']}\n"
                    f"• **Status**: `{found['status']}`\n"
                    f"• **Quantity**: {found['quantity']}\n"
                    f"• **Budget**: {budget_str}\n"
                    f"• **Department**: {found['department']}\n"
                    f"• **RFQs Sent**: {found['rfqs_sent']} | **Quotes**: {found['quotes_received']}{winner}{po}"
                )
        # General requests list
        if proc["recent_requests"]:
            items = []
            for r in proc["recent_requests"][:4]:
                b_str = f" ({r['currency']} {r['budget']})" if r.get("budget") else ""
                items.append(f"• **{r['id']}**: {r['product']} — Status: `{r['status']}`{b_str}")
            return (
                f"There are currently **{proc['total_requests']} total sourcing requests** on file.\n\n"
                + "\n".join(items)
                + f"\n\nTell me an ID (e.g. `{proc['recent_requests'][0]['id']}`) to inspect full details or quotes!"
            )
        return "No procurement requests currently exist in the database. You can create one from the Procurement tab!"

    # 3. Vendors / RFQ / Quotes / Negotiation
    if any(k in q for k in ["vendor", "rfq", "quote", "negotiat", "winner", "supplier"]):
        recent_srs = [r for r in proc["recent_requests"] if r.get("rfqs_sent", 0) > 0 or r.get("winner_vendor")]
        if recent_srs:
            lines = []
            for r in recent_srs[:3]:
                win_str = f" → Awarded to **{r['winner_vendor']}**" if r.get("winner_vendor") else " (RFQs dispatched)"
                lines.append(f"• **{r['id']}** ({r['product']}): {r['rfqs_sent']} RFQs sent, {r['quotes_received']} quotes{win_str}")
            return (
                f"**Vendor Engagement & Negotiation Status:**\n\n"
                + "\n".join(lines)
                + "\n\nThe AI sourcing agent automatically handles vendor outreach, RFQ emails, email reply parsing, and counteroffers."
            )
        return (
            "The AI agent engages vendors automatically via verified email RFQs and Dograh voice calls. "
            f"Currently {proc['total_requests']} sourcing requests exist. Open any request to dispatch RFQs or review quotes."
        )

    # 4. Payments / PayPal / Settlement
    if any(k in q for k in ["pay", "paypal", "sandbox", "settle", "invoice"]):
        return (
            f"**Payment & Settlement Status:**\n\n"
            f"• **Gateway**: PayPal Sandbox\n"
            f"• **Settled Payments**: `{pay['settled_records']}`\n"
            f"• **Logged Transactions**: `{pay['total_records']}`\n"
            f"• When a Purchase Order is approved, the payment milestone is triggered with one-click sandbox authorization. Once executed, the transaction settles immediately."
        )

    # 5. Fraud Detection / Expense Claims / Anomalies
    if any(k in q for k in ["fraud", "claim", "anomal", "policy", "score", "risk"]):
        if fraud["flagged_claims_count"] > 0:
            flagged_list = [
                f"• Claim `{c['claim_id']}` ({c['employee']} at {c['vendor']}): ₹{c['amount']:,.2f} — `{c['status']}`"
                for c in fraud["recent_flagged"]
            ]
            return (
                f"**Expense Anomaly & Fraud Overview:**\n\n"
                f"• Total claims in database: **{fraud['total_claims']}**\n"
                f"• Flagged high-risk anomalies: **{fraud['flagged_claims_count']}**\n\n"
                + "\n".join(flagged_list)
                + "\n\nYou can inspect the anomaly SHAP evidence and detection map on the **Dashboard** and **Audit Screens**."
            )
        return (
            f"**Expense Anomaly Status:**\n\n"
            f"All **{fraud['total_claims']} claims** have passed standard policy thresholds. "
            f"No critical anomalies are currently unresolved."
        )

    # 6. Review Queue / Approvals / Maker-Checker
    if any(k in q for k in ["review", "queue", "maker", "checker", "case"]):
        if review["open_cases_count"] > 0:
            cases_list = [
                f"• Case `#{c['id']}` ({c['case_type']}): Severity `{c['severity']}` — {c['reason']}"
                for c in review["recent_open"]
            ]
            return (
                f"**Shared Review Queue:**\n\n"
                f"• **{review['open_cases_count']} open cases** awaiting review.\n\n"
                + "\n".join(cases_list)
                + "\n\nVisit the **Review Queue** tab to sign off or recommend actions."
            )
        return "The **Shared Review Queue** has 0 pending items. All cases have been resolved!"

    # 7. Default greeting & capabilities
    user_name = context["user"]["name"] or "there"
    return (
        f"Hello {user_name}! I am your **AuditAI Global Copilot**.\n\n"
        f"I have direct, real-time memory of all platform operations. Right now:\n"
        f"• **{proc['total_requests']} Procurement Requests** are tracked in the database\n"
        f"• **{fraud['flagged_claims_count']} of {fraud['total_claims']} Claims** are flagged for policy/fraud review\n"
        f"• **{review['open_cases_count']} Review Cases** are awaiting approval in the queue\n"
        f"• **PayPal Sandbox** payment integration is active\n\n"
        f"You can ask me anything about order statuses, specific PR numbers, vendor quotes, payments, or fraud signals!"
    )


@router.get("/context")
def get_assistant_context(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """Returns the live contextual state of the entire platform."""
    return build_system_context(db, user)


@router.post("/chat")
def assistant_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """Processes chat queries with live situational memory across the platform."""
    context = build_system_context(db, user)

    # Attempt to use Gemini model if configured
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            prompt = (
                f"You are the AuditAI Global Autonomous Copilot and Mascot. You have direct, live, real-time access "
                f"to the platform's database and background services.\n\n"
                f"CURRENT PLATFORM LIVE CONTEXT:\n{context}\n\n"
                f"USER QUERY: {payload.message}\n\n"
                f"Answer concisely, accurately, and professionally. Reference actual IDs, amounts, and statuses "
                f"from the context. If the user asks about taking actions or navigating, guide them clearly."
            )
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            reply_text = getattr(response, "text", None)
            if reply_text and reply_text.strip():
                return {"reply": reply_text.strip(), "context": context}
        except Exception:
            pass  # Fall back seamlessly to local semantic context matcher

    # Local fallback with authoritative database figures
    reply_text = generate_local_response(payload.message, context)
    return {"reply": reply_text, "context": context}
