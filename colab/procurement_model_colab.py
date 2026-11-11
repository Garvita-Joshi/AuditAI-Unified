# AuditAI - Procurement Fraud Model (standalone, Colab-ready)
# ----------------------------------------------------------
# Same design as the app: 8 invoice features -> Autoencoder (PyTorch) -> Isolation Forest on the
# DECODED output -> percentile-calibrated combined score -> threshold.
#
# Colab: paste into a cell (or upload and `%run`). Needs only: numpy, scikit-learn, torch, joblib, pandas
#   !pip -q install torch scikit-learn joblib pandas
#
# The produced `procurement_bundle.joblib` has the exact keys backend/app/procurement/risk.py expects, so
# you can drop it into backend/trained_models/ (or set PROCUREMENT_MODEL_BUNDLE) after testing.

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, MinMaxScaler, StandardScaler

SEED = 42
MAX_FALSE_ALARM = 0.03   # max share of genuine invoices we accept blocking
rng = np.random.default_rng(SEED)
torch.manual_seed(SEED)

FEATURE_NAMES = ["amount_log", "item_count", "quantity_total", "delivery_ratio", "tax_ratio",
                 "po_difference_ratio", "supplier_history_count", "supplier_amount_ratio"]


# ----------------------------------------------------------------------------------------------
# 1. Synthetic invoice generator (legitimate + 5 fraud patterns)
# ----------------------------------------------------------------------------------------------
def make_invoice(fraud=None):
    """Return the 8 raw features for one invoice. fraud in {None,'po_mismatch','delivery_padding',
    'tax_inflation','amount_spike','unusually_low'}."""
    items = int(rng.integers(1, 6))
    qty = int(rng.integers(1, 40)) * items
    unit = float(rng.lognormal(mean=8.5, sigma=0.8))          # ~5k median per unit
    approved = max(unit * qty, 1000.0)
    history = rng.normal(approved, approved * 0.08, size=int(rng.integers(5, 25))).clip(min=100)

    delivery = approved * rng.uniform(0.0, 0.06)
    tax = approved * rng.choice([0.0, 0.05, 0.12, 0.18], p=[.05, .1, .2, .65])
    total = approved + delivery + tax
    total *= rng.normal(1.0, 0.004)                           # tiny rounding noise (matches PO)
    approved_total = approved + delivery + tax                # approved PO includes the same lines

    if fraud == "po_mismatch":
        total = approved_total * rng.uniform(1.12, 1.9)
    elif fraud == "delivery_padding":
        delivery = approved * rng.uniform(0.25, 0.6)
        total = approved + delivery + tax
    elif fraud == "tax_inflation":
        tax = approved * rng.uniform(0.35, 0.8)
        total = approved + delivery + tax
    elif fraud == "amount_spike":
        total = approved_total = float(np.median(history)) * rng.uniform(3.5, 9)
    elif fraud == "unusually_low":
        total = approved_total = float(np.median(history)) * rng.uniform(0.05, 0.25)

    total = float(total); approved_total = max(float(approved_total), 1.0)
    return np.array([
        np.log1p(total),
        items,
        qty,
        delivery / max(total, 1.0),
        tax / max(total, 1.0),
        abs(total - approved_total) / approved_total,
        len(history),
        total / max(float(np.median(history)), 1.0),
    ], dtype=float)


def make_dataset(n_normal, n_fraud_each=0):
    X, y, kind = [], [], []
    for _ in range(n_normal):
        X.append(make_invoice()); y.append(0); kind.append("legit")
    for k in ["po_mismatch", "delivery_padding", "tax_inflation", "amount_spike", "unusually_low"]:
        for _ in range(n_fraud_each):
            X.append(make_invoice(k)); y.append(1); kind.append(k)
    return np.array(X), np.array(y), np.array(kind)


# ----------------------------------------------------------------------------------------------
# 2. Model (identical architecture to backend/app/procurement/autoencoder.py)
# ----------------------------------------------------------------------------------------------
class ExpenseAutoencoder(nn.Module):
    def __init__(self, input_dim, latent_dim=16):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(input_dim, 64), nn.ReLU(), nn.Linear(64, 32), nn.ReLU(),
                                     nn.Linear(32, latent_dim), nn.ReLU())
        self.decoder = nn.Sequential(nn.Linear(latent_dim, 32), nn.ReLU(), nn.Linear(32, 64), nn.ReLU(),
                                     nn.Linear(64, input_dim), nn.Sigmoid())

    def forward(self, x):
        return self.decoder(self.encoder(x))


