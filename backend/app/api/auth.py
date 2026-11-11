"""OTP sign-in, JWT refresh rotation, and logout endpoints."""
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from fastapi.security import HTTPAuthorizationCredentials
from backend.app.core.security import bearer_scheme

from backend.app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES, AUTH_COOKIE_SECURE, AUTH_DEBUG_OTP,
    OTP_EXPIRE_MINUTES, OTP_MAX_ATTEMPTS, REFRESH_TOKEN_EXPIRE_DAYS,
    SMTP_FROM_EMAIL, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME,
)
from backend.app.core.security import (
    create_access_token, create_refresh_token, digest, generate_otp, require_authenticated_user, utcnow,
)
from backend.app.db import Base, engine, get_db
from backend.app.models.auth import OtpChallenge, RefreshSession, User
from backend.app.schemas.auth import OtpRequest, OtpRequestResponse, OtpVerifyRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
AUTH_TABLES = [User.__table__, OtpChallenge.__table__, RefreshSession.__table__]


def ensure_auth_tables() -> None:
    Base.metadata.create_all(bind=engine, tables=AUTH_TABLES)


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="auditai_refresh_token", value=token, max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True, secure=AUTH_COOKIE_SECURE, samesite="lax", path="/api/v1/auth",
    )


def _send_otp_smtp(email: str, code: str) -> None:
    from email.message import EmailMessage
    import smtplib
    import ssl
    message = EmailMessage()
    message["Subject"] = f"{code} is your AuditAI verification code"
    message["From"] = f"AuditAI Security <{SMTP_FROM_EMAIL}>"
    message["To"] = email
    
    text_content = f"Your AuditAI verification code is: {code}\n\nThis code will expire in {OTP_EXPIRE_MINUTES} minutes. If you did not request this, please ignore this email."
    html_content = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 28px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
      <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <h2 style="color: #0f172a; margin: 0; font-size: 20px;">AuditAI Verification</h2>
      </div>
      <p style="color: #334155; font-size: 15px; line-height: 1.5;">Here is your single-use verification code to sign in to the AuditAI platform:</p>
      <div style="background-color: #f8fafc; border: 1px dashed #cbd5e1; padding: 18px; border-radius: 8px; text-align: center; margin: 24px 0;">
        <span style="font-family: monospace; font-size: 34px; font-weight: 700; letter-spacing: 8px; color: #0284c7;">{code}</span>
      </div>
      <p style="color: #64748b; font-size: 13px; line-height: 1.5; margin-bottom: 0;">This code is valid for <strong>{OTP_EXPIRE_MINUTES} minutes</strong>. If you did not attempt to sign in, please ignore this email.</p>
    </div>
    """
    message.set_content(text_content)
    message.add_alternative(html_content, subtype="html")

    # Try configured port first, fallback to 587 STARTTLS if 465 SSL is blocked by host firewall
    ports_to_try = [int(SMTP_PORT or 465)]
    if 587 not in ports_to_try:
        ports_to_try.append(587)
    
    last_err = None
    for port in ports_to_try:
        try:
            implicit_ssl = port == 465
            client = smtplib.SMTP_SSL if implicit_ssl else smtplib.SMTP
            with client(SMTP_HOST, port, timeout=6, **({"context": ssl.create_default_context()} if implicit_ssl else {})) as server:
                if not implicit_ssl:
                    server.starttls(context=ssl.create_default_context())
                if SMTP_USERNAME:
                    password = SMTP_PASSWORD.replace(" ", "") if SMTP_HOST.endswith("gmail.com") else SMTP_PASSWORD
                    server.login(SMTP_USERNAME, password)
                server.send_message(message)
                return
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err


def deliver_otp(email: str, code: str) -> bool:
    """Deliver a code by SMTP when configured. Returns True if successfully sent via email."""
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        return False
    try:
        _send_otp_smtp(email, code)
        return True
    except Exception:
        return False




def issue_tokens(response: Response, user: User, db: Session) -> TokenResponse:
    refresh_token = create_refresh_token()
    session = RefreshSession(
        user_id=user.id, token_digest=digest(refresh_token),
        expires_at=utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    db.commit()
    set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=create_access_token(user), expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


@router.post("/request-otp", response_model=OtpRequestResponse)
def request_otp(payload: OtpRequest, db: Session = Depends(get_db)):
    ensure_auth_tables()
    email = str(payload.email).lower()
    from backend.app.auth.security import normalize_company_email
    try:
        normalize_company_email(email)
    except ValueError:
        raise HTTPException(403, "Company email domain is not approved.")
    db.query(OtpChallenge).filter(OtpChallenge.email == email, OtpChallenge.consumed_at.is_(None)).update(
        {OtpChallenge.consumed_at: utcnow()}, synchronize_session=False
    )
    account = db.query(User).filter(User.email == email, User.active.is_(True)).first()
    if not account:
        import os
        if os.getenv("AUTH_AUTO_PROVISION", "true").lower() in ("true", "1", "yes"):
            from backend.app.auth.security import hash_password
            is_admin = ("admin" in email or email in ("prepares23@gmail.com", "garvita_joshi@technologymindz.com"))
            roles = ["admin", "maker", "checker", "manager", "finance", "security", "legal", "procurement", "it", "employee"] if is_admin else ["employee", "maker"]
            account = User(
                email=email,
                employee_id=f"EMP-{abs(hash(email)) % 100000:05d}",
                display_name=email.split("@")[0].replace(".", " ").title(),
                roles=roles,
                role="admin" if is_admin else "employee",
                password_hash=hash_password("AuditAI@2026!Secure"),
                active=True,
            )
            db.add(account)
            db.commit()
        else:
            raise HTTPException(403, "Ask your administrator to provision your company account.")
    code = generate_otp()
    sent_via_email = deliver_otp(email, code)
    db.add(OtpChallenge(email=email, code_digest=digest(code), expires_at=utcnow() + timedelta(minutes=OTP_EXPIRE_MINUTES)))
    db.commit()

    if sent_via_email and not AUTH_DEBUG_OTP:
        msg = f"A verification code has been sent to {email}. Please check your inbox."
        dev_code = None
    else:
        msg = f"Verification code generated for {email}."
        dev_code = code

    return OtpRequestResponse(
        message=msg, expires_in_seconds=OTP_EXPIRE_MINUTES * 60,
        development_code=dev_code,
    )


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(payload: OtpVerifyRequest, response: Response, db: Session = Depends(get_db)):
    ensure_auth_tables()
    email = str(payload.email).lower()
    from backend.app.auth.security import normalize_company_email
    try:
        normalize_company_email(email)
    except ValueError:
        raise HTTPException(403, "Company email domain is not approved.")
    challenge = (
        db.query(OtpChallenge).filter(OtpChallenge.email == email, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.created_at.desc()).first()
    )
    if not challenge or challenge.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="The one-time code has expired. Request a new code.")
    if challenge.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many incorrect attempts. Request a new code.")
    if not hmac_compare(challenge.code_digest, digest(payload.code)):
        challenge.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid one-time code.")
    challenge.consumed_at = utcnow()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(403, "Company account is not provisioned.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been disabled.")
    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)
    return issue_tokens(response, user, db)


def hmac_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left, right)


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(response: Response, auditai_refresh_token: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    ensure_auth_tables()
    if not auditai_refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token is missing.")
    session = db.query(RefreshSession).filter(RefreshSession.token_digest == digest(auditai_refresh_token)).first()
    if not session or session.revoked_at or session.expires_at <= utcnow():
        raise HTTPException(status_code=401, detail="Refresh token is invalid or expired.")
    user = session.user
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is unavailable.")
    session.revoked_at = utcnow()
    db.commit()
    return issue_tokens(response, user, db)


@router.post("/logout")
def logout(response: Response, auditai_refresh_token: str | None = Cookie(default=None), db: Session = Depends(get_db), credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    if auditai_refresh_token:
        session = db.query(RefreshSession).filter(RefreshSession.token_digest == digest(auditai_refresh_token)).first()
        if session and not session.revoked_at:
            session.revoked_at = utcnow()
            db.commit()
    response.delete_cookie("auditai_refresh_token", path="/api/v1/auth", httponly=True, secure=AUTH_COOKIE_SECURE, samesite="lax")
    if credentials:
        from backend.app.models.auth import AuthSession
        from backend.app.auth.security import token_digest
        legacy = db.query(AuthSession).filter(AuthSession.token_hash == token_digest(credentials.credentials)).first()
        if legacy:
            legacy.revoked_at = utcnow()
            db.commit()
    return {"status": "signed_out"}


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(require_authenticated_user)):
    return UserResponse.model_validate(user)
