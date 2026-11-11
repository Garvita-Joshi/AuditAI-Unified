import hashlib
import json
from datetime import datetime
from backend.app.models.policy import ClaimPolicy,ReviewerAuthority
from backend.app.models.expense import ExpenseClaim,Case,CaseAuditTrail
from backend.app.features.policy_rules import evaluate_policy,CONFIG


def run_checks(db, persist=False):
    db.flush()
    claims=db.query(ExpenseClaim).all()
    meta={p.claim_id:p for p in db.query(ClaimPolicy).all()}
    records=[]
    for c in claims:
        p=meta.get(c.claim_id); inputs=p.inputs if p else {}
        o=c.receipt.ocr_result if c.receipt else None
        records.append(dict(inputs,id=c.claim_id,entity_id=c.entity_id,employee_id=c.employee_id,vendor=c.vendor_name,amount=str(c.claimed_amount),date=c.claimed_date,description=c.description,currency=c.entity.currency.upper() if c.entity else None,ocr_amount=str(o.extracted_amount) if o and o.extracted_amount is not None else None,ocr_confidence=o.extraction_confidence if o else None,ocr_processed=bool(c.receipt and c.receipt.upload_status=='processed')))
    results=evaluate_policy(records)
    if persist:
        for c in claims:
            result=results[c.claim_id]; p=meta.get(c.claim_id)
            if not p: p=ClaimPolicy(claim_id=c.claim_id,inputs={}); db.add(p)
            old=p.result
            p.result=result; p.checked_at=datetime.utcnow()
            if result['requires_review'] and c.status not in ('approved','rejected'):
                if c.status!='processing': c.status='flagged'
                if c.prediction: c.prediction.is_flagged=True
                case=c.case
                if not case:
                    case=Case(claim_id=c.claim_id,status='open'); db.add(case); db.flush(); c.case=case
                elif case.status=='cancelled_unflagged': case.status='open'
                if old!=result:
                    db.add(CaseAuditTrail(case_id=case.id,action='policy_review_required',performed_by='system',notes=json.dumps(result)))
    return results


def approval_block(db,user,claim):
    from decimal import Decimal
    if not claim.entity or claim.entity.currency.upper()!=CONFIG['currency']:
        if abs(claim.claimed_amount)>CONFIG['default_checker_limit']:
            return 'Claim currency unavailable or unsupported for high-value company approval authority.'
        return None
    p=db.get(ClaimPolicy,claim.claim_id)
    required=max(abs(claim.claimed_amount),Decimal(p.result['required_approval_amount']) if p and p.result else Decimal(0))
    authority=db.get(ReviewerAuthority,user.id)
    limit=authority.limit if authority else Decimal(str(CONFIG['default_checker_limit']))
    if required>limit:
        return f'Requires a checker with INR {required} authority; your limit is INR {limit}. Ask an administrator to provision the appropriate senior checker.'
    return None
