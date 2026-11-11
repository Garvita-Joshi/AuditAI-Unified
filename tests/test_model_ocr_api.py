import io
from datetime import datetime, date, timedelta

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base, get_db
from backend.app.models.expense import Case, ExpenseClaim, FraudPrediction
from backend.app.models.auth import AuthUser
from backend.app.auth.security import get_current_user, hash_password
from backend.app.api import receipts, fraud, claims


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    for i in range(3):
        session.add(ExpenseClaim(claim_id=f'C{i}', employee_id='E', employee_name='Employee',
            vendor_name='Vendor', claimed_amount=100, claimed_date=date(2025,1,1)+timedelta(days=i),
            submitted_at=datetime(2025,1,1)+timedelta(hours=i), status='scored' if i == 0 else 'pending'))
    session.commit()
    test_user = AuthUser(email='auditor@auditai.example', employee_id='AUDITOR', display_name='Auditor',
                         roles=['admin', 'maker'], password_hash=hash_password('test-password-123'))
    session.add(test_user)
    session.commit()
    app = FastAPI()
    for router in [receipts.router, fraud.router, claims.router]:
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: test_user
    monkeypatch.setattr(receipts, 'RECEIPTS_DIR', tmp_path)
    with TestClient(app) as client:
        yield client, session
    session.close()
    engine.dispose()


def png():
    stream = io.BytesIO()
    Image.new('RGB', (300,200), 'white').save(stream, format='PNG')
    return stream.getvalue()


def test_receipt_refreshes_affected_score_automatically_and_preserves_confidence(api, monkeypatch, tmp_path):
    client, session = api
    # Build an isolated tiny test bundle; never depend on a developer's installed model.
    from backend.app import config
    from backend.app.ml.pipeline import train_claims
    from tests.test_behavioral_pipeline import records
    monkeypatch.setattr(config, 'TRAINED_MODELS_DIR', tmp_path / 'models')
    monkeypatch.setattr(config, 'AE_EPOCHS', 2)
    monkeypatch.setattr(config, 'IF_N_ESTIMATORS', 10)
    train_claims(records(200), np.zeros(200, dtype=int), config)
    session.add(FraudPrediction(claim_id='C0', combined_fraud_score=.1))
    session.commit()
    monkeypatch.setattr(receipts.ocr_engine, 'extract_text', lambda image: ('Vendor\n2025-01-01\nTotal: 50.00', .4, 'test'))
    response = client.post('/api/v1/receipts/upload?claim_id=C0', files={'file': ('r.png',png(),'image/png')})
    assert response.status_code == 201
    assert response.json()['upload_status'] == 'processed'
    session.expire_all()
    c = session.query(ExpenseClaim).filter_by(claim_id='C0').one()
    assert c.status in ('scored','flagged') and c.prediction is not None
    assert response.json()['checks']['stages'][0]['scored_count']==1
    assert c.prediction.feature_values['ocr_confidence']==pytest.approx(.4)
    assert c.prediction.feature_values['ocr_low_confidence']==1
    assert session.query(FraudPrediction).filter(FraudPrediction.claim_id.in_(['C1','C2'])).count()==0
    assert c.receipt.ocr_result.extraction_confidence <= .4
    assert float(c.receipt.ocr_result.extracted_amount) == 50
    assert client.post('/api/v1/receipts/upload?claim_id=MISSING', files={'file': ('r.png',png())}).status_code == 404


