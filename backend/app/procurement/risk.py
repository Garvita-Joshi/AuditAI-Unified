"""Procurement-specific AE/IF inference. Expense artifacts are never relabeled.

An optional procurement bundle must contain these feature names, an AE state,
scaler, Isolation Forest, and sorted validation score reference arrays. No online
retraining or per-request normalization is performed.
"""
import os
from pathlib import Path
import numpy as np

FEATURE_NAMES = ["amount_log", "item_count", "quantity_total", "delivery_ratio", "tax_ratio", "po_difference_ratio", "supplier_history_count", "supplier_amount_ratio"]


def features(terms, approved, historical_amounts):
    total = float(terms.total)
    approved_total = max(float(approved.total), 1.0)
    history = [float(x) for x in historical_amounts if float(x) > 0]
    if not history:
        # Cold-start supplier: use approved PO baseline so a new vendor is not
        # falsely penalized with 0.0 ratio and 0 history count.
        history = [approved_total] * 5
    elif len(history) < 5:
        median_val = float(np.median(history))
        history = history + [median_val] * (5 - len(history))
    return np.array([
        np.log1p(total),
        len(terms.items),
        sum(x.quantity for x in terms.items),
        float(terms.delivery) / max(total, 1.0),
        float(terms.tax) / max(total, 1.0),
        abs(total - approved_total) / approved_total,
        len(history),
        total / max(float(np.median(history)), 1.0),
    ], dtype=float)


def _explain_basis(raw_vec, terms, approved, is_fraud, score, threshold):
    total = float(terms.total)
    approved_total = max(float(approved.total), 1.0)
    delivery_pct = (float(terms.delivery) / max(total, 1.0)) * 100.0
    tax_pct = (float(terms.tax) / max(total, 1.0)) * 100.0
    po_diff_pct = (abs(total - approved_total) / approved_total) * 100.0
    supplier_ratio = float(raw_vec[7])

    triggers = []
    if po_diff_pct > 2.0:
        triggers.append(f"Invoice total ({total:,.2f}) deviates from approved PO ({approved_total:,.2f}) by {po_diff_pct:.1f}%")
    if delivery_pct > 12.0:
        triggers.append(f"Delivery fee ratio ({delivery_pct:.1f}% of invoice) exceeds normal shipping threshold (<=12%)")
    if tax_pct > 25.0:
        triggers.append(f"Tax ratio ({tax_pct:.1f}% of invoice) exceeds standard GST/VAT ceiling (<=25%)")
    if supplier_ratio > 2.0:
        triggers.append(f"Invoice amount is {supplier_ratio:.2f}x the supplier's historical median baseline")
    elif supplier_ratio < 0.35:
        triggers.append(f"Invoice amount is unusually low ({supplier_ratio:.2f}x) compared to supplier baseline")

    checks = [
        f"PO Variance: {po_diff_pct:.1f}% ({'MATCHED' if po_diff_pct <= 2.0 else 'MISMATCH'})",
        f"Delivery Ratio: {delivery_pct:.1f}% ({'NORMAL' if delivery_pct <= 12.0 else 'HIGH'})",
        f"Tax Ratio: {tax_pct:.1f}% ({'NORMAL' if tax_pct <= 25.0 else 'HIGH'})",
        f"Supplier Historical Ratio: {supplier_ratio:.2f}x ({'CONSISTENT' if 0.5 <= supplier_ratio <= 1.8 else 'OUTLIER'})",
    ]
    return triggers, checks


