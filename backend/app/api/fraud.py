"""
AuditAI — API endpoints for ML-based fraud scoring and dashboard summaries.
"""
import logging
import json
from collections import defaultdict
from typing import Any, Dict

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app import config
from backend.app.db import get_db
from backend.app.auth.security import get_current_user, require_roles
from backend.app.models.auth import AuthUser
from backend.app.features.behavioral import compute_features_batch, claim_record, event_time_info
from backend.app.ml.explainer import compute_shap_values, get_top_features
from backend.app.ml.pipeline import load_pipeline, score_claims, train_claims, transform_features
from backend.app.models.expense import ExpenseClaim, FraudPrediction, Case, CaseAuditTrail
from backend.app.api.analytics import get_case_cycle_metrics
from backend.app.detection_strategy import model_decision, strategy, PATH as STRATEGY_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/fraud", tags=["Fraud"])


# Stable labels used by both the API and the auditor-facing dashboard. The
# underlying feature names remain available in the response for traceability.
_FEATURE_LABELS = {
    "holiday_policy": "Holiday submission policy",
    "log_amount": "Claim amount (log scale)",
    "is_negative": "Negative amount",
    "is_round": "Round amount",
    "hour": "Submission hour",
    "weekend_flag": "Weekend submission",
    "is_after_hours": "After-hours submission",
    "z_global": "Amount vs. all claims",
    "z_vendor": "Amount vs. vendor history",
    "z_employee": "Amount vs. employee history",
    "z_category": "Amount vs. category history",
    "log_vendor_prior_n": "Vendor history volume",
    "log_employee_prior_n": "Employee history volume",
    "vendor_is_new": "New vendor",
    "employee_is_new": "New employee",
    "pair_is_new": "New employee-vendor pair",
    "vendor_missing": "Missing vendor identity",
    "employee_missing": "Missing employee identity",
    "log_vendor_freq_30d": "Vendor frequency (30 days)",
    "log_employee_freq_7d": "Employee frequency (7 days)",
    "log_days_since_vendor": "Days since vendor was seen",
    "duplicate_prior": "Prior duplicate match",
    "log_pair_amount_1d": "Same-pair amount (1 day)",
    "log_pair_count_1d": "Same-pair count (1 day)",
    "has_receipt": "Receipt present",
    "ocr_amount_missing": "Receipt amount missing",
    "ocr_confidence": "OCR confidence",
    "ocr_confidence_missing": "OCR confidence missing",
    "ocr_low_confidence": "OCR low confidence",
    "log_ocr_amount": "Receipt amount",
    "ocr_mismatch_ratio": "Receipt amount mismatch",
    "ocr_vendor_mismatch": "Receipt vendor mismatch",
    "ocr_date_gap": "Receipt date gap",
    "vendor_name_deviation": "Vendor name deviation",
    "amount_mismatch_ratio": "Receipt amount mismatch",
    "has_amount_mismatch": "Amount mismatch flag",
    "duplicate_score": "Duplicate similarity",
    "is_likely_duplicate": "Likely duplicate",
    "vendor_anomaly_score": "Vendor anomaly",
    "is_known_vendor": "Known vendor signal",
    "amount_zscore": "Employee amount outlier",
    "claim_frequency_7d": "7-day claim frequency",
    "claim_frequency_30d": "30-day claim frequency",
    "is_weekend": "Weekend submission",
    "is_holiday": "Holiday submission",
    "is_round_amount": "Round amount",
    "amount_log": "Claim amount scale",
    "split_transaction_flag": "Split transaction",
    "category_risk_score": "Category risk",
}


def _format_feature_value(feature: str, value: Any) -> str:
    """Return a short human-readable value for an auditor tooltip."""
    if value is None:
        return "not available"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)

    if feature in {"amount_mismatch_ratio", "vendor_anomaly_score", "duplicate_score"}:
        return f"{numeric:.0%}"
    if feature in {"is_weekend", "is_holiday", "has_amount_mismatch", "is_likely_duplicate",
                   "is_known_vendor", "is_round_amount", "split_transaction_flag"}:
        return "yes" if numeric >= 0.5 else "no"
    if feature in {"claim_frequency_7d", "claim_frequency_30d"}:
        return f"{numeric:.0f} claims"
    return f"{numeric:.2f}"