def test_ocr_failure_is_not_reported_as_processed(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(receipts.ocr_engine, 'extract_text', lambda image: ('',0,'failed'))
    response = client.post('/api/v1/receipts/upload?claim_id=C1', files={'file': ('r.png',png())})
    assert response.json()['status'] == 'failed'
    assert response.json()['upload_status'] == 'failed'


def test_scoring_keeps_previous_claim_context_and_rescore_is_idempotent(api, monkeypatch):
    client, session = api
    # This test isolates model cancellation; January 1 separately requires policy review.
    for c in session.query(ExpenseClaim).all():
        c.claimed_date+=timedelta(days=5);c.submitted_at+=timedelta(days=5)
    session.commit()
    # Isolate score-driven case lifecycle from missing-information policy findings.
    from backend.app import policy_service
    monkeypatch.setattr(policy_service,'run_checks',lambda *args,**kwargs: {})
    seen = []
    flagged = [True]
    monkeypatch.setattr(fraud, 'load_pipeline', lambda cfg: {'isolation_forest': None})
    def score(x, *args):
        seen.append(x.copy())
        return [dict(reconstruction_error=.01, isolation_forest_score=.4,
                     combined_fraud_score=.6 if flagged[0] else .2,
                     is_flagged=flagged[0]) for _ in x]
    monkeypatch.setattr(fraud, 'score_claims', score)
    monkeypatch.setattr(fraud, 'transform_features', lambda x, a: x)
    monkeypatch.setattr(fraud, 'compute_shap_values', lambda *a, **k: [])
    response = client.post('/api/v1/fraud/score')
    assert response.status_code == 200, response.text
    from backend.app.features.behavioral import FEATURE_NAMES
    assert seen[0][0, FEATURE_NAMES.index('log_vendor_prior_n')] == pytest.approx(np.log(2))
    assert session.query(FraudPrediction).count() == 2
    response = client.post('/api/v1/fraud/score?rescore=true')
    assert response.status_code == 200, response.text
    assert session.query(FraudPrediction).count() == 3
    flagged[0] = False
    response = client.post('/api/v1/fraud/score?rescore=true')
    assert response.status_code == 200, response.text
    session.expire_all()
    assert {case.status for case in session.query(Case).all()} == {'cancelled_unflagged'}
    flagged[0] = True
    response = client.post('/api/v1/fraud/score?rescore=true')
    assert response.status_code == 200, response.text
    session.expire_all()
    assert {case.status for case in session.query(Case).all()} == {'open'}
    assert all([event.action for event in case.audit_trail] == [
        'created', 'cancelled_after_rescore', 'reopened_after_rescore'
    ] for case in session.query(Case).all())


def test_tabular_receipt_amount_is_retained(api):
    client, session = api
    csv = 'claim_id,employee_id,employee_name,vendor_name,claimed_amount,claimed_date,ocr_amount\nNEW,E,Employee,Vendor,100,2025-01-01,50\n'
    response = client.post('/api/v1/claims/upload', files={'file': ('claims.csv',csv,'text/csv')})
    assert response.status_code == 200, response.text
    c = session.query(ExpenseClaim).filter_by(claim_id='NEW').one()
    assert float(c.receipt.ocr_result.extracted_amount) == 50
    assert c.receipt.ocr_result.extraction_confidence is None


@pytest.mark.slow
def test_real_ocr_receipt_image_and_pdf(tmp_path):
    pytest.importorskip('rapidocr_onnxruntime')
    from backend.app.ocr.engine import ocr_engine
    from backend.app.ocr.preprocess import _load_image
    from backend.app.ocr.extractor import extract_fields
    img = Image.new('RGB', (1000,600), 'white')
    font = ImageFont.load_default(size=36)
    ImageDraw.Draw(img).multiline_text((60,60), 'ACME STORE\nDate: 2025-01-01\nTotal: $123.45', font=font, fill='black', spacing=30)
    for ext in ['png', 'pdf']:
        path = tmp_path / f'receipt.{ext}'
        img.save(path)
        text, confidence, method = ocr_engine.extract_text(_load_image(str(path)))
        fields = extract_fields(text, use_llm_fallback=False)
        assert method != 'failed' and confidence > .6
        assert fields['amount'] == pytest.approx(123.45)


def test_claim_import_with_autoflush_disabled_creates_one_policy_per_claim(api):
    from backend.app.models.policy import ClaimPolicy
    client, session = api
    session.autoflush = False
    data = b"claim_id,employee_id,employee_name,claimed_amount,vendor_name,claimed_date\nUPLOAD-ONE,E,Employee,4500,Vendor,2025-01-02\nUPLOAD-TWO,E,Employee,45000,Vendor,2025-01-03\n"
    response = client.post('/api/v1/claims/upload',files={'file':('claims.csv',data,'text/csv')})
    assert response.status_code == 200, response.text
    assert response.json()['error_count'] == 0
    assert session.query(ClaimPolicy).filter(ClaimPolicy.claim_id.in_(['UPLOAD-ONE','UPLOAD-TWO'])).count() == 2
    response = client.post('/api/v1/claims/upload',files={'file':('claims.csv',data,'text/csv')})
    assert response.status_code == 200, response.text
    assert session.query(ClaimPolicy).filter(ClaimPolicy.claim_id.in_(['UPLOAD-ONE','UPLOAD-TWO'])).count() == 2
