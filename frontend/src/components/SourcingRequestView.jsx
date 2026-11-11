import React, { useEffect, useState } from 'react';
import { ArrowLeft, FileText, Pencil, RefreshCw, Network, Bot, CheckCircle2, Clock } from 'lucide-react';
import { sourcingApi } from '../api/client';
import { WorkflowMindMap, SourcingAgentReview } from '../pages/PurchaseIntake';
import AuditTimeLogModal from './AuditTimeLogModal';
import './SourcingRequestView.css';

export const sourcingStatus = status => ({
  draft: 'Draft', ready_for_research: 'Ready for sourcing',
  vendors_shortlisted: 'Vendors shortlisted', awaiting_vendor_replies: 'Awaiting vendor replies',
  sending_rfqs: 'Sending RFQs', quotes_received: 'Quotes received · more pending', quotes_ready: 'Quotes ready for comparison',
  outreach_attention_required: 'Outreach needs attention', recommendation_ready: 'Recommendation ready',
  requirements_changed: 'Requirements changed · analysis needed', no_vendor_matches: 'No vendor matches',
  deleted: 'Deleted', submitted: 'Awaiting approval', needs_info: 'Needs information', approved: 'Approved', rejected: 'Rejected'
}[status] || String(status || 'Draft').replaceAll('_', ' '));
const errorText = e => e.response?.data?.detail || e.message || 'Unable to load the saved request.';

