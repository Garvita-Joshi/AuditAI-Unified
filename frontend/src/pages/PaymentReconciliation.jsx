import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CheckCircle2, RefreshCw } from 'lucide-react';
import { transfersApi, reviewQueueApi } from '../api/client';

const LABELS = {
  payment_total_mismatch: 'Payment total differs from claim amount',
  payment_for_rejected_claim: 'Payment linked to a rejected claim',
  multiple_payments_for_claim: 'Multiple payments — check for duplicate settlement',
  payment_before_checker_approval: 'Payment predates checker approval',
  payment_without_checker_approval: 'Payment has no recorded checker approval',
  checker_approval_time_unavailable: 'Approved claim has no recorded checker approval time',
  currency_mismatch: 'Payment and claim currencies differ',
  claim_currency_unavailable: 'Claim currency unavailable',
  linked_claim_missing: 'Linked claim missing',
};

export default function PaymentReconciliation() {
  const navigate=useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true); setError('');
    try { setData((await transfersApi.reconciliation()).data); }
    catch (e) { setError(e.response?.data?.detail || 'Could not reconcile payments.'); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);
  async function send(claimId) {
    setBusy(true);setError('');
    try {const item=(await reviewQueueApi.reconcile(claimId)).data;navigate(`/review-queue?case=${item.id}`);}
    catch(e){setError(e.response?.data?.detail||'Could not send finding to review.');}
    finally{setBusy(false);}
  }
  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-semibold">Payment Reconciliation</h2>
          <p className="text-secondary text-xs mt-1">
            Compare disbursement records against approved claims and recorded checker authorization events.
          </p>
        </div>
        <button className="btn btn-secondary text-xs flex items-center gap-1.5" onClick={load} disabled={busy}>
          <RefreshCw size={14} className={busy ? 'animate-spin' : ''} />
          <span>{busy ? 'Reconciling…' : 'Refresh Reconciliation'}</span>
        </button>
      </div>

      {error && <p role="alert" className="glass-card mb-4">{error}</p>}

      {data && (
        <>
          <p className="text-xs text-muted mb-4">
            {data.items.length} reconciled claims · {data.unlinked_transfers} unlinked disbursement records
          </p>
          {data.items.length === 0 && (
            <div className="glass-card flex flex-col items-center justify-center py-10 text-center">
              <div
                className="w-10 h-10 rounded-full flex items-center justify-center mb-3"
                style={{ background: 'rgba(16, 185, 129, 0.1)', color: 'var(--status-success)' }}
              >
                <CheckCircle2 size={22} />
              </div>
              <h4 className="text-sm font-semibold text-primary mb-1">No Reconciliation Discrepancies</h4>
              <p className="text-xs text-secondary max-w-md">
                All claims and corresponding settlement disbursements match approved limits and approval authorizations.
              </p>
            </div>
          )}
          {data.items.map(item => (
            <article className="glass-card mb-4" key={item.claim_id}>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-base font-semibold">
                  <Link to={`/claims/${encodeURIComponent(item.claim_id)}`} className="text-accent-primary hover:underline">
                    {item.claim_id}
                  </Link>
                  <span className="badge text-xs ml-2 uppercase">{item.claim_status}</span>
                </h3>
                {item.flags.length > 0 && (
                  <button className="btn btn-primary text-xs" disabled={busy} onClick={() => send(item.claim_id)}>
                    Send to Review
                  </button>
                )}
              </div>
              <p className="text-xs text-secondary mb-1">
                Claim: <strong>{item.claim_currency || 'INR'} {item.claim_amount}</strong> · Paid:{' '}
                <strong>{item.paid_total ?? 'Mixed currencies'}</strong> {item.payment_currencies?.join(', ')}
              </p>
              <p className="text-xs text-muted mb-3">Checker Approval: {item.approved_at || 'Pending / Unavailable'}</p>
              {item.flags.length ? (
                <ul className="mb-3">
                  {item.flags.map(flag => (
                    <li key={flag} className="text-xs text-status-warning font-medium">
                      {LABELS[flag] || flag}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-status-success mb-3">✓ Settlement matches approved claim.</p>
              )}
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Transfer ID</th>
                      <th>Amount</th>
                      <th>Paid At (UTC)</th>
                      <th>Sender → Receiver</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.payments.map(p => (
                      <tr key={p.transaction_id}>
                        <td>{p.transaction_id}</td>
                        <td>
                          {p.currency} {p.amount}
                        </td>
                        <td>{p.timestamp}</td>
                        <td>
                          {p.sender_account} → {p.receiver_account}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          ))}
        </>
      )}
      <details className="glass-card mt-6">
        <summary className="text-xs text-muted cursor-pointer hover:text-secondary">Technical Scope & Limitations</summary>
        <p className="text-xs text-muted mt-2 leading-relaxed">
          Reconciliation flags are audit indicators for reviewer inspection. Settlement amount comparisons verify net recorded amounts against claim totals. Unlinked transfers require claim metadata mapping.
        </p>
      </details>
    </section>
  );
}
