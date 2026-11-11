from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.app.api.procurement import router
from backend.app.api.procurement_payments import router as payments_router
from backend.app.api.procurement_extraction import router as extraction_router
from backend.app.core.security import require_authenticated_user
from backend.app.db import get_db
from backend.app.models.auth import User
from backend.app.models.procurement import (PurchaseRequest, PurchaseOrder, SupplierInvoice, ProcurementContext, ProcurementEvent, ProcurementDocument, InvoiceRevision, ProcurementPayment, ApprovalStep, ApprovalSubtask, ProcurementNotification)
from backend.app.procurement.request_records import RequestArchive, RequestRecordEvent
from backend.app.procurement.contracts import PurchaseTerms, InvoiceCreate, match_invoice


def terms(**changes):
    data = dict(supplier_id="supplier-a", recipient_id="merchant-a", currency="USD",
                items=[dict(sku="H-1", description="Headset", quantity=20, unit_price="25.00")],
                delivery="0.00", tax="0.00")
    data.update(changes)
    return data


def test_exact_money_and_extra_fee_evidence():
    approved = PurchaseTerms(**terms())
    invoice = InvoiceCreate(invoice_number="I-1", terms=terms(delivery="45.00"), stated_total="545.00")
    differences = match_invoice(approved, invoice)
    assert approved.total == Decimal("500.00")
    assert {d["field"] for d in differences} == {"delivery", "approved_total"}


def test_recipient_and_arithmetic_are_independent_checks():
    invoice = InvoiceCreate(invoice_number="I-1", terms=terms(recipient_id="attacker"), stated_total="499.00")
    fields = {d["field"] for d in match_invoice(PurchaseTerms(**terms()), invoice)}
    assert fields == {"recipient_id", "invoice_arithmetic", "approved_total"}


def test_duplicate_skus_and_fractional_cents_rejected():
    with pytest.raises(ValidationError):
        PurchaseTerms(**terms(items=terms()["items"] * 2))
    with pytest.raises(ValidationError):
        PurchaseTerms(**terms(delivery="0.001"))


