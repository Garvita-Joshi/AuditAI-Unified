"""
AuditAI — Centralized configuration.

Reads settings from environment variables with sensible defaults for local development.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# === Paths ===
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # AuditAI/
BACKEND_ROOT = PROJECT_ROOT / "backend"
DATA_DIR = PROJECT_ROOT / "data"
RECEIPTS_DIR = DATA_DIR / "receipts"
SROIE_DIR = DATA_DIR / "sroie"
TRAINED_MODELS_DIR = BACKEND_ROOT / "trained_models"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
ENV_FILE = PROJECT_ROOT / ".env"


def reload_env() -> None:
    """Reload environment variables from project-root .env with override=True."""
    if ENV_FILE.is_file():
        load_dotenv(dotenv_path=ENV_FILE, override=True)
    else:
        load_dotenv(override=True)


# Load project-root .env file deterministically with override=True
reload_env()

# Ensure critical directories exist
for d in [DATA_DIR, RECEIPTS_DIR, TRAINED_MODELS_DIR, UPLOAD_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# === Database ===
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5433/postgres")

# === Gemini LLM ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

# === OCR ===
# Bundled CPU OCR with optional PaddleOCR/Tesseract fallbacks.
OCR_PRIMARY_ENGINE = os.getenv("OCR_PRIMARY_ENGINE", "rapidocr")
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")  # Path to tesseract binary

# === ML Pipeline ===
# Autoencoder hyperparameters
AE_LATENT_DIM = int(os.getenv("AE_LATENT_DIM", "16"))
AE_EPOCHS = int(os.getenv("AE_EPOCHS", "100"))
AE_LEARNING_RATE = float(os.getenv("AE_LEARNING_RATE", "0.001"))
AE_BATCH_SIZE = int(os.getenv("AE_BATCH_SIZE", "64"))
AE_PATIENCE = int(os.getenv("AE_PATIENCE", "12"))
AE_WEIGHT_DECAY = float(os.getenv("AE_WEIGHT_DECAY", "0.00001"))
ML_SEED = int(os.getenv("ML_SEED", "42"))
ML_CLIP = 8.0
NORMAL_SCORE_QUANTILE = 0.99
OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.6"))

# Isolation Forest hyperparameters
IF_CONTAMINATION = float(os.getenv("IF_CONTAMINATION", "0.07"))
IF_N_ESTIMATORS = int(os.getenv("IF_N_ESTIMATORS", "300"))
IF_RANDOM_STATE = int(os.getenv("IF_RANDOM_STATE", "42"))

# Scoring combination weights
# final_score = SCORE_ALPHA * reconstruction_error + (1 - SCORE_ALPHA) * isolation_forest_score
# Independent AE and IF scores calibrated on held-out normal claims.
SCORE_ALPHA = float(os.getenv("SCORE_ALPHA", "0.5"))
FRAUD_SCORE_THRESHOLD = float(os.getenv("FRAUD_SCORE_THRESHOLD", "0.60"))

# === Feature Engineering ===
AMOUNT_MISMATCH_THRESHOLD = float(os.getenv("AMOUNT_MISMATCH_THRESHOLD", "0.05"))
DUPLICATE_SIMILARITY_THRESHOLD = float(os.getenv("DUPLICATE_SIMILARITY_THRESHOLD", "0.85"))
VENDOR_ANOMALY_THRESHOLD = float(os.getenv("VENDOR_ANOMALY_THRESHOLD", "0.3"))

# Known approved vendors — loaded from DB at runtime, this is the fallback static list
KNOWN_VENDORS = [
    "Amazon", "Walmart", "Starbucks", "Uber", "Lyft", "Delta Airlines",
    "United Airlines", "Marriott", "Hilton", "FedEx", "UPS", "Staples",
    "Office Depot", "Best Buy", "Apple", "Microsoft", "Google", "Zomato",
    "Swiggy", "Ola", "MakeMyTrip", "IRCTC", "Flipkart", "Reliance",
    "Tata Consultancy Services", "Infosys", "Wipro", "HCL Technologies",
]

# Indian public holidays (2025-2026) for weekend/holiday feature
HOLIDAYS = [
    "2025-01-26", "2025-03-14", "2025-03-31", "2025-04-06", "2025-04-10",
    "2025-04-14", "2025-04-18", "2025-05-01", "2025-05-12", "2025-06-07",
    "2025-07-06", "2025-08-15", "2025-08-16", "2025-08-27", "2025-09-05",
    "2025-10-02", "2025-10-20", "2025-10-21", "2025-10-23", "2025-11-01",
    "2025-11-05", "2025-12-25",
    "2026-01-26", "2026-03-03", "2026-03-20", "2026-03-30", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-16", "2026-08-15", "2026-08-25",
    "2026-10-02", "2026-10-10", "2026-11-14", "2026-12-25",
]

# === Dograh Voice AI Configuration ===
DOGRAH_API_KEY = os.getenv("DOGRAH_API_KEY", "")
DOGRAH_API_URL = os.getenv("DOGRAH_API_URL", "https://api.dograh.com/api/v1/public/agent")
DOGRAH_TEST_API_URL = os.getenv("DOGRAH_TEST_API_URL", "https://api.dograh.com/api/v1/public/agent/test")
DOGRAH_TRIGGER_PATH = os.getenv("DOGRAH_TRIGGER_PATH", "fe74624e-3928-482b-821e-9be6416df7c8")
DOGRAH_WEBHOOK_SECRET = os.getenv("DOGRAH_WEBHOOK_SECRET", "")
# CRITICAL: DOGRAH_DRY_RUN MUST remain True by default during development.
# When True, zero outbound telephony requests are sent, and no phone is dialed.
DOGRAH_DRY_RUN = os.getenv("DOGRAH_DRY_RUN", "true").lower() in ("true", "1", "yes")
DOGRAH_TIMEOUT_SECONDS = int(os.getenv("DOGRAH_TIMEOUT_SECONDS", "30"))

# === Twilio Telephony Configuration ===
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

# === Exotel OpenVBX Indian Telephony Configuration ===
EXOTEL_ACCOUNT_SID = os.getenv("EXOTEL_ACCOUNT_SID", "")
EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY", "")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN", "")
EXOTEL_BASE_URL = os.getenv("EXOTEL_BASE_URL", "https://api.in.exotel.com").rstrip("/")
EXOTEL_CALLER_ID = os.getenv("EXOTEL_CALLER_ID", "")

# === Voice Calling Safety Controls ===
# Comma-separated E.164 authorized phone numbers for testing (e.g. +919876543210)
VOICE_AUTHORIZED_ALLOWLIST = [
    num.strip() for num in os.getenv("VOICE_AUTHORIZED_ALLOWLIST", "").split(",") if num.strip()
]
VOICE_MAX_DAILY_CALLS = int(os.getenv("VOICE_MAX_DAILY_CALLS", "1"))
VOICE_MAX_DURATION_SECONDS = int(os.getenv("VOICE_MAX_DURATION_SECONDS", "120"))
VOICE_EMERGENCY_DISABLE = os.getenv("VOICE_EMERGENCY_DISABLE", "false").lower() in ("true", "1", "yes")

# === API ===
API_V1_PREFIX = "/api/v1"
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))

# Procurement and OTP settings
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-development-secret-before-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "10"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
AUTH_DEBUG_OTP = os.getenv("AUTH_DEBUG_OTP", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)
SOURCING_MAIL_FROM = os.getenv("SOURCING_MAIL_FROM", "prepares23@gmail.com")
CORS_ORIGINS = [origin.strip() for origin in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if origin.strip()]
CONTROL_DUPLICATE_WINDOW_DAYS = int(os.getenv("CONTROL_DUPLICATE_WINDOW_DAYS", "90"))
CONTROL_SPLIT_WINDOW_DAYS = int(os.getenv("CONTROL_SPLIT_WINDOW_DAYS", "3"))
CONTROL_APPROVAL_THRESHOLD = float(os.getenv("CONTROL_APPROVAL_THRESHOLD", "50000"))
CONTROL_GHOST_VENDOR_THRESHOLD = float(os.getenv("CONTROL_GHOST_VENDOR_THRESHOLD", "25000"))
CONTROL_KEYWORDS = [item.strip().lower() for item in os.getenv(
    "CONTROL_KEYWORDS", "adjustment,misc,personal,reimburse,cash,urgent,one-time"
).split(",") if item.strip()]
RATIO_DEFINITIONS = {
    "bad_debt_to_ar": {"name": "Bad-debt write-off to Accounts Receivable", "numerator_accounts": ["Bad Debt Write-off"], "denominator_accounts": ["Accounts Receivable"]},
    "cash_receipts_to_revenue": {"name": "Cash receipts to Revenue", "numerator_accounts": ["Cash Receipts"], "denominator_accounts": ["Revenue"]},
    "current_ratio_proxy": {"name": "Current assets to Current liabilities", "numerator_accounts": ["Current Assets"], "denominator_accounts": ["Current Liabilities"]},
    "cash_to_expense": {"name": "Cash payments to total spend", "numerator_accounts": [], "denominator_accounts": []},
}