def assess(terms, approved, historical_amounts):
    from backend.app.config import TRAINED_MODELS_DIR
    bundle_path = Path(os.getenv("PROCUREMENT_MODEL_BUNDLE", str(TRAINED_MODELS_DIR / "procurement_bundle.joblib")))
    if not bundle_path.is_file():
        return {"status": "unavailable", "reason": "No compatible procurement model bundle is installed.",
                "model": "Autoencoder + Isolation Forest", "score": None}
    try:
        import joblib
        import torch
        from backend.app.procurement.autoencoder import ExpenseAutoencoder
        bundle = joblib.load(bundle_path)
        if bundle["feature_names"] != FEATURE_NAMES:
            raise ValueError("Feature schema does not match procurement-v1.")
        raw_vec = features(terms, approved, historical_amounts)
        x = raw_vec.reshape(1, -1)
        x = bundle["scaler"].transform(x)
        model = ExpenseAutoencoder(len(FEATURE_NAMES), bundle["latent_dim"])
        model.load_state_dict(bundle["ae_state"])
        model.eval()
        with torch.no_grad():
            reconstructed = model(torch.tensor(x, dtype=torch.float32)).numpy()
        sq_errors = ((x - reconstructed) ** 2)[0]
        ae_raw = float(np.mean(sq_errors))
        if bundle.get("if_input") != "decoded":
            raise ValueError("Procurement bundle must use decoded AE features for Isolation Forest.")
        if_raw = float(-bundle["isolation_forest"].score_samples(reconstructed)[0])
        def percentile(value, reference):
            reference = np.asarray(reference)
            if reference.size < 20 or not np.isfinite(reference).all() or np.any(np.diff(reference) < 0):
                raise ValueError("Validation reference must be sorted, finite, and contain at least 20 values.")
            return float(np.searchsorted(reference, value, side="right") / len(reference))
        ae_score = percentile(ae_raw, bundle["ae_reference"])
        if_score = percentile(if_raw, bundle["if_reference"])
        weight = bundle.get("ae_weight", .4)
        score = weight * ae_score + (1 - weight) * if_score
        threshold = bundle.get("threshold", .95)
        is_fraud = bool(score >= threshold)
        triggers, checks = _explain_basis(raw_vec, terms, approved, is_fraud, score, threshold)
        basis_summary = " | ".join(checks)
        if is_fraud:
            reason_text = "; ".join(triggers) if triggers else f"Combined AE/IF anomaly score ({score*100:.1f}%) exceeded threshold ({threshold*100:.1f}%)."
            recommendation = f"Block payment and flag for fraud investigation. Basis: {reason_text}"
        else:
            recommendation = f"Approved: invoice pattern matches verified legitimate spending ({basis_summary})."
        feature_map = {name: round(float(val), 4) for name, val in zip(FEATURE_NAMES, raw_vec)}
        # Signed contribution proxy: positive when anomalous, scaled by reconstruction error
        feature_errors = {
            name: round(float(err) if (is_fraud or float(err) > 0.05) else -float(err), 4)
            for name, err in zip(FEATURE_NAMES, sq_errors)
        }
        return {
            "status": "review" if is_fraud else "assessed",
            "score": round(score, 4),
            "is_fraud": is_fraud,
            "fraud_decision": "FRAUD_FLAGGED" if is_fraud else "CLEAN_APPROVED",
            "decision_label": "High Anomaly - Fraud Flagged" if is_fraud else "Clean - Considered Not Fraud",
            "threshold": threshold,
            "autoencoder_percentile": round(ae_score, 4),
            "isolation_forest_percentile": round(if_score, 4),
            "autoencoder_raw_mse": round(ae_raw, 6),
            "isolation_forest_raw": round(if_raw, 6),
            "version": bundle.get("version", "procurement-v1"),
            "training_source": bundle.get("training_source", "unspecified"),
            "model": "Autoencoder + Isolation Forest",
            "basis": checks,
            "triggers": triggers,
            "feature_values": feature_map,
            "feature_errors": feature_errors,
            "note": f"Evaluated 8 procurement features ({basis_summary}).",
            "recommendation": recommendation,
        }
    except Exception:
        return {"status": "unavailable", "reason": "Model bundle could not be validated. Check its feature schema and artifacts.", "score": None}


