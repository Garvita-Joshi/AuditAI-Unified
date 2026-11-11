"""Persist and dispatch RFQs automatically, with one claim per vendor message."""
from datetime import datetime

from sqlalchemy import update

from backend.app.agentic_ai.messaging import send_rfq
from backend.app.agentic_ai.records import AgentActivity, AgentVendor
from backend.app.procurement.request_records import is_archived

PENDING_STATUSES = {'draft_ready', 'needs_vendor_confirmation'}
SENT_STATUSES = {'rfq_sent', 'awaiting_response', 'reply_received_human_review',
                 'negotiation_counteroffer_sent'}


def _contact_error(vendor):
    if (vendor.offer or {}).get('is_external') or vendor.status == 'public_lead':
        return 'An external discovery lead needs a verified company vendor contact.'
    address = (vendor.vendor_email or '').strip().lower()
    if (not address or '@' not in address or address.endswith(('.example', '.invalid', '.test'))
            or '@example.' in address):
        return 'A deliverable company vendor email is required.'
    if address == '24uec144@lnmiit.ac.in':
        return 'This address is excluded from supplier outreach.'
    return None


def dispatch_rfqs(db, run, requested_by, vendor_ids=None, retry_failed=False):
    """Send stored drafts without human email approval; never approve a purchase.

    Claim each message before contacting SMTP so parallel start/sync requests
    cannot send it twice. Failed sends require an explicit retry. A process
    interrupted during SMTP leaves `rfq_sending` for investigation instead of
    automatically resending an email whose delivery may have succeeded.
    """
    if is_archived(db,'sourcing',run.request_id):
        return {'sent_count':0,'failed_count':0,'blocked_count':0,'already_sent':[],
                'results':[],'blocked_reason':'Request deleted; supplier outreach is stopped.'}
    query = db.query(AgentVendor).filter_by(run_id=run.id)
    if vendor_ids is not None:
        query = query.filter(AgentVendor.id.in_(vendor_ids))
    vendors = query.order_by(AgentVendor.rank).all()
    results, already_sent = [], []
    eligible = PENDING_STATUSES | ({'send_failed'} if retry_failed else set())

    def log(vendor, event, **details):
        db.add(AgentActivity(run_id=run.id, request_id=run.request_id,
            actor='Sourcing mail service', event=event, details={
                'vendor': vendor.vendor_name, 'vendor_id': vendor.id,
                'email': vendor.vendor_email, 'requested_by': requested_by,
                'automatic': True, **details}))
        try:
            from backend.app.procurement.request_records import record_action
            user_id = run.owner_id if hasattr(run, 'owner_id') else 1
            record_action(db, 'sourcing', run.request_id, user_id, event,
                          actor='Sourcing mail service',
                          vendor=vendor.vendor_name, vendor_id=vendor.id,
                          email=vendor.vendor_email, **details)
        except Exception:
            pass

    for vendor in vendors:
        if vendor.sent_at or vendor.status in SENT_STATUSES:
            already_sent.append(vendor.vendor_name)
            continue
        if vendor.status not in eligible:
            continue
        error = _contact_error(vendor)
        if error:
            vendor.status = 'contact_required'
            log(vendor, 'rfq_contact_required', error=error)
            db.commit()
            results.append({'vendor_id': vendor.id, 'vendor_name': vendor.vendor_name,
                            'email': vendor.vendor_email, 'status': 'contact_required', 'error': error})
            continue

        claimed = db.execute(update(AgentVendor).where(
            AgentVendor.id == vendor.id, AgentVendor.sent_at.is_(None),
            AgentVendor.status.in_(eligible)).values(status='rfq_sending'),
            execution_options={'synchronize_session': False}).rowcount
        if not claimed:
            db.rollback()
            continue
        log(vendor, 'rfq_send_started')
        db.commit()
        db.refresh(vendor)
        result = {'vendor_id': vendor.id, 'vendor_name': vendor.vendor_name,
                  'email': vendor.vendor_email, 'composed_by': 'ai_agent', 'simulated': False}
        try:
            response = send_rfq(vendor.vendor_email, vendor.rfq_subject, vendor.rfq_body,
                user_email=requested_by, vendor_name=vendor.vendor_name,
                run_id=run.id, vendor_id=vendor.id)
            vendor.sent_at = datetime.utcnow()
            vendor.status = 'rfq_sent'
            note = f"SMTP accepted the RFQ for {response.get('recipient', vendor.vendor_email)}."
            log(vendor, 'rfq_sent', sent=True, sent_at=vendor.sent_at.isoformat(),
                ref_token=response.get('ref_token'), note=note)
            result.update(status='rfq_sent', note=note)
        except Exception as exc:
            vendor.status = 'send_failed'
            error = str(exc)[:300]
            log(vendor, 'rfq_send_failed', sent=False, error=error)
            result.update(status='send_failed', error=error)
        db.commit()
        results.append(result)

    all_vendors = db.query(AgentVendor).filter_by(run_id=run.id).all()
    sent = sum(v.sent_at is not None for v in all_vendors)
    replied = sum(v.reply_at is not None for v in all_vendors)
    attention = sum(v.status in {'send_failed', 'contact_required'} for v in all_vendors)
    if sent and run.status != 'recommendation_ready':
        run.status = 'outreach_in_progress'
    elif attention and not sent:
        run.status = 'outreach_attention_required'
    run.summary = {**(run.summary or {}), 'automatic_rfq_dispatch': True,
        'sent_count': sent, 'pending_response_count': max(sent-replied, 0),
        'dispatch_attention_count': attention,
        'decision_note': 'RFQs are sent automatically to company vendor contacts. Final purchase approval remains with a human.'}
    db.commit()
    return {'sent_count': sum(r['status'] == 'rfq_sent' for r in results),
            'failed_count': sum(r['status'] == 'send_failed' for r in results),
            'blocked_count': sum(r['status'] == 'contact_required' for r in results),
            'already_sent': already_sent, 'results': results}
