# AuditAI Unified

Expense auditing and procurement integrated using AuditAI’s orange-and-black interface.

See [integration status and setup](docs/UNIFIED_INTEGRATION.md). Start with a new database; existing company data and credentials are not migrated.

The procurement calling extension now has a [Phase 2 backend foundation](docs/VOICE_AGENT_PHASE_2.md): owner-scoped call drafts, quotation fields, transcripts and audit history. Live calls remain disabled.

Validation after AuditAI upstream refresh `8c62504`: **149 backend tests passed, 3 skipped; 21 frontend tests passed**. Frontend production build passed.

---

# AuditAI

> **AI-powered financial fraud detection system for enterprise audit teams.**

AuditAI is a full-stack financial anomaly detection platform built for audit firms, banks, and large corporates. It combines OCR receipt parsing, a two-stage ML pipeline (PyTorch Autoencoder + Scikit-learn Isolation Forest), SHAP explainability, and Gemini-powered audit report generation into a single, demoable v1.

---

## 🚀 Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI (Python) |
| **Frontend** | React + Vite |
| **Database** | PostgreSQL |
| **ML** | PyTorch (Autoencoder), Scikit-learn (Isolation Forest), SHAP |
| **OCR** | RapidOCR CPU (primary), optional PaddleOCR/Tesseract fallbacks |
| **LLM** | Google Gemini API |

---

## Model update

The active detector uses prior-only behavioral features, independent Autoencoder and Isolation Forest models, frozen score calibration, and local receipt OCR. See [model v2 setup and validation](docs/model-v2.md).

## Company login and review roles

Employees, makers, and checkers sign in with a provisioned company email and password. The demo domain is `auditai.example`; set `COMPANY_EMAIL_DOMAINS=yourcompany.com` in `.env` before provisioning real accounts. There is no public sign-up or role selector at login. Create accounts from a trusted local terminal with `python scripts/provision_user.py --email name@yourcompany.com --employee-id EMP014 --roles employee,maker`. The script prompts for a password without echoing it.

For a deployed frontend, set `FRONTEND_ORIGINS` to its exact URL (or a comma-separated list of approved URLs) so browser requests can reach the API.

For local testing, run `python scripts/seed_demo_accounts.py`. It writes randomly generated passwords to the ignored file `scripts/artifacts/demo-credentials.txt`. The maker demo account uses employee ID `EMP014`, so its own claims are visible but cannot be reviewed. The checker demo account uses `EMP033`; the dual-role account demonstrates that one person cannot make and check the same case.

The API enforces review order and separation of duties. A maker may recommend; a different checker may sign off only after that recommendation. A claim owner or any account that uploaded the claim or its receipt may view the claim but cannot review it. Employee-only accounts see their own claims. Login sessions expire after 12 hours and can be revoked by signing out. For production, connect account provisioning and email ownership to your company identity provider.

## 🧠 What It Detects (v1: Employee Expense Fraud)

- **Typosquatting vendors** (e.g. "Zomto Food" vs "Zomato")
- **Duplicate claims** (fuzzy-matched by vendor + amount + date)
- **Amount inflation** (OCR receipt vs. claimed amount mismatch)
- **Split transactions** (multiple claims on same date from same employee)
- **Weekend/holiday claims**
- **Round-number anomalies**
- **Related-party transactions**
- **Benford's Law deviations**
- **Segregation of Duties violations**

---

## 📐 ML Architecture

```
Transactions + Receipt OCR
      ↓
Prior-only behavioral features (IDs used for lookups only)
      ↓
Training-fitted preprocessing
      ↓
Autoencoder reconstruction error + independent Isolation Forest score
      ↓
Frozen reference calibration and review threshold
      ↓
Ranked alerts + Isolation Forest SHAP evidence
```

Training separates normal training, early stopping, threshold calibration, and future testing chronologically. Scores are anomaly indices, not fraud probabilities. Read [the model notes](docs/model-v2.md) for label requirements and benchmark limitations.

---

## 🏗️ Project Structure

```
AuditAI/
├── backend/
│   └── app/
│       ├── api/           # FastAPI routers (claims, fraud, cases, analytics, reports)
│       ├── models/        # SQLAlchemy ORM models
│       ├── schemas/       # Pydantic request/response schemas
│       ├── features/      # Feature engineering (15 fraud signals)
│       ├── ml/            # Autoencoder, Isolation Forest, SHAP pipeline
│       ├── ocr/           # PaddleOCR + Tesseract dual-engine
│       ├── llm/           # Gemini API integration
│       └── config.py      # Centralized hyperparameters
├── frontend/
│   └── src/
│       ├── pages/         # Dashboard, Upload, ClaimsTable, ClaimDetail, AuditScreens
│       ├── components/    # Navbar, StatCard, ScoreBadge, ShapChart, ScoreGauge, etc.
│       └── api/           # Axios API client
├── scripts/
│   ├── generate_expense_claims.py   # Synthetic data generator
│   └── seed_and_train.py            # One-command pipeline setup
└── data/                            # Generated CSVs and synthetic receipts
```

---

## ⚡ Quick Start

### 1. Prerequisites
- Python 3.10+
- Node.js 18+
- PostgreSQL (running on port 5433)

### 2. Install backend dependencies
```bash
pip install fastapi uvicorn sqlalchemy psycopg2-binary pandas numpy torch scikit-learn shap fuzzywuzzy python-Levenshtein python-multipart google-generativeai pillow opencv-python-headless
```

### 3. Set environment variables
```bash
export DATABASE_URL="postgresql://localhost:5433/postgres"
export GEMINI_API_KEY="your-gemini-api-key"
```

### 4. Start the backend
```bash
python -m uvicorn backend.app.main:app --reload --port 8000
```

### 5. Seed the database + train models
```bash
python scripts/seed_demo_accounts.py
# Set AUDITAI_ADMIN_EMAIL and AUDITAI_ADMIN_PASSWORD to the provisioned admin account.
python scripts/seed_and_train.py
```

### 6. Start the frontend
```bash
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173** to sign in. Employees land on their claims; reviewers can access the dashboard.

---

## 📊 Dashboard Features

- **Audit Dashboard** — KPI metrics, monthly flagged claims bar chart, score distribution
- **High-Risk Claims Queue** — Filter by case status, risk level, and keyword search
- **Inline Typosquat Warnings** — Hover tooltips showing `⚠ 89% match to 'Domino's Pizza'`
- **3-Tier Risk Colors** — Amber (50-70%), Orange (70-85%), Red (85%+)
- **Claim Detail** — OCR results, SHAP waterfall chart, score gauges, AI audit report
- **Maker-Checker Workflow** — Makers recommend, Checkers sign off, append-only trail
- **Audit Screens** — Benford's Law chart, Related-Party screening, SoD violations

---

## 🔑 Key API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/claims/upload` | Upload CSV of expense claims |
| `GET` | `/api/v1/claims` | List claims with filters and pagination |
| `POST` | `/api/v1/fraud/train` | Train ML pipeline |
| `POST` | `/api/v1/fraud/score` | Score all claims |
| `GET` | `/api/v1/fraud/summary` | Dashboard statistics |
| `GET` | `/api/v1/analytics/benford` | Benford's Law distribution |
| `GET` | `/api/v1/analytics/related-parties` | Related-party screen |
| `GET` | `/api/v1/analytics/sod-violations` | SoD violations |
| `POST` | `/api/v1/cases/{id}/maker-recommend` | Maker recommendation |
| `POST` | `/api/v1/cases/{id}/checker-signoff` | Checker final sign-off |

---

## 📄 License

MIT
