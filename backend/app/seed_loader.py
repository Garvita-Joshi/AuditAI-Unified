import json
import logging
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parent / "initial_seed.json"

def seed_initial_claims_data(db: Session) -> bool:
    """Idempotently seed the initial 18 claims, receipts, fraud predictions, and review cases
    if the database is currently empty (e.g. on fresh Railway cloud deployments).
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
        
        # Load tables in dependency order
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

        connection = db.connection()
        for table in table_order:
            rows = seed_data.get(table, [])
            if not rows:
                continue
            cols = list(rows[0].keys())
            col_names = ", ".join(cols)
            bind_names = ", ".join([f":{c}" for c in cols])
            insert_stmt = text(f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({bind_names})")
            
            for row in rows:
                connection.execute(insert_stmt, row)

        db.commit()
        logger.info(f"Successfully seeded {len(seed_data.get('expense_claims', []))} demo claims into database.")
        print(f"[SEED-LOADER] Successfully seeded {len(seed_data.get('expense_claims', []))} demo claims & fraud predictions for dashboard.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to seed demo claims: {e}")
        print(f"[SEED-LOADER] Seed error: {e}")
        return False