def _explanation_rows(prediction: FraudPrediction) -> list[dict[str, Any]]:
    """Build explainable reason rows from persisted SHAP and raw feature values."""
    shap_values = prediction.shap_values or {}
    feature_values = prediction.feature_values or {}
    if float(feature_values.get("_event_time_known", 0.0) or 0.0) < 0.5:
        # Historical date-only claims were once interpreted as midnight.
        shap_values = {name: impact for name, impact in shap_values.items()
                       if name not in {"hour", "is_after_hours"}}
    if not shap_values:
        # AE-only runs do not persist SHAP values. Keep the dashboard useful by
        # showing the strongest observed behavioral signals, clearly marked as
        # feature evidence rather than model attribution.
        candidates = []
        for feature, raw_value in feature_values.items():
            if feature.startswith("_") or raw_value is None:
                continue
            if feature in {"hour", "is_after_hours"} and float(feature_values.get("_event_time_known", 0.0) or 0.0) < 0.5:
                continue
            try:
                numeric = abs(float(raw_value))
            except (TypeError, ValueError):
                continue
            if feature in {"has_amount_mismatch", "is_likely_duplicate", "is_weekend", "is_holiday", "is_round_amount", "split_transaction_flag"}:
                strength = 1.0 if numeric >= 0.5 else 0.0
            elif feature in {"amount_mismatch_ratio", "vendor_anomaly_score", "category_risk_score"}:
                strength = min(numeric, 1.0)
            elif feature == "duplicate_score":
                strength = max(0.0, min(numeric, 1.0))
            elif feature == "amount_zscore":
                strength = min(numeric / 3.0, 1.0)
            elif feature in {"claim_frequency_7d", "claim_frequency_30d"}:
                strength = min(numeric / (3.0 if feature.endswith("7d") else 10.0), 1.0)
            else:
                strength = 0.0
            if strength > 0:
                candidates.append((feature, strength))
        shap_values = dict(sorted(candidates, key=lambda item: item[1], reverse=True)[:5])
        evidence_type = "feature signal"
    else:
        evidence_type = "SHAP attribution"
    rows = []
    for feature, raw_impact in sorted(shap_values.items(), key=lambda item: abs(item[1]), reverse=True):
        impact = float(raw_impact)
        if evidence_type == "feature signal":
            direction = "policy review signal" if feature == "is_holiday" else "feature signal present"
        else:
            direction = "increases anomaly evidence" if impact > 0 else "reduces anomaly evidence"
        rows.append({
            "feature": feature,
            "label": _FEATURE_LABELS.get(feature, feature.replace("_", " ").title()),
            "impact": round(impact, 6),
            "direction": direction,
            "value": feature_values.get(feature),
            "value_display": _format_feature_value(feature, feature_values.get(feature)),
            "evidence_type": evidence_type,
        })
    if float(feature_values.get("_holiday_policy_flag", 0.0) or 0.0) >= 0.5:
        rows.append({
            "feature": "holiday_policy",
            "label": "Holiday submission policy",
            "impact": 1.0,
            "direction": "requires policy review",
            "value": 1.0,
            "value_display": "yes",
            "evidence_type": "policy rule",
        })
    rows.sort(key=lambda row: abs(row["impact"]), reverse=True)
    return rows


@router.get('/model')
def model_status():
    artifacts = load_pipeline(config)
    if artifacts is None:
        return {'ready': False, 'message': 'Train the v3 behavioral model first.'}
    return {'ready': True, 'version': artifacts['version'],
            'feature_names': artifacts['feature_names'], 'metadata': artifacts['metadata']}