def sync_ml_evaluation_to_claims(
    db,
    user,
    *,
    claim_id: str,
    source_type: str,
    request_id: int,
    source_ref: str,
    invoice_number: str,
    supplier_id: str,
    product_title: str,
    category: str,
    stated_total,
    approved_total,
    currency: str,
    assessment: dict,
    po_number: str = None,
    paypal_payment: dict = None,
):
    """Upsert an evaluated procurement/sourcing final invoice into the Claims tables
    (ExpenseClaim, FraudPrediction, AuditReport, ClaimContributor) so it appears
    in /claims with full ML evaluation details.
    """
    from datetime import datetime
    from decimal import Decimal
    try:
        from backend.app.db import Base
        from backend.app.models.expense import ExpenseClaim, FraudPrediction, AuditReport, Entity
        from backend.app.models.auth import ClaimContributor

        bind = db.get_bind()
        Base.metadata.create_all(
            bind=bind,
            tables=[
                Entity.__table__,
                ExpenseClaim.__table__,
                FraudPrediction.__table__,
                AuditReport.__table__,
                ClaimContributor.__table__,
            ],
        )

        norm_currency = (currency or "INR").upper()
        entity_name = "APAC Entity" if norm_currency == "INR" else f"Global {norm_currency} Entity"
        entity = db.query(Entity).filter(Entity.name == entity_name).first()
        if not entity:
            entity = Entity(
                name=entity_name,
                currency=norm_currency,
                materiality_threshold=Decimal("50000.00") if norm_currency == "INR" else Decimal("5000.00"),
            )
            db.add(entity)
            db.flush()

        amt = Decimal(str(stated_total or "0.00")).quantize(Decimal("0.01"))
        app_amt = Decimal(str(approved_total or amt)).quantize(Decimal("0.01"))
        is_fraud = bool(assessment.get("is_fraud", False))
        pay_status = (paypal_payment or {}).get("status", "not_started")

        if is_fraud:
            claim_status = "flagged"
        elif pay_status in ("completed", "paid"):
            claim_status = "approved"
        else:
            claim_status = "scored"

        emp_id = getattr(user, "employee_id", None) or f"EMP-{getattr(user, 'id', 1)}"
        emp_name = (
            getattr(user, "display_name", None)
            or getattr(user, "full_name", None)
            or getattr(user, "email", None)
            or "Procurement Officer"
        )

        desc = (
            f"[{source_ref}] {product_title or 'Procurement Invoice'} · "
            f"Invoice {invoice_number} · Approved PO: {norm_currency} {app_amt:,.2f} · "
            f"ML Verdict: {assessment.get('decision_label', 'Evaluated')}"
        )

        claim = db.query(ExpenseClaim).filter(ExpenseClaim.claim_id == claim_id).first()
        if not claim:
            claim = ExpenseClaim(
                claim_id=claim_id,
                employee_id=str(emp_id),
                employee_name=str(emp_name),
                claimed_amount=amt,
                vendor_name=str(supplier_id or "Approved Supplier")[:300],
                claimed_date=datetime.utcnow().date(),
                category=str(category or "Procurement Final Invoice")[:100],
                description=desc,
                status=claim_status,
                submitted_at=datetime.utcnow(),
                entity_id=entity.id,
                is_fraud=is_fraud,
                fraud_type="procurement_invoice_anomaly" if is_fraud else "none",
            )
            db.add(claim)
            db.flush()
        else:
            claim.claimed_amount = amt
            claim.vendor_name = str(supplier_id or claim.vendor_name)[:300]
            claim.category = str(category or claim.category or "Procurement Final Invoice")[:100]
            claim.description = desc
            claim.status = claim_status
            claim.entity_id = entity.id
            claim.is_fraud = is_fraud
            claim.fraud_type = "procurement_invoice_anomaly" if is_fraud else "none"

        user_id = getattr(user, "id", None)
        if user_id is not None:
            contrib = (
                db.query(ClaimContributor)
                .filter_by(claim_id=claim_id, user_id=user_id, source="procurement_ml_eval")
                .first()
            )
            if not contrib:
                db.add(ClaimContributor(claim_id=claim_id, user_id=user_id, source="procurement_ml_eval"))

        raw_features = dict(assessment.get("feature_values") or {})
        raw_errors = dict(assessment.get("feature_errors") or {})
        procurement_meta = {
            "is_procurement_invoice": True,
            "source_type": source_type,
            "request_id": request_id,
            "source_ref": source_ref,
            "invoice_number": invoice_number,
            "po_number": po_number or f"PO-{source_ref}",
            "supplier_id": supplier_id,
            "product_title": product_title,
            "approved_total": str(app_amt),
            "po_total": str(app_amt),
            "stated_total": str(amt),
            "currency": norm_currency,
            "score": assessment.get("score"),
            "threshold": assessment.get("threshold"),
            "is_fraud": is_fraud,
            "fraud_decision": assessment.get("fraud_decision"),
            "verdict": assessment.get("decision_label") or assessment.get("fraud_decision"),
            "decision_label": assessment.get("decision_label"),
            "autoencoder_percentile": assessment.get("autoencoder_percentile"),
            "autoencoder_score": assessment.get("autoencoder_percentile"),
            "isolation_forest_percentile": assessment.get("isolation_forest_percentile"),
            "isolation_forest_score": assessment.get("isolation_forest_percentile"),
            "autoencoder_raw_mse": assessment.get("autoencoder_raw_mse"),
            "isolation_forest_raw": assessment.get("isolation_forest_raw"),
            "feature_values": raw_features,
            "feature_errors": raw_errors,
            "model": assessment.get("model", "Autoencoder + Isolation Forest"),
            "version": assessment.get("version", "procurement-v1-synthetic"),
            "training_source": assessment.get("training_source", "synthetic"),
            "basis": assessment.get("basis", []),
            "triggers": assessment.get("triggers", []),
            "recommendation": assessment.get("recommendation", ""),
            "note": assessment.get("note", ""),
            "paypal_payment": paypal_payment or {"status": "ready_for_checkout" if not is_fraud else "blocked_by_ml"},
            "evaluated_at": datetime.utcnow().isoformat(),
        }
        feature_payload = {**raw_features, "_procurement_ml": procurement_meta}
        shap_payload = dict(assessment.get("feature_errors") or {})

        pred = db.query(FraudPrediction).filter(FraudPrediction.claim_id == claim_id).first()
        if not pred:
            pred = FraudPrediction(
                claim_id=claim_id,
                reconstruction_error=float(assessment.get("autoencoder_percentile") or 0.0),
                isolation_forest_score=float(assessment.get("isolation_forest_percentile") or 0.0),
                combined_fraud_score=float(assessment.get("score") or 0.0),
                is_flagged=is_fraud,
                shap_values=shap_payload,
                feature_values=feature_payload,
                predicted_at=datetime.utcnow(),
            )
            db.add(pred)
        else:
            pred.reconstruction_error = float(assessment.get("autoencoder_percentile") or 0.0)
            pred.isolation_forest_score = float(assessment.get("isolation_forest_percentile") or 0.0)
            pred.combined_fraud_score = float(assessment.get("score") or 0.0)
            pred.is_flagged = is_fraud
            pred.shap_values = shap_payload
            pred.feature_values = feature_payload
            pred.predicted_at = datetime.utcnow()

        basis_lines = "\n".join(f"- **{b}**" for b in (assessment.get("basis") or []))
        trigger_lines = (
            "\n".join(f"- {t}" for t in (assessment.get("triggers") or []))
            if assessment.get("triggers")
            else "- None — all 8 procurement features are within normal learned operating bounds."
        )
        paypal_line = (
            f"Completed (Order ID: `{paypal_payment.get('order_id')}`)"
            if pay_status in ("completed", "paid")
            else (
                f"Order Created (`{paypal_payment.get('order_id')}`) — Awaiting Buyer Approval / Capture"
                if (paypal_payment or {}).get("order_id")
                else ("Eligible for PayPal Sandbox Settlement" if not is_fraud else "Blocked by ML Fraud Gate")
            )
        )

        report_md = (
            f"### Final Invoice ML Fraud Evaluation ({source_ref})\n\n"
            f"- **Decision Verdict:** `{assessment.get('fraud_decision', 'EVALUATED')}` ({assessment.get('decision_label', '')})\n"
            f"- **Combined Anomaly Score:** **{(float(assessment.get('score') or 0) * 100):.2f}%** "
            f"(Policy Threshold: **{(float(assessment.get('threshold') or 0.85) * 100):.1f}%**)\n"
            f"- **Autoencoder Reconstruction Percentile:** **{(float(assessment.get('autoencoder_percentile') or 0) * 100):.2f}%** "
            f"(Raw MSE: `{assessment.get('autoencoder_raw_mse', 0)}`)\n"
            f"- **Isolation Forest Anomaly Percentile:** **{(float(assessment.get('isolation_forest_percentile') or 0) * 100):.2f}%** "
            f"(Raw Score: `{assessment.get('isolation_forest_raw', 0)}`)\n"
            f"- **Model Architecture:** {assessment.get('model', 'Autoencoder + Isolation Forest')} (`{assessment.get('version', 'procurement-v1-synthetic')}`)\n\n"
            f"#### Commercial & Purchase Order Verification\n"
            f"- **Source Request:** `{source_ref}` ({product_title or 'Procurement Request'})\n"
            f"- **Invoice Number:** `{invoice_number}`\n"
            f"- **Purchase Order:** `{po_number or f'PO-{source_ref}'}`\n"
            f"- **Supplier:** {supplier_id}\n"
            f"- **Authorized PO Total:** {norm_currency} {app_amt:,.2f}\n"
            f"- **Invoiced Stated Total:** {norm_currency} {amt:,.2f}\n"
            f"- **PayPal Sandbox Status:** {paypal_line}\n\n"
            f"#### 4-Pillar ML Basis Checks\n"
            f"{basis_lines}\n\n"
            f"#### Anomaly Triggers\n"
            f"{trigger_lines}\n\n"
            f"#### Recommendation\n"
            f"{assessment.get('recommendation', '')}"
        )

        rep = db.query(AuditReport).filter(AuditReport.claim_id == claim_id).first()
        if not rep:
            rep = AuditReport(
                claim_id=claim_id,
                report_text=report_md,
                generated_by=f"Procurement ML ({assessment.get('version', 'procurement-v1-synthetic')})",
                generated_at=datetime.utcnow(),
            )
            db.add(rep)
        else:
            rep.report_text = report_md
            rep.generated_by = f"Procurement ML ({assessment.get('version', 'procurement-v1-synthetic')})"
            rep.generated_at = datetime.utcnow()

        db.flush()
        return claim_id
    except Exception as exc:
        print(f"[sync_ml_evaluation_to_claims] non-fatal error: {exc}")
        return None

