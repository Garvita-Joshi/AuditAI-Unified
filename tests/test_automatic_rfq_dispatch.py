from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api import sourcing
from backend.app.agentic_ai import dispatch, messaging
from backend.app.agentic_ai.records import AgentRun, AgentVendor, AgentActivity
from backend.app.procurement.request_records import RequestArchive, RequestRecordEvent


@pytest.fixture
def workspace(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    for model in (sourcing.User, sourcing.SourcingRequest, AgentRun, AgentVendor, AgentActivity, RequestArchive, RequestRecordEvent):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    row = sourcing.SourcingRequest(owner_id=1, status='ready_for_research', requirements={
        'product':'Headsets', 'quantity':10, 'budget':'10000.00', 'currency':'INR',
        'delivery_deadline':'2026-12-01', 'delivery_location':'Jaipur, India',
        'specifications':'USB', 'mandatory_conditions':'One year warranty'})
    session.add(row); session.commit()
    user = SimpleNamespace(id=1, email='buyer@company.com')
    smtp = Mock(return_value={'recipient':'supplier@business.com','ref_token':'tracking-reference'})
    monkeypatch.setattr(dispatch, 'send_rfq', smtp)
    monkeypatch.setattr(messaging, 'fetch_inbox_replies', lambda run_id: [])
    monkeypatch.setattr(sourcing, 'mailbox_status', lambda: {'configured':True,'from_email':'prepares23@gmail.com'})
    monkeypatch.setattr(sourcing, 'run_sourcing_agent', lambda brief: {'drafts':[{
        'offer':{'vendor_id':'V001','vendor_name':'Company supplier','email':'supplier@business.com','sku':'H1'},
        'rank':1,'score':90,'reasons':['Product match'],'rfq_subject':'Headsets quotation',
        'rfq_body':'Please quote ten USB headsets.','status':'needs_vendor_confirmation'}]})
    yield session, row, user, smtp
    session.close(); engine.dispose()


def test_start_sends_without_email_approval_and_records_the_smtp_result(workspace):
    db, row, user, smtp = workspace
    result = sourcing.start_sourcing_agent(row.id, db, user)
    assert smtp.call_count == 1
    vendor = result['vendors'][0]
    assert vendor['rfq_approved'] is False
    assert vendor['sent_at'] is not None
    assert vendor['status'] == 'rfq_sent'
    assert result['summary']['sent_count'] == 1
    assert result['status'] == 'outreach_in_progress'
    events = db.query(AgentActivity).all()
    assert [event.event for event in events][-2:] == ['rfq_send_started','rfq_sent']
    assert events[-1].details['automatic'] is True
    assert events[-1].details['requested_by'] == user.email


def test_restarting_same_brief_does_not_create_another_batch_or_send_again(workspace):
    db, row, user, smtp = workspace
    first = sourcing.start_sourcing_agent(row.id, db, user)
    second = sourcing.start_sourcing_agent(row.id, db, user)
    assert first['id'] == second['id']
    assert db.query(AgentRun).count() == 1
    assert smtp.call_count == 1


def test_smtp_failure_is_logged_and_only_retried_explicitly(workspace):
    db, row, user, smtp = workspace
    smtp.side_effect = RuntimeError('SMTP connection failed')
    result = sourcing.start_sourcing_agent(row.id, db, user)
    vendor = db.query(AgentVendor).one()
    assert vendor.status == 'send_failed' and vendor.sent_at is None
    assert result['vendors'][0]['send_error'] == 'SMTP connection failed'
    run = db.query(AgentRun).one()
    dispatch.dispatch_rfqs(db, run, user.email)
    assert smtp.call_count == 1
    smtp.side_effect = None
    retry = sourcing.send_ai_rfqs(row.id, run.id, sourcing.SendRfqsInput(vendor_ids=[vendor.id]), db, user)
    assert retry['sent_count'] == 1
    assert smtp.call_count == 2
    assert db.query(AgentVendor).one().rfq_approved is False


def test_parallel_sync_cannot_claim_an_email_that_is_already_sending(workspace):
    db, row, user, smtp = workspace
    nested_results = []
    def send(*args, **kwargs):
        with sessionmaker(bind=db.get_bind())() as other:
            run = other.query(AgentRun).one()
            nested_results.append(dispatch.dispatch_rfqs(other, run, user.email))
        return {'recipient':'supplier@business.com'}
    smtp.side_effect = send
    result = sourcing.start_sourcing_agent(row.id, db, user)
    assert smtp.call_count == 1
    assert nested_results[0]['sent_count'] == 0
    assert result['summary']['sent_count'] == 1


@pytest.mark.parametrize('offer_changes', [
    {'email':''}, {'email':'contact@vendor.example'}, {'is_external':True}])
def test_missing_placeholder_and_unverified_contacts_are_not_auto_emailed(workspace, monkeypatch, offer_changes):
    db, row, user, smtp = workspace
    original = sourcing.run_sourcing_agent(row.requirements)
    original['drafts'][0]['offer'].update(offer_changes)
    monkeypatch.setattr(sourcing, 'run_sourcing_agent', lambda brief: original)
    result = sourcing.start_sourcing_agent(row.id, db, user)
    assert smtp.call_count == 0
    assert result['vendors'][0]['status'] == 'contact_required'
    assert result['vendors'][0]['sent_at'] is None
    assert result['summary']['dispatch_attention_count'] == 1
    if offer_changes.get('email') == '':
        assert result['vendors'][0]['email'] == ''
