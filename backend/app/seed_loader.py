import json
import logging
from datetime import datetime, date
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.app.db import Base
import backend.app.models.auth
import backend.app.models.expense
import backend.app.models.review_queue
import backend.app.models.policy
from backend.app.models.auth import AuthUser
from backend.app.auth.security import hash_password
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parent / "initial_seed.json"

def seed_initial_claims_data(db: Session) -> bool:
    """Idempotently seed the initial 18 claims, receipts, fraud predictions, and review cases
    if the database is currently empty (e.g. on fresh Railway cloud deployments).
    Fully compatible with both SQLite and PostgreSQL.
    """
    try:
        # Check if expense claims are already present
        res = db.execute(text("SELECT COUNT(*) FROM expense_claims")).scalar()
        if res and res > 0:
            return False

        if not SEED_FILE.exists():
            logger.warning(f"Seed file {SEED_FILE} does not exist. Skipping demo data seed.")
            return False

        seed_data = json.loads(SEED_FILE.read_text())

        is_sqlite = db.bind.dialect.name == "sqlite"
        is_postgres = db.bind.dialect.name in ("postgresql", "postgres")

        # Ensure an admin account exists for foreign key references in claim_contributors
        admin_user = db.query(AuthUser).filter(AuthUser.email == "prepares23@gmail.com").first()
        if not admin_user:
            admin_user = db.query(AuthUser).first()
        if not admin_user:
            admin_user = AuthUser(
                email="prepares23@gmail.com",
                employee_id="ADMIN-001",
                display_name="Garvita Joshi",
                roles=["admin", "maker", "checker", "manager", "finance", "security", "legal", "procurement", "it", "employee"],
                role="admin",
                password_hash=hash_password("AuditAI@2026!SecureAdmin"),
                active=True,
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

        target_user_id = admin_user.id

        # Load tables in strict dependency order
        table_order = [
            'entities',
            'receipts',
            'ocr_results',
            'expense_claims',
            'claim_contributors',
            'fraud_predictions',
            'cases',
            'case_audit_trails',
            'review_queue_records',
            'claim_policy_checks'
        ]

        for table_name in table_order:
            rows = seed_data.get(table_name, [])
            if not rows:
                continue

            table_obj = Base.metadata.tables.get(table_name)
            for r in rows:
                row_dict = dict(r)

                # Remap user_id for claim_contributors to the existing valid user
                if table_name == 'claim_contributors':
                    row_dict['user_id'] = target_user_id

                if table_obj is not None:
                    for col in table_obj.columns:
                        col_name = col.name
                        if col_name in row_dict and row_dict[col_name] is not None:
                            val = row_dict[col_name]
                            col_type = str(col.type).upper()
                            if 'JSON' in col_type and isinstance(val, str):
                                try:
                                    row_dict[col_name] = json.loads(val)
                                except Exception:
                                    pass
                            elif 'DATETIME' in col_type and isinstance(val, str):
                                try:
                                    row_dict[col_name] = datetime.fromisoformat(val.replace('Z', '+00:00'))
                                except Exception:
                                    pass
                            elif 'DATE' in col_type and isinstance(val, str):
                                try:
                                    row_dict[col_name] = date.fromisoformat(val[:10])
                                except Exception:
                                    pass

                    if is_sqlite:
                        stmt = sqlite_insert(table_obj).values(row_dict).on_conflict_do_nothing()
                    elif is_postgres:
                        stmt = pg_insert(table_obj).values(row_dict).on_conflict_do_nothing()
                    else:
                        stmt = table_obj.insert().values(row_dict)
                    db.execute(stmt)
                else:
                    cols = list(row_dict.keys())
                    col_names = ", ".join(cols)
                    bind_names = ", ".join([f":{c}" for c in cols])
                    if is_sqlite:
                        raw_stmt = text(f"INSERT OR IGNORE INTO {table_name} ({col_names}) VALUES ({bind_names})")
                    elif is_postgres:
                        raw_stmt = text(f"INSERT INTO {table_name} ({col_names}) VALUES ({bind_names}) ON CONFLICT DO NOTHING")
                    else:
                        raw_stmt = text(f"INSERT INTO {table_name} ({col_names}) VALUES ({bind_names})")
                    db.execute(raw_stmt, row_dict)

        # Synchronize serial sequences in PostgreSQL if any table used explicit primary keys
        if is_postgres:
            for table_name in table_order:
                try:
                    db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE(MAX(id), 1)) FROM {table_name}"))
                except Exception:
                    pass

        db.commit()
        logger.info(f"Successfully seeded {len(seed_data.get('expense_claims', []))} demo claims into database.")
        print(f"[SEED-LOADER] Successfully seeded {len(seed_data.get('expense_claims', []))} demo claims & fraud predictions for dashboard.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to seed demo claims: {e}")
        print(f"[SEED-LOADER] Seed error: {e}")
        return False
