"""One provisioned identity authenticates expense and procurement routes by OTP."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.app.main import app
from backend.app.db import Base, get_db
from backend.app.models.auth import AuthUser
from backend.app.api import auth


def test_otp_identity_accesses_both_modules_and_requires_provisioning(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def db_override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    codes = {}
    monkeypatch.setattr(auth, 'deliver_otp', lambda email, code: codes.update({email: code}))
    with factory() as db:
        db.add(AuthUser(email='employee@auditai.example', employee_id='EMP-U', display_name='Unified employee', roles=['employee'], role='employee', password_hash='unused-test-hash'))
        db.commit()
    try:
        with TestClient(app) as client:
            assert client.post('/api/v1/auth/request-otp', json={'email':'unknown@auditai.example'}).status_code == 403
            assert client.post('/api/v1/auth/request-otp', json={'email':'employee@auditai.example'}).status_code == 200
            response = client.post('/api/v1/auth/verify-otp', json={'email':'employee@auditai.example','code':codes['employee@auditai.example']})
            assert response.status_code == 200, response.text
            payload=response.json()
            assert payload['user']['employee_id']=='EMP-U'
            headers={'Authorization': 'Bearer '+payload['access_token']}
            assert client.get('/api/v1/claims',headers=headers).status_code==200
            assert client.get('/api/v1/procurement/requests',headers=headers).status_code==200
            assert client.post('/api/v1/fraud/score',headers=headers).status_code==403
            assert client.post('/api/v1/auth/refresh').status_code==200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