@router.get("/summary", response_model=Dict[str, Any])
def get_fraud_summary(db: Session = Depends(get_db)):
    """Get dashboard summary statistics."""
    total_claims = db.query(ExpenseClaim).count()
    if total_claims == 0:
        try:
            from backend.app.seed_loader import seed_initial_claims_data
            if seed_initial_claims_data(db):
                total_claims = db.query(ExpenseClaim).count()
        except Exception:
            pass

    if total_claims == 0:
        return {
            "total_claims": 0,
            "flagged_count": 0,
            "flagged_rate": 0.0,
            "fraud_rate": 0.0,
            "average_score": 0.0,
            "score_distribution": {},
            "recent_flagged": [],
            "fraud_over_time": [],
            "kpis": {
                "avg_time_to_disposition_seconds": 0.0,
                "false_positive_rate": 0.0,
                "total_disposed_cases": 0
            }
        }

    # Get predictions
    predictions = db.query(FraudPrediction).all()
    flagged_count = sum(1 for p in predictions if p.is_flagged)
    flagged_rate = (flagged_count / total_claims) * 100 if total_claims > 0 else 0.0

    scores = [p.combined_fraud_score for p in predictions if p.combined_fraud_score is not None]
    average_score = sum(scores) / len(scores) if scores else 0.0

    # Score distribution histogram (10 buckets from 0 to 1)
    distribution = {f"{i/10:.1f}-{i/10+0.1:.1f}": 0 for i in range(10)}
    for s in scores:
        bucket = min(int(s * 10), 9)
        distribution[f"{bucket/10:.1f}-{bucket/10+0.1:.1f}"] += 1

    # Recent flagged claims
    recent_flagged_db = (
        db.query(ExpenseClaim)
        .join(FraudPrediction)
        .filter(FraudPrediction.is_flagged == True)
        .order_by(FraudPrediction.predicted_at.desc())
        .limit(20) # Increase limit to support frontend filters
        .all()
    )
    
    # Import get_closest_vendor from claims to get typosquats dynamically
    from backend.app.api.claims import get_closest_vendor

    recent_flagged = []
    for c in recent_flagged_db:
        closest_match, match_ratio = get_closest_vendor(c.vendor_name)
        if match_ratio >= 1.0 or match_ratio < 0.70:
            closest_match = None
            match_ratio = 0.0
            
        top_reasons = _explanation_rows(c.prediction)
        recent_flagged.append({
            "id": c.id,
            "claim_id": c.claim_id,
            "vendor_name": c.vendor_name,
            "employee_name": c.employee_name,
            "claimed_amount": float(c.claimed_amount),
            "claimed_date": c.claimed_date.isoformat(),
            "fraud_score": c.prediction.combined_fraud_score,
            "status": c.status,
            "case_status": c.case.status if c.case else "none",
            "closest_vendor_match": closest_match,
            "vendor_similarity_score": match_ratio if closest_match else None,
            "dominant_reason": top_reasons[0]["label"] if top_reasons else "Model score only",
            "dominant_reason_detail": (
                f"{top_reasons[0]['label']} — {top_reasons[0]['direction']}"
                if top_reasons else "Model score only"
            ),
            "top_reasons": top_reasons,
        })

    # Aggregate contribution magnitude across all flagged predictions so
    # auditors can see recurring drivers behind the queue, not just one claim.
    reason_totals = defaultdict(lambda: {"flagged_claims": 0, "total_impact": 0.0, "positive_claims": 0})
    for prediction in predictions:
        if not prediction.is_flagged:
            continue
        seen_features = set()
        for reason in _explanation_rows(prediction):
            if reason["feature"] in seen_features:
                continue
            seen_features.add(reason["feature"])
            reason_totals[reason["feature"]]["flagged_claims"] += 1
            reason_totals[reason["feature"]]["total_impact"] += abs(reason["impact"])
            if reason["impact"] > 0:
                reason_totals[reason["feature"]]["positive_claims"] += 1

    reason_breakdown = []
    for feature, totals in reason_totals.items():
        reason_breakdown.append({
            "feature": feature,
            "label": _FEATURE_LABELS.get(feature, feature.replace("_", " ").title()),
            "flagged_claims": totals["flagged_claims"],
            "mean_impact": round(totals["total_impact"] / max(totals["flagged_claims"], 1), 4),
            "positive_claims": totals["positive_claims"],
        })
    reason_breakdown.sort(key=lambda item: (item["flagged_claims"], item["mean_impact"]), reverse=True)

    # Fraud over time (monthly count of flagged claims)
    time_series = defaultdict(lambda: {"total": 0, "flagged": 0})
    for c in db.query(ExpenseClaim).all():
        month = c.claimed_date.strftime("%Y-%m")
        time_series[month]["total"] += 1
        if c.prediction and c.prediction.is_flagged:
            time_series[month]["flagged"] += 1

    fraud_over_time = [
        {
            "date": month,
            "count": data["total"],
            "flagged_count": data["flagged"],
            "rate": round(data["flagged"] / data["total"] * 100, 1),
        }
        for month, data in sorted(time_series.items())
    ]

    # Fetch Case management cycle metrics (KPIs)
    kpis = get_case_cycle_metrics(db)

    return {
        "total_claims": total_claims,
        "flagged_count": flagged_count,
        "flagged_rate": round(flagged_rate, 2),
        "fraud_rate": round(flagged_rate, 2),  # Legacy response key.
        "average_score": round(average_score, 4),
        "score_distribution": distribution,
        "recent_flagged": recent_flagged,
        "explainability": {
            "score_semantics": "Anomaly index, not a fraud probability",
            "display_threshold": 0.5,
            "reason_breakdown": reason_breakdown[:8],
        },
        "fraud_over_time": fraud_over_time,
        "kpis": kpis
    }