def make_scaler():
    # Standardise -> clip outliers -> squeeze to [0,1] (decoder ends in a sigmoid).
    # Built only from sklearn/numpy objects so it unpickles inside the app.
    return Pipeline([
        ("std", StandardScaler()),
        ("clip", FunctionTransformer(np.clip, kw_args={"a_min": -5, "a_max": 5})),
        ("minmax", MinMaxScaler(feature_range=(0.0, 1.0), clip=True)),
    ])


def reconstruct(model, x01):
    model.eval()
    with torch.no_grad():
        return model(torch.tensor(x01, dtype=torch.float32)).numpy()


def raw_scores(model, iforest, scaler, X):
    x01 = scaler.transform(X)
    rec = reconstruct(model, x01)
    ae_raw = ((x01 - rec) ** 2).mean(axis=1)
    if_raw = -iforest.score_samples(rec)           # IF runs on the decoded features
    return ae_raw, if_raw, x01, rec


def percentile(values, reference):
    return np.searchsorted(reference, values, side="right") / len(reference)


# ----------------------------------------------------------------------------------------------
# 3. Train
# ----------------------------------------------------------------------------------------------
def train(n_train=6000, n_val=1500, n_test_normal=1500, n_test_fraud_each=150,
          latent_dim=4, epochs=150, batch=128, lr=1e-3, ae_weight=0.85):
    X_train, _, _ = make_dataset(n_train)                 # legit only: unsupervised
    X_val, _, _ = make_dataset(n_val)                     # legit only: calibration reference
    X_cal, y_cal, _ = make_dataset(n_val // 3, n_fraud_each=n_val // 15)  # labelled: pick threshold
    X_test, y_test, kind_test = make_dataset(n_test_normal, n_test_fraud_each)

    scaler = make_scaler().fit(X_train)
    x_train = torch.tensor(scaler.transform(X_train), dtype=torch.float32)
    model = ExpenseAutoencoder(len(FEATURE_NAMES), latent_dim)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()
    n = len(x_train)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, batch):
            xb = x_train[perm[i:i + batch]]
            opt.zero_grad()
            loss = loss_fn(model(xb), xb)
            loss.backward(); opt.step()
            total += loss.item() * len(xb)
        if ep == 0 or (ep + 1) % 20 == 0:
            print(f"epoch {ep + 1:3d}/{epochs}  loss={total / n:.6f}")

    # Isolation Forest is fitted on the autoencoder's DECODED output of normal data.
    rec_train = reconstruct(model, scaler.transform(X_train))
    iforest = IsolationForest(n_estimators=300, contamination="auto", random_state=SEED).fit(rec_train)

    # Validation reference arrays (sorted) -> percentile calibration, as the app expects.
    ae_v, if_v, _, _ = raw_scores(model, iforest, scaler, X_val)
    ae_ref, if_ref = np.sort(ae_v), np.sort(if_v)

    def combined(X):
        ae, iff, _, _ = raw_scores(model, iforest, scaler, X)
        return ae_weight * percentile(ae, ae_ref) + (1 - ae_weight) * percentile(iff, if_ref)

    # Threshold chosen on the labelled calibration set (best F1), never on the test set.
    s_cal = combined(X_cal)
    grid = np.linspace(0.5, 0.995, 100)
    legit = s_cal[y_cal == 0]
    # Business rule: best F1 while wrongly blocking at most MAX_FALSE_ALARM of genuine invoices.
    ok_grid = [t for t in grid if (legit >= t).mean() <= MAX_FALSE_ALARM] or [grid[-1]]
    threshold = float(max(ok_grid, key=lambda t: f1_score(y_cal, s_cal >= t)))

    bundle = {
        "feature_names": FEATURE_NAMES, "scaler": scaler, "latent_dim": latent_dim,
        "ae_state": model.state_dict(), "if_input": "decoded", "isolation_forest": iforest,
        "ae_reference": ae_ref, "if_reference": if_ref, "ae_weight": ae_weight,
        "threshold": threshold, "version": "procurement-colab-v1",
        "training_source": "synthetic legit invoices (unsupervised AE+IF)",
    }

    # ---- evaluation on a held-out labelled test set ----
    s_test = combined(X_test)
    pred = (s_test >= threshold).astype(int)
    print("\n=== Held-out test ===")
    print(f"threshold={threshold:.3f}  ROC-AUC={roc_auc_score(y_test, s_test):.4f}  "
          f"PR-AUC={average_precision_score(y_test, s_test):.4f}")
    print(f"precision={precision_score(y_test, pred):.3f}  recall={recall_score(y_test, pred):.3f}  "
          f"F1={f1_score(y_test, pred):.3f}")
    tn, fp, fn, tp = confusion_matrix(y_test, pred).ravel()
    print(f"TP={tp} FP={fp} TN={tn} FN={fn}   false-alarm rate on legit={fp / (fp + tn):.3%}")
    per_kind = pd.DataFrame({"kind": kind_test, "flagged": pred}).groupby("kind")["flagged"].mean().round(3)
    print("\nFlag rate per invoice type (legit should be ~0, frauds ~1):\n", per_kind.to_string())
    return bundle, (model, iforest, scaler, ae_ref, if_ref, ae_weight, threshold)


