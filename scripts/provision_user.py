"""Provision a company account from a trusted local terminal.

Example: python scripts/provision_user.py --email alex@company.com --employee-id EMP014 --roles employee,maker
The password is requested without echo. Public registration is intentionally unavailable.
"""
import argparse
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.auth.security import hash_password, normalize_company_email
from backend.app.db import Base, SessionLocal, engine
from backend.app.models.auth import AuthUser  # noqa: F401 - registers the table
from backend.app.models import expense  # noqa: F401 - registers related tables

ALLOWED_ROLES = {"employee", "maker", "checker", "admin", "procurement", "finance", "legal", "security", "manager", "it"}


def provision(email: str, employee_id: str, name: str, roles: list[str], password: str):
    email = normalize_company_email(email)
    roles = sorted(set(roles))
    if not roles or not set(roles) <= ALLOWED_ROLES:
        raise ValueError("Roles must be employee, maker, checker, or admin.")
    if not employee_id.strip():
        raise ValueError("Employee ID is required.")
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        user = db.query(AuthUser).filter(AuthUser.email == email).first()
        if user:
            user.employee_id = employee_id.strip()
            user.display_name = name.strip() or email.split("@")[0]
            user.roles = roles
            user.password_hash = hash_password(password)
            user.active = True
            user.failed_attempts = 0
            user.locked_until = None
        else:
            user = AuthUser(email=email, employee_id=employee_id.strip(),
                            display_name=name.strip() or email.split("@")[0],
                            roles=roles, password_hash=hash_password(password))
            db.add(user)
        user.role = next((r for r in ["admin","procurement","finance","legal","security","manager","it"] if r in roles), "employee")
        db.commit()
    return email


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--employee-id", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--roles", default="employee", help="Comma-separated roles")
    args = parser.parse_args()
    password = getpass("Password (12+ characters): ")
    if password != getpass("Confirm password: "):
        parser.error("Passwords did not match.")
    print(f"Provisioned {provision(args.email, args.employee_id, args.name, args.roles.split(','), password)}")