@pytest.fixture
def api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, PurchaseRequest, PurchaseOrder, SupplierInvoice, ProcurementContext, ProcurementEvent, ProcurementDocument, InvoiceRevision, ProcurementPayment, ApprovalStep, ApprovalSubtask, ProcurementNotification, RequestArchive, RequestRecordEvent):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    users = [User(email="requester@example.test", role="auditor"),
             User(email="manager@example.test", role="manager"),
             User(email="other@example.test", role="auditor"),
             User(email="finance@example.test", role="finance"),
             User(email="security@example.test", role="security"),
             User(email="admin@example.test", role="admin")]
    for index, user in enumerate(users):
        user.employee_id = f"EMP-{index}"
        user.display_name = user.email.split("@")[0]
        user.roles = [user.role]
        user.password_hash = "unused-test-hash"
    session.add_all(users)
    session.commit()
    actor = {"user": users[0]}
    app = FastAPI()
    app.include_router(router)
    app.include_router(payments_router)
    app.include_router(extraction_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[require_authenticated_user] = lambda: actor["user"]
    with TestClient(app) as client:
        yield client, actor, users
    session.close()
    engine.dispose()


def create(client):
    response = client.post('/api/v1/procurement/requests', json={"title":"Headsets", "budget_limit":"600.00", "terms":terms()})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _approve_chain(client, actor, users, request_id, *, personal=False):
    path=f"/api/v1/procurement/requests/{request_id}"
    roles={"manager":1,"admin":5,"finance":3,"security":4}
    detail=client.get(path).json()
    for step in detail["approval_steps"]:
        actor["user"]=users[roles[step["role"]]]
        for subtask in step["subtasks"]:
            done=client.patch(f"{path}/steps/{step['id']}/subtasks/{subtask['id']}",
                json={"status":"done","reason":"Verified against source documents."})
            assert done.status_code==200, done.text
        result=client.post(f"{path}/steps/{step['id']}/decision",
            json={"action":"approve","note":"Reviewed and approved independently."})
        assert result.status_code==200, result.text
    actor["user"]=users[0]
    return client.get(path).json()


def test_independent_approval_snapshot_matching_and_duplicate_block(api):
    client, actor, users = api
    request_id = create(client)
    path = f'/api/v1/procurement/requests/{request_id}'
    assert [s['role'] for s in client.get(path).json()['approval_steps']] == ['manager','admin','finance']
    actor['user'] = users[1]
    detail=client.get(path).json()
    manager=detail['approval_steps'][0]
    response=client.post(f"{path}/steps/{manager['id']}/decision",json={'action':'approve','note':'Manager review.'})
    assert response.status_code==200
    procurement=client.get(path).json()['approval_steps'][1]
    actor['user']=users[5]
    assert client.post(f"{path}/steps/{procurement['id']}/decision",json={'action':'approve','note':'Try early.'}).status_code==409
    for task in procurement['subtasks']:
        result=client.patch(f"{path}/steps/{procurement['id']}/subtasks/{task['id']}",json={'status':'done','reason':'Reviewed source quote.'})
        assert result.status_code==200
    assert client.post(f"{path}/steps/{procurement['id']}/decision",json={'action':'approve','note':'Procurement review.'}).status_code==200
    actor['user']=users[3]
    finance=client.get(path).json()['approval_steps'][2]
    assert client.post(f"{path}/steps/{finance['id']}/decision",json={'action':'approve','note':'Finance checked.'}).status_code==200
    detail=client.get(path).json()
    order=detail['order']
    assert order is not None
    assert client.post(f"{path}/steps/{finance['id']}/decision",json={'action':'approve','note':'Duplicate'}).status_code==409
    actor['user'] = users[0]
    payload = {"invoice_number":"INV-1", "terms":terms(), "stated_total":"500.00"}
    invoice_path = f'/api/v1/procurement/orders/{order["id"]}/invoices'
    matched = client.post(invoice_path, json=payload)
    assert matched.status_code == 201, matched.text
    assert matched.json()['status'] == 'matched'
    assert matched.json()['payment_eligible'] is False
    assert client.post(invoice_path, json=payload).status_code == 409
    actor['user'] = users[2]
    assert client.get('/api/v1/procurement/requests').json() == []
    assert client.post(invoice_path, json={**payload, "invoice_number":"INV-2"}).status_code == 404


def test_manager_cannot_self_approve_and_overbudget_request_rejected(api):
    client, actor, users = api
    actor['user'] = users[1]
    request_id = create(client)
    assert client.post(f'/api/v1/procurement/requests/{request_id}/approve').status_code == 403
    response = client.post('/api/v1/procurement/requests', json={"title":"Too expensive", "budget_limit":"400.00", "terms":terms()})
    assert response.status_code == 422


def approved_order(api, personal=False):
    client, actor, users = api
    actor['user'] = users[0]
    result = client.post('/api/v1/procurement/requests', json={"title":"Support headsets", "budget_limit":"600.00", "terms":terms(),
        "details":{"shares_personal_data":personal,"data_types":["Personal Data (e.g. name, email, location, etc.)"] if personal else [],"data_usage":"Support team names" if personal else ""}})
    assert result.status_code==201, result.text
    request_id = result.json()['id']
    detail=_approve_chain(client,actor,users,request_id,personal=personal)
    return request_id, detail['order']['id']


def test_conditional_security_and_no_early_po(api):
    client, actor, users = api
    request_id, order_id = approved_order(api, True)
    detail = client.get(f'/api/v1/procurement/requests/{request_id}').json()
    assert [s['role'] for s in detail['workflow']] == ['manager','admin','finance','security']
    assert all(s['status']=='approved' for s in detail['workflow'])
    assert detail['order']['id'] == order_id
    assert len(detail['events']) == 7



def test_required_subtasks_gate_approval_and_actions_are_audited(api):
    client, actor, users=api
    request_id=create(client)
    path=f"/api/v1/procurement/requests/{request_id}"
    actor['user']=users[1]
    first=client.get(path).json()['approval_steps'][0]
    assert client.post(f"{path}/steps/{first['id']}/decision",json={'action':'approve','note':'Manager checked.'}).status_code==200
    actor['user']=users[5]
    procurement=client.get(path).json()['approval_steps'][1]
    blocked=client.post(f"{path}/steps/{procurement['id']}/decision",json={'action':'approve','note':'Attempt before tasks.'})
    assert blocked.status_code==409
    for subtask in procurement['subtasks']:
        assert client.patch(f"{path}/steps/{procurement['id']}/subtasks/{subtask['id']}",
            json={'status':'done','reason':'Quote and order form checked.'}).status_code==200
    assert client.post(f"{path}/steps/{procurement['id']}/decision",json={'action':'approve','note':'Procurement approved.'}).status_code==200
    events=client.get(path).json()['events']
    actions=[event['action'] for event in events]
    assert actions.count('subtask_completed')==2
    approval=next(event for event in events if event['action']=='approval_approve' and event['details'].get('step_id')==procurement['id'])
    assert approval['details']['reason']=='Procurement approved.'
    assert all(event['details'].get('step_id') for event in events if event['action'].startswith('approval_') or event['action']=='subtask_completed')


def test_inr_threshold_adds_final_human_approval(api):
    client,actor,users=api
    payload={'title':'INR threshold test','budget_limit':'150000.00',
        'terms':terms(currency='INR',items=[dict(sku='LAP-1',description='Laptop',quantity=1,unit_price='120000.00')])}
    result=client.post('/api/v1/procurement/requests',json=payload)
    assert result.status_code==201, result.text
    steps=client.get(f"/api/v1/procurement/requests/{result.json()['id']}").json()['approval_steps']
    assert [step['role'] for step in steps]==['manager','admin','finance','admin']
    assert steps[-1]['name']=='Final approval'


def test_exception_correction_history_and_review(api):
    client, actor, users = api
    request_id, order_id = approved_order(api)
    original = {"invoice_number":"INV-EX", "terms":terms(delivery="45.00"), "stated_total":"545.00"}
    response = client.post(f'/api/v1/procurement/orders/{order_id}/invoices', json=original)
    assert response.status_code == 201, response.text
    invoice_id = response.json()['invoice_id']
    assert response.json()['status'] == 'exception'
    assert client.get('/api/v1/procurement/requests').json()[0]['invoice_status'] == 'exception'
    assert client.post(f'/api/v1/procurement/invoices/{invoice_id}/request-correction').status_code == 200
    assert client.post(f'/api/v1/procurement/invoices/{invoice_id}/checkout').status_code == 409
    actor['user'] = users[3]
    assert client.post(f'/api/v1/procurement/invoices/{invoice_id}/review',json={'note':'Wrong invoice'}).status_code == 409
    corrected = {**original,"terms":terms(),"stated_total":"500.00"}
    response = client.post(f'/api/v1/procurement/invoices/{invoice_id}/correct',json=corrected)
    assert response.json()['status'] == 'matched'
    versions = client.get(f'/api/v1/procurement/invoices/{invoice_id}/revisions').json()
    assert len(versions) == 2
    assert versions[0]['payload']['stated_total'] == '545.00'
    assert versions[1]['payload']['stated_total'] == '500.00'
    actor['user'] = users[0]
    assert client.post(f'/api/v1/procurement/invoices/{invoice_id}/review',json={'note':'Self'}).status_code == 403
    actor['user'] = users[3]
    assert client.post(f'/api/v1/procurement/invoices/{invoice_id}/review',json={'note':'Checked corrected source invoice and supplier.'}).status_code == 200
    assert client.post(f'/api/v1/procurement/invoices/{invoice_id}/correct',json=corrected).status_code == 409


def test_more_info_resubmit_and_visibility(api):
    client, actor, users = api
    request_id = create(client)
    actor['user'] = users[1]
    path = f'/api/v1/procurement/requests/{request_id}'
    assert client.post(path+'/decision',json={'action':'request_info','note':''}).status_code == 422
    assert client.post(path+'/decision',json={'action':'request_info','note':'What is the business purpose?'}).json()['status']=='needs_info'
    actor['user'] = users[2]
    assert client.get(path).status_code == 404
    assert client.post(path+'/comments',json={'note':'Other user'}).status_code == 404
    actor['user'] = users[0]
    assert client.post(path+'/resubmit',json={'note':'For support staff.'}).json()['status']=='submitted'
    assert client.post(path+'/comments',json={'note':'   '}).status_code == 422


def test_documents_are_scoped_and_downloadable(api, monkeypatch, tmp_path):
    from backend.app import config
    monkeypatch.setattr(config,'UPLOAD_DIR',tmp_path)
    client, actor, users = api
    request_id = create(client)
    response = client.post(f'/api/v1/procurement/requests/{request_id}/documents',files={'file':('quote.txt',b'20 headsets at $25 each','text/plain')})
    assert response.status_code == 201, response.text
    document_id = response.json()['id']
    assert client.get(f'/api/v1/procurement/documents/{document_id}').content == b'20 headsets at $25 each'
    assert client.post(f'/api/v1/procurement/requests/{request_id}/documents',files={'file':('script.html',b'<script/>','text/html')}).status_code == 422
    actor['user'] = users[2]
    assert client.get(f'/api/v1/procurement/documents/{document_id}').status_code == 404


def test_sandbox_capture_reconciles_and_does_not_repeat(api,monkeypatch):
    from backend.app.procurement import paypal
    client, actor, users = api
    request_id, order_id = approved_order(api)
    response=client.post(f'/api/v1/procurement/orders/{order_id}/invoices',json={'invoice_number':'INV-PAY','terms':terms(),'stated_total':'500.00'})
    invoice_id=response.json()['invoice_id']
    actor['user']=users[3]
    client.post(f'/api/v1/procurement/invoices/{invoice_id}/review',json={'note':'Identity and invoice independently checked.'})
    monkeypatch.setattr(paypal,'configured',lambda:True)
    monkeypatch.setattr(paypal,'configuration',lambda:{'merchant_id':'merchant-a'})
    state={'status':'CREATED'}
    calls=[]
    def provider(method,path,payload=None,request_id=None):
        calls.append((method,path,request_id))
        if path.endswith('/capture'):
            state['status']='COMPLETED'
        response={'id':'ORDER-1','status':state['status'],'purchase_units':[{'custom_id':f'auditai-invoice-{invoice_id}',
            'payee':{'merchant_id':'merchant-a'},'amount':{'currency_code':'USD','value':'500.00'}}],
            'links':[{'rel':'approve','href':'https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1'}]}
        if state['status']=='COMPLETED':
            response['purchase_units'][0]['payments']={'captures':[{'id':'CAP-1','status':'COMPLETED','amount':{'currency_code':'USD','value':'500.00'}}]}
        return response
    monkeypatch.setattr(paypal,'call',provider)
    actor['user']=users[0]
    path=f'/api/v1/procurement/invoices/{invoice_id}'
    assert client.post(path+'/checkout').status_code==200
    assert client.post(path+'/capture').status_code==409
    state['status']='APPROVED'
    assert client.post(path+'/capture').json()['status']=='completed'
    assert client.post(path+'/capture').json()['status']=='completed'
    assert sum(method=='POST' and p.endswith('/capture') for method,p,key in calls)==1
    detail=client.get(f'/api/v1/procurement/requests/{request_id}').json()
    assert detail['invoices'][0]['status']=='paid'


def test_payment_rejects_recipient_or_amount_substitution():
    from types import SimpleNamespace
    from fastapi import HTTPException
    from backend.app.api.procurement_payments import verify_order
    invoice=SimpleNamespace(id=1,terms={'recipient_id':'merchant-a'},stated_total=Decimal('500.00'))
    provider={'purchase_units':[{'custom_id':'auditai-invoice-1','payee':{'merchant_id':'attacker'},'amount':{'currency_code':'USD','value':'500.00'}}]}
    with pytest.raises(HTTPException):
        verify_order(provider,invoice)
    provider['purchase_units'][0]['payee']['merchant_id']='merchant-a'
    provider['purchase_units'][0]['amount']['value']='501.00'
    with pytest.raises(HTTPException):
        verify_order(provider,invoice)


def test_model_score_does_not_depend_on_batch_context():
    from backend.app.procurement.risk import assess
    approved=PurchaseTerms(**terms())
    a=assess(approved,approved,[450,500,550])
    if a['status']=='unavailable':
        pytest.skip('Train the optional procurement bundle to run inference checks.')
    assess(PurchaseTerms(**terms(delivery='200.00')),approved,[450,500,550])
    b=assess(approved,approved,[450,500,550])
    assert a==b
    assert a['version']=='procurement-v1-synthetic'
    assert 0<=a['score']<=1


def test_invoice_identifiers_canonicalized_and_zero_orders_rejected():
    from backend.app.procurement.contracts import RequestCreate
    invoice=InvoiceCreate(invoice_number='  inv-001  ',terms=terms(),stated_total='500.00')
    assert invoice.invoice_number=='INV-001'
    with pytest.raises(ValidationError):
        InvoiceCreate(invoice_number='   ',terms=terms(),stated_total='500.00')
    with pytest.raises(ValidationError):
        RequestCreate(title='Zero',budget_limit='10.00',terms=terms(items=[dict(sku='ZERO',description='Zero',quantity=1,unit_price='0.00')]))


def test_quote_extraction_requires_configuration(api,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    client,actor,users=api
    response=client.post('/api/v1/procurement/extract-quote',files={'file':('quote.txt',b'20 headsets at $25','text/plain')})
    assert response.status_code==503
    assert 'manually' in response.json()['detail']