@router.post("/train", status_code=status.HTTP_200_OK)
def train_models(trust_synthetic_labels: bool = False, db: Session = Depends(get_db),
                 user: AuthUser = Depends(require_roles("admin"))):
    """Train on reviewed normal cases, or explicitly trusted synthetic labels."""
    claims = db.query(ExpenseClaim).filter(~ExpenseClaim.claim_id.like('TXN%')).order_by(ExpenseClaim.submitted_at, ExpenseClaim.id).all()
    records = [claim_record(c) for c in claims]
    labels = [int(c.is_fraud) if trust_synthetic_labels else
              (0 if c.case and c.case.status == "closed_approved" else
               1 if c.case and c.case.status == "closed_rejected" else -1) for c in claims]
    try:
        artifacts = train_claims(records, labels, config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Scores from a newly trained bundle cannot reuse a previous bundle's cutoffs.
    STRATEGY_PATH.write_text(json.dumps({key:dict(threshold=.5,run_id=artifacts['metadata']['run_id'],
        basis='New model default; run the benchmark calibration before applying cohort cutoffs') for key in ('aster','original')},indent=2),encoding='utf-8')
    return {"status": "success", "message": "Behavioral v3 model trained with OCR and holiday-policy features.",
            "metadata": artifacts["metadata"]}


@router.post("/score", status_code=status.HTTP_200_OK)
def score_all_claims(rescore: bool = False, db: Session = Depends(get_db),
                     user: AuthUser = Depends(get_current_user)):
    """Score all unscored claims through the pipeline."""
    return score_selected_claims(db, user, rescore=rescore)


def score_selected_claims(db, user, rescore=False, claim_ids=None):
    """Use the unchanged model on selected upload IDs with full historical features."""
    if rescore and "admin" not in (user.roles or []):
        raise HTTPException(403, "Only an administrator can rescore existing claims.")
    pipeline = load_pipeline(config)
    if not pipeline:
        raise HTTPException(500, "Pipeline models not found. Please train first.")

    # Rebuild the complete historical ledger, then select targets in the same
    # order as ORM claims. Never compute history from only the pending subset.
    all_claims = db.query(ExpenseClaim).order_by(ExpenseClaim.submitted_at, ExpenseClaim.id).all()
    claims = [c for c in all_claims if (c.claim_id in claim_ids and c.status not in ("approved", "rejected"))] if claim_ids is not None else [c for c in all_claims if c.status in ("pending", "processing") or (c.status == "flagged" and c.prediction is None) or
              (rescore and c.status in ("scored", "flagged"))]
    all_claims = [c for c in all_claims if strategy(c.claim_id)['model_enabled']]
    claims = [c for c in claims if strategy(c.claim_id)['model_enabled']]
    if not claims:
        from backend.app.policy_service import run_checks
        run_checks(db, True)
        db.commit()
        return {"status": "success", "scored_count": 0, "flagged_count": 0}
    try:
        records = [claim_record(c) for c in all_claims]
        all_features, feature_names = compute_features_batch(records)
        by_id = {c.claim_id: f for c, f in zip(all_claims, all_features)}
        time_known_by_id = {c.claim_id: event_time_info(record)[1]
                            for c, record in zip(all_claims, records)}
        features_list = [by_id[c.claim_id] for c in claims]
        feature_matrix = np.asarray([[f[n] for n in feature_names] for f in features_list])
        results = score_claims(feature_matrix, pipeline, config)
        for claim, result in zip(claims, results):
            result['is_flagged'] = model_decision(claim.claim_id, result['combined_fraud_score'])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Holiday receipts are a policy exception: the rule flags them even when
    # the statistical model does not cross its anomaly threshold.
    holiday_indices = [
        i for i, features in enumerate(features_list)
        if float(features.get("is_holiday", 0.0)) >= 0.5
    ]
    flagged_indices = [i for i, result in enumerate(results) if result["is_flagged"]]
    family = pipeline.get('family', 'combined')
    explanation_model = pipeline.get('supervised') if family == 'supervised' else pipeline['isolation_forest']
    shap_results = [] if family == 'ae' else compute_shap_values(
        explanation_model, transform_features(feature_matrix, pipeline),
        feature_names, claim_indices=flagged_indices)

    # Save to DB
    flagged_count = 0
    shap_idx = 0
    
    for i, claim in enumerate(claims):
        res = results[i]
        holiday_policy_flag = i in holiday_indices
        is_flagged = bool(res["is_flagged"] or holiday_policy_flag)
        if is_flagged:
            flagged_count += 1
            
        shap_vals = {}
        if res["is_flagged"] and shap_idx < len(shap_results):
            # Convert full shap dict to top 5
            top_features = get_top_features(shap_results[shap_idx], top_n=5)
            shap_vals = {f["feature"]: f["value"] for f in top_features}
            shap_idx += 1

        # Flush replacement to satisfy the unique claim_id constraint.
        if claim.prediction:
            db.delete(claim.prediction)
            db.flush()
        if (rescore or claim_ids is not None) and claim.audit_report:
            # A generated report cites the previous score and evidence. It is
            # safer to require regeneration after a model or policy rescore.
            db.delete(claim.audit_report)
            db.flush()

        pred = FraudPrediction(
            claim_id=claim.claim_id,
            reconstruction_error=res["reconstruction_error"],
            isolation_forest_score=res["isolation_forest_score"],
            combined_fraud_score=res["combined_fraud_score"],
            is_flagged=is_flagged,
            shap_values=shap_vals if is_flagged else None,
            feature_values={**features_list[i], '_model_version': 3,
                            '_model_run_id': pipeline.get('metadata', {}).get('run_id'),
                            '_model_threshold': strategy(claim.claim_id)['threshold'],
                            '_model_enabled': strategy(claim.claim_id)['model_enabled'],
                            '_event_time_known': float(time_known_by_id[claim.claim_id]),
                            '_holiday_policy_flag': float(holiday_policy_flag),
                            '_supervised_score': float(family == 'supervised')},
        )
        db.add(pred)
        
        claim.status = "flagged" if is_flagged else "scored"

        # Create Case & Audit Trail if flagged
        if is_flagged:
            # Check if case already exists to prevent duplicate entries
            case = db.query(Case).filter(Case.claim_id == claim.claim_id).first()
            if not case:
                case = Case(
                    claim_id=claim.claim_id,
                    status="open",
                )
                db.add(case)
                db.flush() # Flush to get case.id
                
                trail = CaseAuditTrail(
                    case_id=case.id,
                    action="created",
                    performed_by="system",
                    notes=f"Review signal: model={res['is_flagged']}, holiday policy={holiday_policy_flag}; score={res['combined_fraud_score']:.4f}; cutoff={strategy(claim.claim_id)['threshold']:.8f}"
                )
                db.add(trail)
            elif case.status == "cancelled_unflagged":
                case.status = "open"
                db.add(CaseAuditTrail(
                    case_id=case.id,
                    action="reopened_after_rescore",
                    performed_by="system",
                    notes="The refreshed score or holiday rule flagged this claim again.",
                ))
        else:
            case = db.query(Case).filter(Case.claim_id == claim.claim_id).first()
            if case and case.status == "open" and not case.maker_id and not case.checker_id:
                case.status = "cancelled_unflagged"
                db.add(CaseAuditTrail(
                    case_id=case.id,
                    action="cancelled_after_rescore",
                    performed_by="system",
                    notes="The refreshed score no longer flags this claim; no reviewer had acted.",
                ))

    from backend.app.policy_service import run_checks
    run_checks(db,True)
    flagged_count = sum(c.status in ('flagged','processing') for c in claims)
    db.commit()

    return {
        "status": "success", 
        "scored_count": len(claims), 
        "flagged_count": flagged_count,
        "model_version": 3,
        "display_threshold": 0.5,
        "explanation_scope": 'supervised model SHAP' if family == 'supervised' else 'Isolation Forest component SHAP (absent for AE-only)'
    }
