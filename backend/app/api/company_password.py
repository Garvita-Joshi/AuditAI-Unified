"""Login for provisioned company accounts. Roles are never supplied by the browser."""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.auth.security import (
    DUMMY_PASSWORD_HASH, SESSION_HOURS, bearer, get_current_user, normalize_company_email,
    token_digest, user_payload, verify_password,
)
from backend.app.db import get_db
from backend.app.models.auth import AuthSession, AuthUser

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    try:
        email = normalize_company_email(body.email)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    user = db.query(AuthUser).filter(AuthUser.email == email, AuthUser.active.is_(True)).first()
    now = datetime.utcnow()
    if user and user.locked_until and user.locked_until > now:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in 15 minutes.")
    password_valid = verify_password(body.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not password_valid:
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_attempts = 0
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    user.failed_attempts = 0
    user.locked_until = None
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token),
                       expires_at=now + timedelta(hours=SESSION_HOURS)))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "user": user_payload(user)}


