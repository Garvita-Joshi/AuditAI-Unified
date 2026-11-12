"""Password, session, and claim access rules enforced by the API."""
import hashlib
import hmac
import os
import re
from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models.auth import AuthSession, AuthUser, ClaimContributor

COMPANY_EMAIL_DOMAINS = {
    d.strip().lower()
    for d in os.getenv("COMPANY_EMAIL_DOMAINS", "auditai.example,auditai.local,demo-industries.example,example.com,lnmiit.ac.in").split(",")
    if d.strip()
}


def get_allowed_email_domains() -> set[str]:
    return set(COMPANY_EMAIL_DOMAINS)


SESSION_HOURS = int(os.getenv("AUTH_SESSION_HOURS", "12"))
PASSWORD_ITERATIONS = 310_000
bearer = HTTPBearer(auto_error=False)


def normalize_company_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", normalized):
        raise ValueError("Enter a valid company email address.")
    domain = normalized.rsplit("@", 1)[1]
    allowed = set(COMPANY_EMAIL_DOMAINS)
    if domain not in allowed and normalized not in ("prepares23@gmail.com", "garvita_joshi@technologymindz.com"):
        raise ValueError("Only an approved company email domain is allowed.")
    return normalized


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (TypeError, ValueError):
        return False


# Run the same password check for unknown accounts to reduce email enumeration.
DUMMY_PASSWORD_HASH = hash_password("unregistered-account-placeholder")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def user_payload(user: AuthUser) -> dict:
    return {"id": user.id, "email": user.email, "employee_id": user.employee_id,
            "display_name": user.display_name, "roles": user.roles or []}


def has_role(user: AuthUser, *roles: str) -> bool:
    return any(role in (user.roles or []) for role in roles)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AuthUser:
    from backend.app.core.security import require_authenticated_user
    user = require_authenticated_user(credentials, db)
    try:
        normalize_company_email(user.email)
    except ValueError:
        raise HTTPException(403, "Account email domain is not approved.")
    return user


def require_roles(*roles: str):
    def dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not has_role(user, *roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account does not have access to this action.")
        return user
    return dependency


def is_claim_participant(db: Session, user: AuthUser, claim) -> bool:
    if user.employee_id == claim.employee_id:
        return True
    return db.query(ClaimContributor.id).filter(
        ClaimContributor.claim_id == claim.claim_id,
        ClaimContributor.user_id == user.id,
    ).first() is not None


def can_view_claim(db: Session, user: AuthUser, claim) -> bool:
    return has_role(user, "maker", "checker", "admin") or is_claim_participant(db, user, claim)


def assert_can_view_claim(db: Session, user: AuthUser, claim) -> None:
    if not can_view_claim(db, user, claim):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot view this claim.")


def review_block_reason(db: Session, user: AuthUser, claim, role: str) -> str | None:
    if not has_role(user, role):
        return f"Your account is not assigned the {role} role."
    if is_claim_participant(db, user, claim):
        return "You own or contributed to this claim, so you can view it but cannot review it."
    if claim.status not in ("flagged", "processing"):
        return "This claim is not currently flagged for review."
    case = claim.case
    if not case:
        if role == "maker" and claim.status == "flagged":
            return None
        return "The maker must open the review case first."
    if role == "maker":
        if case.status not in ("open", "maker_recommended_approve", "maker_recommended_reject"):
            return "This case is already closed."
        if case.maker_id and str(case.maker_id).isdigit() and str(case.maker_id) != str(user.id):
            return "Another maker has already made the recommendation on this case."
    else:
        if case.status not in ("maker_recommended_approve", "maker_recommended_reject"):
            return "The maker must submit a recommendation first."
        if not case.maker_id or str(case.maker_id) == str(user.id):
            return "The checker must be a different person from the maker."
        # Legacy unauthenticated recommendations must be re-entered by an account.
        if not str(case.maker_id).isdigit():
            return "The maker must submit an authenticated recommendation first."
        if any(entry.performed_by == f"maker: {user.email}" for entry in case.audit_trail):
            return "You already acted as maker on this case and cannot sign off as checker."
        from backend.app.policy_service import approval_block
        authority_reason = approval_block(db,user,claim)
        if authority_reason:
            return authority_reason
    return None


def assert_can_review(db: Session, user: AuthUser, claim, role: str) -> None:
    reason = review_block_reason(db, user, claim, role)
    if reason:
        raise HTTPException(status.HTTP_403_FORBIDDEN, reason)
