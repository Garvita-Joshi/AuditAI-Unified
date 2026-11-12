import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from backend.app.db import Base
import backend.app.models.auth
import backend.app.models.expense
import backend.app.models.review_queue
import backend.app.models.policy
from backend.app.seed_loader import seed_initial_claims_data
from backend.app.models.expense import ExpenseClaim, FraudPrediction

def test_seed_initial_claims_data_sqlite_with_foreign_keys():
    test_engine = create_engine("sqlite:///:memory:")
    @event.listens_for(test_engine, "connect")
    def set_fk(dbapi_conn, record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine)

    with TestSession() as db:
        # Initially empty
        assert db.query(ExpenseClaim).count() == 0
        
        # Seed should succeed
        seeded = seed_initial_claims_data(db)
        assert seeded is True
        assert db.query(ExpenseClaim).count() == 18
        assert db.query(FraudPrediction).count() == 18

        # Calling again should be idempotent (return False and not duplicate)
        seeded_again = seed_initial_claims_data(db)
        assert seeded_again is False
        assert db.query(ExpenseClaim).count() == 18
