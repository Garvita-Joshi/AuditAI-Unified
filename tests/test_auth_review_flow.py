"""End-to-end authorization checks for employee and maker-checker accounts."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth.security import hash_password, normalize_company_email
from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models.auth import AuthUser
from backend.app.models.expense import Case, ExpenseClaim


def test_login_visibility_and_separation_of_duties(monkeypatch):
    monkeypatch.setattr("backend.app.auth.security.COMPANY_EMAIL_DOMAINS", {"auditai.example"})
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def test_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with session_factory() as db:
        users = [
            AuthUser(email="employee@auditai.example", employee_id="EMP001", display_name="Employee",
                     roles=["employee"], password_hash=hash_password("employee-pass-123")),
            AuthUser(email="maker@auditai.example", employee_id="EMP014", display_name="Maker",
                     roles=["employee", "maker"], password_hash=hash_password("maker-pass-12345")),
            AuthUser(email="dual@auditai.example", employee_id="EMP050", display_name="Dual",
                     roles=["employee", "maker", "checker"], password_hash=hash_password("dual-pass-123456")),
            AuthUser(email="checker@auditai.example", employee_id="EMP033", display_name="Checker",
                     roles=["employee", "checker"], password_hash=hash_password("checker-pass-123")),
            AuthUser(email="admin@auditai.example", employee_id="EMP-ADMIN", display_name="Admin",
                     roles=["admin"], password_hash=hash_password("admin-pass-12345")),
        ]
        db.add_all(users)
        for claim_id, employee_id in [("CLM-EMP", "EMP001"), ("CLM-SELF", "EMP014"), ("CLM-OTHER", "EMP099")]:
            db.add(ExpenseClaim(claim_id=claim_id, employee_id=employee_id, employee_name="Example",
                                claimed_amount=Decimal("100.00"), vendor_name="Vendor",
                                claimed_date=date(2026, 1, 15), status="flagged"))
            db.add(Case(claim_id=claim_id, status="open"))
        db.add(ExpenseClaim(claim_id="CLM-SCORED", employee_id="EMP099", employee_name="Example",
                            claimed_amount=Decimal("100.00"), vendor_name="Vendor",
                            claimed_date=date(2026, 1, 15), status="scored"))
        db.add(Case(claim_id="CLM-SCORED", status="open"))
        db.commit()
        dual_id = users[2].id
        checker_id = users[3].id

    try:
        client = TestClient(app)

        def headers(email, password):
            result = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert result.status_code == 200, result.text
            return {"Authorization": f"Bearer {result.json()['access_token']}"}

        assert client.get("/api/v1/claims").status_code == 401
        assert client.post("/api/v1/auth/login", json={"email": "outsider@gmail.com", "password": "whatever"}).status_code == 401
        try:
            normalize_company_email("outsider@gmail.com")
            assert False, "Non-company domain was accepted"
        except ValueError:
            pass

        employee = headers("employee@auditai.example", "employee-pass-123")
        maker = headers("maker@auditai.example", "maker-pass-12345")
        dual = headers("dual@auditai.example", "dual-pass-123456")
        checker = headers("checker@auditai.example", "checker-pass-123")
        admin = headers("admin@auditai.example", "admin-pass-12345")

        visible = client.get("/api/v1/claims", headers=employee)
        assert visible.status_code == 200
        assert [claim["claim_id"] for claim in visible.json()["claims"]] == ["CLM-EMP"]
        assert client.get("/api/v1/claims/CLM-OTHER", headers=employee).status_code == 403
        assert client.get("/api/v1/claims/CLM-SELF", headers=maker).json()["review_permissions"]["is_own_claim"]
        scored = client.get("/api/v1/claims/CLM-SCORED", headers=maker).json()
        assert "not currently flagged" in scored["review_permissions"]["maker_block_reason"]
        assert client.post("/api/v1/cases/CLM-SCORED/maker-recommend",
                           params={"action": "approve", "notes": "Not flagged"}, headers=maker).status_code == 400
        assert client.get("/api/v1/fraud/summary", headers=employee).status_code == 403
        assert client.patch("/api/v1/claims/CLM-OTHER/status?new_status=approved", headers=checker).status_code == 403
        assert client.patch("/api/v1/claims/CLM-OTHER/status?new_status=approved", headers=admin).status_code == 422

        action = "/api/v1/cases/CLM-OTHER"
        assert client.post(f"{action}/checker-signoff", params={"action": "approve", "notes": "Too early"}, headers=checker).status_code == 403
        assert client.post("/api/v1/cases/CLM-SELF/maker-recommend", params={"action": "approve", "notes": "My own claim"}, headers=maker).status_code == 403
        recommended = client.post(f"{action}/maker-recommend", params={"action": "reject", "notes": "Needs review", "maker_id": "9999"}, headers=dual)
        assert recommended.status_code == 200, recommended.text
        assert client.post(f"{action}/checker-signoff", params={"action": "approve", "notes": "Same account"}, headers=dual).status_code == 403
        signed = client.post(f"{action}/checker-signoff", params={"action": "approve", "notes": "Reviewed evidence"}, headers=checker)
        assert signed.status_code == 200, signed.text
        detail = client.get("/api/v1/claims/CLM-OTHER", headers=checker).json()
        assert detail["claim"]["status"] == "approved"
        assert detail["case_review"]["maker_name"] == "Dual"
        with session_factory() as db:
            case = db.query(Case).filter(Case.claim_id == "CLM-OTHER").one()
            assert case.maker_id == str(dual_id)
            assert case.checker_id == str(checker_id)

        csv = b"claim_id,employee_id,employee_name,claimed_amount,vendor_name,claimed_date\nCLM-UP,EMP099,Example,42.00,Vendor,2026-01-16\n"
        assert client.post("/api/v1/claims/upload", files={"file": ("claims.csv", BytesIO(csv), "text/csv")}, headers=employee).status_code == 403
        upload = client.post("/api/v1/claims/upload", files={"file": ("claims.csv", BytesIO(csv), "text/csv")}, headers=maker)
        assert upload.status_code == 200, upload.text
        with session_factory() as db:
            db.query(ExpenseClaim).filter(ExpenseClaim.claim_id == "CLM-UP").one().status = "flagged"
            # Import policy checks may already have opened a case (e.g. missing description).
            if not db.query(Case).filter_by(claim_id="CLM-UP").first():
                db.add(Case(claim_id="CLM-UP", status="open"))
            db.commit()
        assert client.get("/api/v1/claims/CLM-UP", headers=maker).status_code == 200
        assert client.post("/api/v1/cases/CLM-UP/maker-recommend", params={"action": "approve", "notes": "I uploaded it"}, headers=maker).status_code == 403
        assert client.post("/api/v1/reports/generate/CLM-SELF", headers=maker).status_code == 403
        assert client.post("/api/v1/auth/logout", headers=checker).status_code == 200
        assert client.get("/api/v1/auth/me", headers=checker).status_code == 401
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