export default function SourcingRequestView({ id, onBack, onEdit }) {
  const [row, setRow] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [showVendors, setShowVendors] = useState(true), [run, setRun] = useState(null), [selected, setSelected] = useState([]);
  const [showAuditModal, setShowAuditModal] = useState(false);

  const load = async () => {
    try {
      const { data } = await sourcingApi.detail(id);
      setRow(data);
      setRun(data.agent_run || null);
    } catch (e) {
      setError(errorText(e));
    }
  };

  useEffect(() => {
    let active = true;
    const fetchDetail = () => {
      sourcingApi.detail(id).then(({ data }) => {
        if (active) {
          setRow(data);
          setRun(data.agent_run || null);
        }
      }).catch(e => {
        if (active) setError(errorText(e));
      });
    };
    fetchDetail();
    // Continuous live polling (every 4s) so background agent actions & incoming quotes reflect in real time
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        fetchDetail();
      }
    }, 4000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id]);

  const action = async fn => { setBusy(true); setError(''); try { return await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } };
  const update = async method => { const { data } = await method(); setRun(data.run || data); return data; };
  if (!row) return <section className="p-panel">{error ? <p role="alert">{error}</p> : <p>Loading saved request…</p>}<button className="p-link" onClick={onBack}>Back to requests</button></section>;
  const req = row.requirements, plan = row.workspace?.workflow || row.workflow_preview;
  const currency = req.currency || 'INR', money = value => new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en-US', { style: 'currency', currency }).format(Number(value || 0));
  const sum = (req.line_items || []).reduce((n, item) => n + Number(item.quantity || 0) * Number(item.unit_price || 0), 0);

  return <section className="p-request-record" aria-label="Saved request mind map">
    <div className="p-record-toolbar">
      <button className="p-link" onClick={onBack}><ArrowLeft size={15} />Back to requests</button>
      <div>
        <button className="p-button" disabled={busy} onClick={() => action(load)}><RefreshCw size={14} />Refresh status</button>
        <button className="p-button cv-audit-btn" onClick={() => setShowAuditModal(true)} title="View immutable chronological audit time log trail"><Clock size={14} />Audit Time Log</button>
        <button className="p-button primary" onClick={onEdit}><Pencil size={14} />Edit form</button>
      </div>
    </div>
    {error && <p className="p-notice p-danger" role="alert">{error}</p>}

    {/* Request Brief Summary */}
    <section className="p-panel p-record-brief">
      <div>
        <span className="p-eyebrow">SR-{String(row.id).padStart(4, '0')} · SAVED PURCHASE REQUEST</span>
        <h2>{req.product || 'Untitled purchase request'}</h2>
        <p>Form details are read-only here. Choose Edit form to make changes.</p>
      </div>
      <span className={`p-record-status status-${row.current_status}`}>{sourcingStatus(row.current_status)}</span>
      <dl>
        <div><dt>Budget</dt><dd>{money(req.budget)}</dd></div>
        <div><dt>Estimated line total</dt><dd>{money(sum)}</dd></div>
        <div><dt>Purchase type</dt><dd>{req.purchase_type || 'Not specified'}</dd></div>
        <div><dt>Department</dt><dd>{req.department || req.line_items?.[0]?.department || 'Not specified'}</dd></div>
        <div><dt>Category</dt><dd>{req.category || 'Not specified'}</dd></div>
        <div><dt>Personal data shared</dt><dd>{req.data_sharing_choice === 'yes' ? 'Yes' : req.data_sharing_choice === 'no' ? 'No' : req.data_sharing_choice === 'unknown' ? 'Not yet confirmed' : 'Not specified'}</dd></div>
      </dl>
      {row.progress?.vendors > 0 && <div className="p-record-progress"><span>{row.progress.vendors} shortlisted</span><span>{row.progress.sent} RFQs accepted</span><span>{row.progress.replies} replies</span><span>{row.progress.pending} pending</span></div>}
    </section>

    {/* Section 1: Workflow Mind Map */}
    <section className="p-panel p-record-map">
      <div className="p-section-heading">
        <div>
          <h2><Network size={18} />Purchase Mind Map</h2>
          <p className="p-muted">{plan?.source === 'gemini' ? 'Saved AI-generated approval route.' : 'Purchase-specific planned review route.'} Interactive workflow checkpoints and autonomous agent execution state.</p>
        </div>
        <span className="p-record-map-note">Planned checkpoints · human decisions required</span>
      </div>
      {plan?.graph ? (
        <WorkflowMindMap
          workflow={plan.graph}
          requestId={row?.id}
          assessment={row?.workspace?.workflow?.final_invoice_assessment}
          initialPaypal={row?.workspace?.workflow?.paypal_payment}
          onAssessmentComplete={() => load()}
        />
      ) : (
        <p>No workflow is saved yet. Complete the required purchase details through Edit form.</p>
      )}
    </section>

    {/* Section 2: Supplier Communication & Live Outreach (Directly visible) */}
    {run && (
      <section className="p-panel p-record-comms">
        <div className="p-section-heading">
          <div>
            <h2>Chosen Suppliers &amp; Commercial Outreach</h2>
            <p className="p-muted">Active RFQs, inbound quotations, and policy counteroffers. Click any supplier row below to view full email outreach and quote negotiation details.</p>
          </div>
          <button className="p-button" onClick={() => setShowVendors(v => !v)}>
            {showVendors ? 'Collapse suppliers' : 'Expand suppliers'}
          </button>
        </div>
        {showVendors && (
          <SourcingAgentReview
            run={run}
            rowId={row.id}
            row={row}
            request={row}
            selected={selected}
            setSelected={setSelected}
            busy={busy}
            onRunUpdated={setRun}
            onSendAiRfqs={ids => update(() => sourcingApi.sendAiRfqs(row.id, run.id, ids))}
            onReply={(vendorId, text) => action(() => update(() => sourcingApi.recordAgentReply(row.id, run.id, vendorId, text)))}
            onAddVendor={data => action(() => update(() => sourcingApi.addVendor(row.id, run.id, data)))}
            onExternalSearch={query => action(async () => { const { data } = await sourcingApi.externalSearch(row.id, query, req.delivery_location || 'India'); setRun(old => ({ ...old, public_web: data })); return data; })}
            onAnalyze={() => update(() => sourcingApi.analyzeResponses(row.id, run.id))}
          />
        )}
      </section>
    )}

    {/* Section 3: Saved Purchase Details */}
    <section className="p-panel">
      <h2><FileText size={17} />Saved purchase details</h2>
      <div className="p-table-wrap">
        <table>
          <thead>
            <tr><th>Description</th><th>Type</th><th>Quantity</th><th>Unit price</th><th>Total</th></tr>
          </thead>
          <tbody>
            {req.line_items?.map((item, index) => (
              <tr key={index}>
                <td>{item.description || 'Not specified'}</td>
                <td>{item.line_type}</td>
                <td>{item.quantity}</td>
                <td>{money(item.unit_price)}</td>
                <td>{money(Number(item.quantity) * Number(item.unit_price))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="p-record-details">
        <div><dt>Contract dates</dt><dd>{req.contract_start || 'Not specified'} → {req.contract_end || 'Not specified'}</dd></div>
        <div><dt>Payment terms</dt><dd>{req.payment_terms || 'Not specified'}</dd></div>
        <div><dt>Preferences / specifications</dt><dd>{req.specifications || 'None specified'}</dd></div>
        <div><dt>Mandatory conditions</dt><dd>{req.mandatory_conditions || 'None specified'}</dd></div>
        {req.shares_personal_data && <>
          <div><dt>Information shared</dt><dd>{req.data_types?.join(', ') || 'Not specified'}</dd></div>
          <div><dt>Supplier data use</dt><dd>{req.data_usage || 'Not specified'}</dd></div>
        </>}
      </dl>
    </section>
    {showAuditModal && (
      <AuditTimeLogModal
        requestId={row.id}
        requestKind="sourcing"
        requestTitle={req.product || 'Purchase Requisition'}
        initialAuditLog={row.audit_log}
        onClose={() => setShowAuditModal(false)}
      />
    )}
  </section>;
}