# ----------------------------------------------------------------------------------------------
# 4. Score a single invoice (mirrors backend risk.assess)
# ----------------------------------------------------------------------------------------------
def invoice_features(total, approved_total, items, quantity, delivery, tax, history):
    history = [h for h in history if h > 0] or [max(approved_total, 1.0)] * 5
    if len(history) < 5:
        history = history + [float(np.median(history))] * (5 - len(history))
    return np.array([np.log1p(total), items, quantity, delivery / max(total, 1.0), tax / max(total, 1.0),
                     abs(total - approved_total) / max(approved_total, 1.0), len(history),
                     total / max(float(np.median(history)), 1.0)], dtype=float)


def assess(bundle, vec):
    scaler, thr = bundle["scaler"], bundle["threshold"]
    model = ExpenseAutoencoder(len(FEATURE_NAMES), bundle["latent_dim"])
    model.load_state_dict(bundle["ae_state"])
    ae, iff, x01, rec = raw_scores(model, bundle["isolation_forest"], scaler, vec.reshape(1, -1))
    ae_p = float(percentile(ae, bundle["ae_reference"])[0])
    if_p = float(percentile(iff, bundle["if_reference"])[0])
    w = bundle["ae_weight"]
    score = w * ae_p + (1 - w) * if_p
    return {
        "verdict": "FRAUD_FLAGGED" if score >= thr else "CLEAN_APPROVED",
        "score": round(score, 4), "threshold": round(thr, 4),
        "autoencoder_percentile": round(ae_p, 4), "autoencoder_raw_mse": round(float(ae[0]), 6),
        "isolation_forest_percentile": round(if_p, 4), "isolation_forest_raw": round(float(iff[0]), 6),
        "per_feature_error": {n: round(float(e), 4) for n, e in zip(FEATURE_NAMES, ((x01 - rec) ** 2)[0])},
    }


if __name__ == "__main__":
    bundle, _ = train()
    joblib.dump(bundle, "procurement_bundle.joblib")
    print("\nSaved procurement_bundle.joblib")

    print("\n=== Demo invoices ===")
    # Matches its PO, 18% GST, small shipping, consistent with supplier history -> expect CLEAN
    ok = invoice_features(total=236_000, approved_total=236_000, items=2, quantity=20,
                          delivery=4_000, tax=36_000, history=[228_000, 240_000, 235_000, 233_000, 238_000, 231_000])
    print("legit  :", assess(bundle, ok)["verdict"], assess(bundle, ok)["score"])
    # 60% above the approved PO, padded delivery -> expect FRAUD
    bad = invoice_features(total=380_000, approved_total=236_000, items=2, quantity=20,
                           delivery=110_000, tax=36_000, history=[228_000, 240_000, 235_000])
    print("padded :", assess(bundle, bad)["verdict"], assess(bundle, bad)["score"])
    print(assess(bundle, bad))
