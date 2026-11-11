"""Company accounts, revocable login sessions, and claim contributors."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import synonym, relationship
from backend.app.db import Base


class AuthUser(Base):
    __tablename__ = "auth_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(254), unique=True, index=True, nullable=False)
    employee_id = Column(String(50), index=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    roles = Column(JSON, nullable=False, default=list)
    role = Column(String(50), nullable=False, default="employee")
    full_name = synonym("display_name")
    is_active = synonym("active")
    last_login_at = Column(DateTime, nullable=True)
    password_hash = Column(String(300), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class ClaimContributor(Base):
    """Any account that submitted a claim or attached evidence cannot review it."""
    __tablename__ = "claim_contributors"
    __table_args__ = (UniqueConstraint("claim_id", "user_id"),)

    id = Column(Integer, primary_key=True)
    claim_id = Column(String(50), ForeignKey("expense_claims.claim_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    source = Column(String(30), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# OTP uses the same provisioned company identity.
User = AuthUser

class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(320), nullable=False, index=True)
    code_digest = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    token_digest = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    replaced_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("AuthUser")
