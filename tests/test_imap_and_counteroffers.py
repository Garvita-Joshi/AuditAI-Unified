import pytest
from backend.app.agentic_ai.messaging import _parse_email_message


def test_parse_email_message_plain_text():
    raw_email = (
        b"From: prepares23@gmail.com\r\n"
        b"To: prepares23@gmail.com\r\n"
        b"Subject: Re: Commercial RFQ: 50x Laptops [Ref: AuditAI-R12-V34]\r\n"
        b"Date: Wed, 12 Nov 2026 19:40:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"We accept your RFQ. We can supply at INR 280,000 with 5 days delivery and 2 years warranty.\r\n"
        b"\r\n"
        b"On Wed, Nov 12, 2026 at 7:30 PM <prepares23@gmail.com> wrote:\r\n"
        b"> COMMERCIAL REQUEST FOR QUOTATION (RFQ)\r\n"
        b"> Tracking Ref Code: [AuditAI-R12-V34]\r\n"
    )
    parsed = _parse_email_message(raw_email, "101")
    assert parsed is not None
    assert parsed['run_id'] == 12
    assert parsed['vendor_id'] == 34
    assert "280,000" in parsed['clean_reply']
    assert "COMMERCIAL REQUEST FOR QUOTATION" not in parsed['clean_reply']


def test_parse_email_message_html_only():
    raw_email = (
        b"From: supplier@prepares.com\r\n"
        b"To: prepares23@gmail.com\r\n"
        b"Subject: Re: Round 1 Policy Counteroffer: [Ref: AuditAI-R5-V8] - Tech Supply\r\n"
        b"Date: Wed, 12 Nov 2026 19:42:00 +0000\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>We accept your revised counteroffer of INR 250,000 all inclusive.</p>"
        b"<blockquote>On Nov 12, 2026 wrote:<br>COMMERCIAL REQUEST FOR QUOTATION (RFQ)</blockquote>"
        b"</body></html>"
    )
    parsed = _parse_email_message(raw_email, "102")
    assert parsed is not None
    assert parsed['run_id'] == 5
    assert parsed['vendor_id'] == 8
    assert "We accept your revised counteroffer" in parsed['clean_reply']


def test_parse_email_message_ignores_own_outbound_rfq():
    raw_email = (
        b"From: prepares23@gmail.com\r\n"
        b"To: prepares23@gmail.com\r\n"
        b"Subject: Commercial RFQ: 50x Laptops [Ref: AuditAI-R1-V1]\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"COMMERCIAL REQUEST FOR QUOTATION (RFQ)\r\n"
        b"Vendor Addressee : Supplier\r\n"
        b"Tracking Ref Code: [AuditAI-R1-V1]\r\n"
    )
    parsed = _parse_email_message(raw_email, "103")
    assert parsed is None


def test_autonomous_cycle_dispatches_counteroffer_even_when_poll_inbox_is_false(monkeypatch):
    from unittest.mock import Mock
    from datetime import datetime
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from backend.app.api import sourcing
    from backend.app.agentic_ai.records import AgentRun, AgentVendor, AgentActivity
    from backend.app.procurement.request_records import RequestArchive, RequestRecordEvent

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    for model in (sourcing.User, sourcing.SourcingRequest, AgentRun, AgentVendor, AgentActivity, RequestArchive, RequestRecordEvent):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()

    row = sourcing.SourcingRequest(
        owner_id=1, status='outreach_in_progress', requirements={
            'product': 'Laptops', 'quantity': 10, 'budget': '100000.00', 'currency': 'INR',
            'delivery_deadline': '2026-12-01', 'delivery_location': 'Jaipur, India'
        }
    )
    session.add(row)
    session.commit()

    run = AgentRun(request_id=row.id, owner_id=1, status='outreach_in_progress')
    session.add(run)
    session.commit()

    vendor = AgentVendor(
        run_id=run.id,
        vendor_id='V1',
        offer_id='OFF-1',
        vendor_name='Tech Dynamics',
        vendor_email='tech@prepares.com',
        rank=1,
        score=95.0,
        status='rfq_sent',
        sent_at=datetime.utcnow(),
        rfq_subject='Commercial RFQ: 10x Laptops',
        rfq_body='Please quote.',
        offer={'vendor_id': 'V1', 'vendor_name': 'Tech Dynamics'}
    )
    session.add(vendor)
    session.commit()

    dispatched = []
    def mock_send(to_email, subject, body, **kwargs):
        dispatched.append({'to': to_email, 'subject': subject, 'body': body})
        return {'recipient': to_email, 'ref_token': f"AuditAI-R{run.id}-V{vendor.id}", 'delivered': True}

    monkeypatch.setattr('backend.app.agentic_ai.messaging.send_rfq', mock_send)
    monkeypatch.setattr('backend.app.api.sourcing.send_rfq', mock_send)
    monkeypatch.setattr(sourcing, 'mailbox_status', lambda: {'configured': True, 'from_email': 'prepares23@gmail.com'})

    inbox_replies = [{
        'vendor_id': vendor.id,
        'clean_reply': 'We can quote INR 120,000 for 10 laptops. Delivery in 5 business days, 2 years warranty.',
        'from_addr': 'tech@prepares.com',
        'subject': f'Re: Commercial RFQ: 10x Laptops [Ref: AuditAI-R{run.id}-V{vendor.id}]',
        'date_str': 'Wed, 12 Nov 2026 19:45:00 +0000',
        'message_id': '2001',
    }]

    # Run tick as background_worker does (poll_inbox=False with prefetched_replies)
    sourcing.process_autonomous_sourcing_cycle(
        db=session,
        run=run,
        row=row,
        user_email='prepares23@gmail.com',
        dispatch_pending=False,
        poll_inbox=False,
        prefetched_replies=inbox_replies,
    )

    session.refresh(vendor)
    assert len(dispatched) == 1
    assert dispatched[0]['to'] == 'tech@prepares.com'
    assert f"AuditAI-R{run.id}-V{vendor.id}" in dispatched[0]['subject']
    assert "Round 1" in dispatched[0]['subject']
    assert vendor.status == 'negotiation_counteroffer_sent'
    assert vendor.offer['negotiation_data']['counteroffer_dispatched'] is True

    session.close()
    engine.dispose()
