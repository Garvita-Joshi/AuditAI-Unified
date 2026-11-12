"""
AuditAI — API endpoints for expense claim management.

Handles claim upload (CSV/JSON), individual claim retrieval, listing with
filtering/sorting/pagination, and receipt attachment.
"""
import io
import logging
import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from fuzzywuzzy import fuzz
from backend.app.config import KNOWN_VENDORS
from backend.app.auth.security import (
    assert_can_view_claim, get_current_user, has_role, is_claim_participant,
    review_block_reason, require_roles,
)
from backend.app.db import Base, engine, get_db
from backend.app.models.auth import AuthUser, ClaimContributor
from backend.app.models.policy import ClaimPolicy
from backend.app.policy_service import run_checks
from backend.app.models.expense import (
    AuditReport,
    ExpenseClaim,
    FraudPrediction,
    OcrResult,
    Receipt,
    Entity,
    Case,
    CaseAuditTrail,
)
from backend.app.schemas.expense import (
    ClaimListResponse,
    ExpenseClaimDetail,
    ExpenseClaimResponse,
    FraudPredictionResponse,
    AuditReportResponse,
    OcrResultResponse,
    UploadResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/claims", tags=["Claims"])


def get_closest_vendor(vendor_name: str):
    if not vendor_name:
        return None, 0.0
    vendor_lower = vendor_name.lower().strip()
    vendor_tokens = re.findall(r"[a-z0-9]+", vendor_lower)
    max_ratio = 0.0
    closest = None
    for known in KNOWN_VENDORS:
        known_lower = known.lower().strip()
        if vendor_lower == known_lower:
            return None, 0.0
        known_tokens = re.findall(r"[a-z0-9]+", known_lower)
        full_ratio = fuzz.ratio(vendor_lower, known_lower) / 100.0
        first_token_ratio = (fuzz.ratio(vendor_tokens[0], known_tokens[0]) / 100.0
                             if vendor_tokens and known_tokens else 0.0)
        brand_typo = (vendor_tokens and known_tokens and vendor_tokens[0] != known_tokens[0]
                      and min(len(vendor_tokens[0]), len(known_tokens[0])) >= 4
                      and first_token_ratio >= 0.80)
        # Shared generic words such as "Airlines" must not imply a typo.
        if full_ratio < 0.85 and not brand_typo:
            continue
        ratio = max(full_ratio, first_token_ratio if brand_typo else 0.0)
        if ratio > max_ratio:
            max_ratio = ratio
            closest = known
    return closest, max_ratio


@router.post("/init-db", status_code=status.HTTP_200_OK)
def init_db(db: Session = Depends(get_db), user: AuthUser = Depends(require_roles("admin"))):
    """Create all database tables and seed default entity."""
    try:
        Base.metadata.create_all(bind=engine)
        
        # Seed default APAC Entity
        entity = db.query(Entity).filter(Entity.name == "APAC Entity").first()
        if not entity:
            entity = Entity(name="APAC Entity", currency="INR", materiality_threshold=50000.00)
            db.add(entity)
            db.commit()
            
        return {"status": "success", "message": "All database tables created & default entity seeded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB init failed: {e}")


@router.post("/seed-demo", status_code=status.HTTP_200_OK)
def seed_demo_claims(db: Session = Depends(get_db)):
    """Seed or restore the initial 18 claims and fraud predictions for the dashboard."""
    from backend.app.seed_loader import seed_initial_claims_data
    seeded = seed_initial_claims_data(db)
    return {"status": "success", "seeded": seeded, "claims_count": db.query(ExpenseClaim).count()}


@router.post("/upload", response_model=UploadResponse)
async def upload_claims(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """
    Upload expense claims from a CSV or JSON file.

    Expected CSV columns: claim_id, employee_id, employee_name, claimed_amount,
    vendor_name, claimed_date, category, description, is_fraud, fraud_type, ocr_amount
    """
    if not file.filename:
        raise HTTPException(400, "No file provided.")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("csv", "json"):
        raise HTTPException(400, "File must be CSV or JSON.")

    try:
        contents = await file.read()
        if ext == "csv":
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_json(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(422, f"Failed to parse file: {e}")

    # Standardize columns
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    aliases = {'transaction_id': 'claim_id', 'amount': 'claimed_amount',
               'transaction_date': 'claimed_date', 'general_ledger_account': 'category',
               'is_anomaly': 'is_fraud', 'risk_category': 'fraud_type',
               'ocr_extracted_amount': 'ocr_amount', 'extracted_vendor': 'ocr_vendor',
               'extracted_date': 'ocr_date', 'extraction_confidence': 'ocr_confidence'}
    df = df.rename(columns={a:b for a,b in aliases.items() if a in df and b not in df})

    required = ["claim_id", "employee_id", "employee_name", "claimed_amount", "vendor_name", "claimed_date"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Missing columns: {missing}")

    if not has_role(user, "maker", "checker", "admin"):
        employee_ids = {str(value).strip() for value in df["employee_id"]}
        if employee_ids != {user.employee_id}:
            raise HTTPException(403, "Employees may submit claims only for their own employee ID.")

    loaded = 0
    errors = []

    # Fetch all existing claim IDs at once to avoid N+1 queries
    existing_claim_ids = set(r[0] for r in db.query(ExpenseClaim.claim_id).all())
    
    # Get default entity once
    default_entity = db.query(Entity).filter(Entity.name == "APAC Entity").first()
    entity_id = default_entity.id if default_entity else None

    claims_to_add = []
    policy_inputs = {}
    for idx, row in df.iterrows():
        try:
            claim_id = str(row["claim_id"]).strip()

            # Skip duplicates using our in-memory set
            if claim_id in existing_claim_ids:
                continue

            # Parse amount
            amt_raw = str(row["claimed_amount"]).replace(",", "").replace("₹", "").replace("$", "").strip()
            amount = Decimal(amt_raw)
            if not amount.is_finite():
                raise ValueError('Amount must be finite.')
            if any(pd.isna(row[k]) or not str(row[k]).strip() for k in ['claim_id','employee_id','employee_name','vendor_name']):
                raise ValueError('Claim ID, employee ID/name and vendor cannot be blank.')
            from backend.app.api.policies import Inputs
            supplied = {k:row[k] for k in Inputs.model_fields if k in row and pd.notna(row[k])}
            if not has_role(user,'admin'):
                supplied = {k:v for k,v in supplied.items() if k not in ('source_approver_id','source_approver_limit','business_exception')}
            metadata = Inputs(**supplied).model_dump(mode='json',exclude_unset=True)

            # Parse date
            date_val = pd.to_datetime(row["claimed_date"]).date()
            if pd.isna(date_val):
                raise ValueError('Claim date is missing or invalid.')

            # Parse fraud labels
            is_fraud = False
            if "is_fraud" in df.columns:
                val = str(row.get("is_fraud", "")).strip().lower()
                is_fraud = val in ("true", "1", "yes", "t")

            fraud_type = str(row.get("fraud_type", "none")).strip() if pd.notna(row.get("fraud_type")) else "none"

            claim = ExpenseClaim(
                claim_id=claim_id,
                employee_id=str(row["employee_id"]).strip(),
                employee_name=str(row["employee_name"]).strip(),
                claimed_amount=amount,
                vendor_name=str(row["vendor_name"]).strip(),
                claimed_date=date_val,
                category=str(row.get("category", "")).strip() if pd.notna(row.get("category")) else None,
                description=str(row.get("description", "")).strip() if pd.notna(row.get("description")) else None,
                status="pending",
                is_fraud=is_fraud,
                fraud_type=fraud_type,
                entity_id=entity_id,
            )
            if pd.notna(row.get('submitted_at')):
                claim.submitted_at = pd.to_datetime(row['submitted_at'], utc=True).tz_localize(None).to_pydatetime()
            # Preserve existing extracted receipt amounts from tabular imports.
            # Unknown OCR quality remains unknown, never fabricated as 100%.
            if pd.notna(row.get('ocr_amount')):
                ocr_amount = Decimal(str(row['ocr_amount']))
                if not ocr_amount.is_finite():
                    raise ValueError('OCR amount must be finite.')
                confidence = float(row['ocr_confidence']) if pd.notna(row.get('ocr_confidence')) else None
                if confidence is not None and not 0 <= confidence <= 1:
                    raise ValueError('OCR confidence must be between zero and one.')
                receipt = Receipt(receipt_id=f'CSV-{uuid.uuid4().hex[:16]}', file_path='',
                                  file_type='imported', upload_status='processed')
                receipt.ocr_result = OcrResult(extracted_amount=ocr_amount,
                    extracted_vendor=(str(row['ocr_vendor']).strip() if pd.notna(row.get('ocr_vendor')) else None),
                    extracted_date=(str(row['ocr_date']).strip() if pd.notna(row.get('ocr_date')) else None),
                    extraction_method='imported', extraction_confidence=confidence)
                claim.receipt = receipt
            claims_to_add.append(claim)
            policy_inputs[claim_id] = metadata
            existing_claim_ids.add(claim_id) # prevent duplicate inserts from the same file
            loaded += 1
        except Exception as e:
            errors.append({"row": idx + 1, "error": str(e)})

    if claims_to_add:
        db.add_all(claims_to_add)
        db.flush()
        db.add_all([ClaimPolicy(claim_id=c.claim_id,inputs=policy_inputs[c.claim_id]) for c in claims_to_add])
        db.add_all([
            ClaimContributor(claim_id=claim.claim_id, user_id=user.id, source="claim_upload")
            for claim in claims_to_add
        ])
        db.flush()
        run_checks(db,True)
        db.commit()

    from backend.app.automatic_checks import after_import
    checks=after_import(db,user,'claims',claim_ids=[c.claim_id for c in claims_to_add]) if claims_to_add else None
    return UploadResponse(
        checks=checks,
        status="success" if not errors else "partial_success",
        message=f"Loaded {loaded} claims.",
        processed_count=len(df),
        error_count=len(errors),
        errors=errors[:20],  # Limit error details
    )


@router.get("", response_model=ClaimListResponse)
def list_claims(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    score_band: Optional[str] = Query(None, regex="^(low|review|high)$"),
    search: Optional[str] = Query(None),
    sort_by: str = Query("submitted_at", regex="^(claim_id|employee_name|vendor_name|claimed_amount|claimed_date|submitted_at|status|fraud_score)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """List claims with filtering, sorting, and pagination."""
    query = db.query(ExpenseClaim)
    if not has_role(user, "maker", "checker", "admin"):
        contributed = db.query(ClaimContributor.claim_id).filter(ClaimContributor.user_id == user.id)
        query = query.filter(or_(ExpenseClaim.employee_id == user.employee_id,
                                 ExpenseClaim.claim_id.in_(contributed)))

    if status_filter:
        query = query.filter(ExpenseClaim.status == status_filter)

    if score_band or sort_by == "fraud_score":
        query = query.outerjoin(FraudPrediction, ExpenseClaim.claim_id == FraudPrediction.claim_id)
    if score_band:
        displayed_score = func.round(FraudPrediction.combined_fraud_score * 100, 0)
        if score_band == "low":
            query = query.filter(displayed_score < 50)
        elif score_band == "review":
            query = query.filter(displayed_score >= 50, displayed_score < 65)
        else:
            query = query.filter(displayed_score >= 65)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                ExpenseClaim.claim_id.ilike(search_term),
                ExpenseClaim.employee_name.ilike(search_term),
                ExpenseClaim.vendor_name.ilike(search_term)
            )
        )

    # Sorting
    if sort_by == "fraud_score":
        # Keep unscored claims last in either direction and sort before pagination.
        score = FraudPrediction.combined_fraud_score
        query = query.order_by(score.is_(None), score.desc() if sort_order == "desc" else score.asc(),
                               ExpenseClaim.claim_id.asc())
    else:
        sort_col = getattr(ExpenseClaim, sort_by, ExpenseClaim.submitted_at)
        query = query.order_by(sort_col.desc() if sort_order == "desc" else sort_col.asc(),
                               ExpenseClaim.claim_id.asc())

    total = query.count()
    claims = query.offset((page - 1) * page_size).limit(page_size).all()

    claim_responses = []
    for c in claims:
        closest_match, match_ratio = get_closest_vendor(c.vendor_name)
        if match_ratio >= 1.0 or match_ratio < 0.70:
            closest_match = None
            match_ratio = 0.0

        resp = ExpenseClaimResponse(
            id=c.id,
            claim_id=c.claim_id,
            employee_id=c.employee_id,
            employee_name=c.employee_name,
            claimed_amount=c.claimed_amount,
            vendor_name=c.vendor_name,
            claimed_date=c.claimed_date,
            category=c.category,
            description=c.description,
            status=c.status,
            submitted_at=c.submitted_at,
            receipt_id=c.receipt_id,
            is_fraud=c.is_fraud,
            fraud_type=c.fraud_type,
            fraud_score=c.prediction.combined_fraud_score if c.prediction else None,
            is_flagged=c.prediction.is_flagged if c.prediction else None,
            entity_name=c.entity.name if c.entity else "APAC Entity",
            currency=c.entity.currency if c.entity else "INR",
            case_status=c.case.status if c.case else "none",
            closest_vendor_match=closest_match,
            vendor_similarity_score=match_ratio if closest_match else None,
        )
        claim_responses.append(resp)

    return ClaimListResponse(
        claims=claim_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{claim_id}")
def get_claim_detail(claim_id: str, db: Session = Depends(get_db),
                     user: AuthUser = Depends(get_current_user)):
    """Get full claim detail with OCR, prediction, SHAP, and audit report."""
    claim = db.query(ExpenseClaim).filter(ExpenseClaim.claim_id == claim_id).first()
    if not claim:
        raise HTTPException(404, f"Claim {claim_id} not found.")
    assert_can_view_claim(db, user, claim)

    # Build response
    closest_match, match_ratio = get_closest_vendor(claim.vendor_name)
    if match_ratio >= 1.0 or match_ratio < 0.70:
        closest_match = None
        match_ratio = 0.0

    claim_resp = ExpenseClaimResponse(
        id=claim.id,
        claim_id=claim.claim_id,
        employee_id=claim.employee_id,
        employee_name=claim.employee_name,
        claimed_amount=claim.claimed_amount,
        vendor_name=claim.vendor_name,
        claimed_date=claim.claimed_date,
        category=claim.category,
        description=claim.description,
        status=claim.status,
        submitted_at=claim.submitted_at,
        receipt_id=claim.receipt_id,
        is_fraud=claim.is_fraud,
        fraud_type=claim.fraud_type,
        fraud_score=claim.prediction.combined_fraud_score if claim.prediction else None,
        is_flagged=claim.prediction.is_flagged if claim.prediction else None,
        entity_name=claim.entity.name if claim.entity else "APAC Entity",
        currency=claim.entity.currency if claim.entity else "INR",
        case_status=claim.case.status if claim.case else "none",
        closest_vendor_match=closest_match,
        vendor_similarity_score=match_ratio if closest_match else None,
    )

    ocr_resp = None
    if claim.receipt and claim.receipt.ocr_result:
        ocr = claim.receipt.ocr_result
        ocr_resp = OcrResultResponse(
            id=ocr.id,
            receipt_id=ocr.receipt_id,
            raw_ocr_text=ocr.raw_ocr_text,
            extracted_vendor=ocr.extracted_vendor,
            extracted_amount=ocr.extracted_amount,
            extracted_date=ocr.extracted_date,
            extracted_tax_id=ocr.extracted_tax_id,
            extracted_line_items=ocr.extracted_line_items,
            extraction_method=ocr.extraction_method,
            extraction_confidence=ocr.extraction_confidence,
            processed_at=ocr.processed_at,
        )

    pred_resp = None
    if claim.prediction:
        p = claim.prediction
        pred_resp = FraudPredictionResponse(
            id=p.id,
            claim_id=p.claim_id,
            reconstruction_error=p.reconstruction_error,
            isolation_forest_score=p.isolation_forest_score,
            combined_fraud_score=p.combined_fraud_score,
            is_flagged=p.is_flagged,
            shap_values=p.shap_values,
            feature_values=p.feature_values,
            predicted_at=p.predicted_at,
        )

    report_resp = None
    if claim.audit_report:
        r = claim.audit_report
        report_resp = AuditReportResponse(
            id=r.id,
            claim_id=r.claim_id,
            report_text=r.report_text,
            generated_by=r.generated_by,
            generated_at=r.generated_at,
        )

    maker = None
    if claim.case and claim.case.maker_id and str(claim.case.maker_id).isdigit():
        maker = db.query(AuthUser).filter(AuthUser.id == int(claim.case.maker_id)).first()

    return {
        "claim": claim_resp,
        "policy": (db.get(ClaimPolicy,claim_id).result if db.get(ClaimPolicy,claim_id) else None),
        "ocr_result": ocr_resp,
        "prediction": pred_resp,
        "audit_report": report_resp,
        "case_review": {
            "maker_recommendation": (
                "approve" if claim.case.status == "maker_recommended_approve" else
                "reject" if claim.case.status == "maker_recommended_reject" else None
            ) if claim.case else None,
            "maker_notes": claim.case.maker_notes if claim.case else None,
            "maker_name": maker.display_name if maker else None,
        },
        "review_permissions": {
            "is_own_claim": is_claim_participant(db, user, claim),
            "maker_block_reason": review_block_reason(db, user, claim, "maker"),
            "checker_block_reason": review_block_reason(db, user, claim, "checker"),
        },
    }


@router.patch("/{claim_id}/status")
def update_claim_status(
    claim_id: str,
    new_status: str = Query(..., regex="^(pending|processing|scored|flagged)$"),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("admin")),
):
    """Admin maintenance for non-final statuses; approval requires checker sign-off."""
    claim = db.query(ExpenseClaim).filter(ExpenseClaim.claim_id == claim_id).first()
    if not claim:
        raise HTTPException(404, f"Claim {claim_id} not found.")

    claim.status = new_status
    db.commit()
    return {"status": "success", "claim_id": claim_id, "new_status": new_status}
