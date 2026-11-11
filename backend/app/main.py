from contextlib import asynccontextmanager
import os
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.auth.security import get_current_user, require_roles
from backend.app.api.auth import router as auth_router
from backend.app.api.dev_otp import router as dev_otp_router
from backend.app.api.claims import router as claims_router
from backend.app.api.receipts import router as receipts_router
from backend.app.api.fraud import router as fraud_router
from backend.app.api.reports import router as reports_router
from backend.app.api.cases import router as cases_router
from backend.app.api.analytics import router as analytics_router
from backend.app.api.transfers import router as transfers_router
from backend.app.api.transfer_reviews import router as transfer_reviews_router
from backend.app.api.reconciliation import router as reconciliation_router
from backend.app.api.policies import router as policies_router
from backend.app.api.master_data import router as master_data_router
from backend.app.api.review_queue import router as review_queue_router
from backend.app.transfer_migrations import migrate_transfer_claim_link
from backend.app.db import Base, engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Auth tables are additive, so existing claim data does not need migration.
    Base.metadata.create_all(bind=engine)
    migrate_transfer_claim_link(engine)
    # Existing imported master data should not require a manual first scan.
    from backend.app.db import SessionLocal
    from backend.app.master_rule_service import run
    with SessionLocal() as db:
        for dataset in ('vendor','payroll'):
            run(db,dataset)
        db.commit()

    import asyncio
    from backend.app.agentic_ai.background_worker import start_autonomous_sourcing_worker, stop_autonomous_sourcing_worker
    worker_task = asyncio.create_task(start_autonomous_sourcing_worker(poll_interval_seconds=15))
    try:
        yield
    finally:
        await stop_autonomous_sourcing_worker(worker_task)

app = FastAPI(
    title="AuditAI API",
    description="Automated financial anomaly detection and ingestion pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register endpoints
app.include_router(auth_router)
app.include_router(dev_otp_router)
app.include_router(transfers_router)
app.include_router(transfer_reviews_router)
app.include_router(reconciliation_router)
app.include_router(policies_router)
app.include_router(master_data_router)
app.include_router(review_queue_router)
app.include_router(claims_router, dependencies=[Depends(get_current_user)])
app.include_router(receipts_router, dependencies=[Depends(get_current_user)])
app.include_router(fraud_router, dependencies=[Depends(require_roles("maker", "checker", "admin"))])
app.include_router(reports_router, dependencies=[Depends(require_roles("maker", "checker", "admin"))])
app.include_router(cases_router, dependencies=[Depends(get_current_user)])
app.include_router(analytics_router, dependencies=[Depends(require_roles("maker", "checker", "admin"))])

@app.get("/health")
@app.get("/api/v1/health")
def read_root():
    return {
        "app": "AuditAI",
        "description": "Financial Transaction Anomaly Detection & Ingestion Engine",
        "version": "1.0.0",
        "status": "healthy"
    }

@app.get("/api/v1/sourcing/worker/status")
def get_sourcing_worker_status():
    from backend.app.agentic_ai.background_worker import get_worker_status
    return get_worker_status()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)

from backend.app.api.review_records import router as review_records_router
app.include_router(review_records_router)

from backend.app.api.master_checks import router as master_checks_router
app.include_router(master_checks_router)

from backend.app.api.detection import router as detection_router
app.include_router(detection_router)

from backend.app.api.procurement import router as procurement_router
from backend.app.api.procurement_extraction import router as extraction_router
from backend.app.api.procurement_payments import router as payments_router
from backend.app.api.sourcing import router as sourcing_router
from backend.app.api.company_password import router as company_password_router
for router in (procurement_router, extraction_router, payments_router, sourcing_router):
    app.include_router(router, dependencies=[Depends(get_current_user)])
app.include_router(company_password_router)

# Voice foundation registers additive tables and authenticated data APIs.
from backend.app.api.voice_calls import router as voice_calls_router
app.include_router(voice_calls_router)

# Dograh Voice AI Integration: Outbound triggers (dry-run safe), Webhook receiver, status lookups
from backend.app.api.dograh_routes import router as dograh_router
app.include_router(dograh_router)

# Static frontend serving (for unified production cloud deployment)
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import HTTPException

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/")
    async def serve_spa_root():
        return FileResponse(frontend_dist / "index.html")

    @app.get("/{full_path:path}")
    async def serve_spa_route(full_path: str):
        # Do not intercept API routes, OpenAPI docs, or health endpoints
        if full_path.startswith("api/") or full_path.startswith("voice/") or full_path in ("docs", "openapi.json", "redoc", "health"):
            raise HTTPException(status_code=404, detail="Not Found")

        file_candidate = frontend_dist / full_path
        if file_candidate.is_file():
            return FileResponse(file_candidate)
        return FileResponse(frontend_dist / "index.html")
else:
    @app.get("/")
    def read_root_fallback():
        return {
            "app": "AuditAI",
            "description": "Financial Transaction Anomaly Detection & Ingestion Engine",
            "version": "1.0.0",
            "status": "healthy"
        }

