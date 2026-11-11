"""File-backed restart tests: no SMTP, LLM, mailbox, or vendor calls."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import sourcing
from backend.app.core.security import require_authenticated_user
from backend.app.db import Base, get_db
from backend.app.models.auth import User
from backend.app.agentic_ai.records import AgentRun, AgentVendor, AgentActivity
from backend.app.procurement.request_records import RequestArchive, RequestRecordEvent


def open_server(database, actor):
    engine = create_engine(f'sqlite:///{database}', connect_args={'check_same_thread':False})
    tables = [model.__table__ for model in (User, sourcing.SourcingRequest,
        sourcing.SourcingWorkspace, sourcing.SourcingContractDocument, AgentRun, AgentVendor, AgentActivity, RequestArchive, RequestRecordEvent)]
    Base.metadata.create_all(engine, tables=tables)
    sessions = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(sourcing.router)
    def session():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_authenticated_user] = lambda: actor
    return TestClient(app), engine, sessions


def test_saved_form_plan_documents_and_agent_survive_restart(tmp_path, monkeypatch):
    actor = SimpleNamespace(id=1, email='owner@example.test', role='employee')
    path = tmp_path/'persistent.db'
    client, engine, sessions = open_server(path, actor)
    graph = {'source':'rules','nodes':[{'id':'procurement','name':'Procurement review'}], 'edges':[]}
    monkeypatch.setattr(sourcing,'generate_workflow',lambda *_: graph)
    def no_external_action(*args, **kwargs):
        raise AssertionError('Restoring saved records must not start external actions')
    monkeypatch.setattr(sourcing,'process_autonomous_sourcing_cycle',no_external_action)
    monkeypatch.setattr(sourcing,'run_sourcing_agent',no_external_action)
    monkeypatch.setattr(sourcing,'mailbox_status',lambda: {'configured':False})
    with client:
        row = client.post('/api/v1/sourcing').json()
        request_id=row['id']
        requirements={**row['requirements'],'product':'Support headsets','budget':'12000.00',
            'currency':'INR','data_sharing_choice':'yes','shares_personal_data':True,
            'data_types':['Personal Data'],'data_usage':'Delivery contact only',
            'line_items':[{'description':'Support headsets','quantity':4,'unit_price':'2000.00','department':'IT'}]}
        saved=client.put(f'/api/v1/sourcing/{request_id}',json={
            'requirements':requirements,'version':row['version'],'intake_step':2})
        assert saved.status_code==200, saved.text
        assert client.post(f'/api/v1/sourcing/{request_id}/workflow').json()==graph
        with sessions() as db:
            db.add(sourcing.SourcingContractDocument(request_id=request_id,owner_id=1,kind='msa',
                filename='agreement.pdf',storage_key='test-file-key',size=120))
            db.add(AgentRun(request_id=request_id,owner_id=1,status='awaiting_human_review',summary={}))
            db.commit()
    engine.dispose()
    # New engine, sessions and application instance, pointed at the same on-disk database.
    client, engine, sessions = open_server(path, actor)
    with client:
        rows=client.get('/api/v1/sourcing').json()
        assert len(rows)==1
        restored=client.get(f'/api/v1/sourcing/{request_id}').json()
        assert restored['requirements']['product']=='Support headsets'
        assert restored['requirements']['line_items'][0]['unit_price']=='2000.00'
        assert restored['requirements']['data_usage']=='Delivery contact only'
        assert restored['workspace']['workflow']==graph
        assert restored['workspace']['step']==2
        assert restored['agent_run']['status']=='awaiting_human_review'
        assert restored['messages'][-1]['text'].startswith('Form details saved')
        assert client.get(f'/api/v1/sourcing/{request_id}/contract-documents').json()[0]['filename']=='agreement.pdf'
        # Another employee cannot list, open or overwrite this saved request.
        actor.id=2
        assert client.get('/api/v1/sourcing').json()==[]
        assert client.get(f'/api/v1/sourcing/{request_id}').status_code==404
        assert client.put(f'/api/v1/sourcing/{request_id}',json={
            'requirements':requirements,'version':2,'intake_step':3}).status_code==404
    engine.dispose()


def test_stale_save_rolls_back_progress_and_changed_brief_invalidates_plan(tmp_path,monkeypatch):
    actor=SimpleNamespace(id=1,email='owner@example.test',role='employee')
    client,engine,_=open_server(tmp_path/'versioned.db',actor)
    monkeypatch.setattr(sourcing,'generate_workflow',lambda *_:{'nodes':[{'id':'review'}],'edges':[]})
    with client:
        row=client.post('/api/v1/sourcing').json(); url=f"/api/v1/sourcing/{row['id']}"
        saved=client.put(url,json={'requirements':{**row['requirements'],'product':'Laptops'},'version':1,'intake_step':1}).json()
        client.post(url+'/workflow')
        stale=client.put(url,json={'requirements':row['requirements'],'version':1,'intake_step':3})
        assert stale.status_code==409
        restored=client.get(url).json()
        assert restored['workspace']['step']==1
        assert restored['workspace']['workflow']['nodes']
        changed=client.put(url,json={'requirements':{**saved['requirements'],'product':'Monitors'},'version':2,'intake_step':0})
        assert changed.status_code==200
        assert client.get(url).json()['workspace']['workflow'] is None
        assert client.put(url,json={'requirements':saved['requirements'],'version':3,'intake_step':4}).status_code==422
    engine.dispose()
