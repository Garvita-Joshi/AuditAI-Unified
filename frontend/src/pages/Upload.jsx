import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { claimsApi, fraudApi, receiptsApi, procurementApi } from '../api/client';
import FileUpload from '../components/FileUpload';
import MasterDataImport from '../components/MasterDataImport';
import AutomaticCheckResult from '../components/AutomaticCheckResult';
import { Play, FileText, Search, CheckCircle, Clock, AlertTriangle, Loader, Link2, FilePlus, Database } from 'lucide-react';
import { isReviewer, useAuth } from '../auth/AuthContext';
import { useAuditProfile } from '../context/AuditProfileContext';
import './Upload.css';

// ── Procurement Invoice Upload Pipeline ──────────────────────────────────────
function PipelineStep({ label, status, timestamp }) {
  const icon = status === 'done'
    ? <CheckCircle size={13} style={{ color: 'var(--color-status-success, #10b981)' }} />
    : status === 'partial'
    ? <AlertTriangle size={13} style={{ color: '#f59e0b' }} />
    : <Clock size={13} style={{ color: 'var(--color-muted, #6b7280)' }} />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 90 }}>
      {icon}
      <span style={{ fontSize: 11, fontWeight: 500, color: status === 'done' ? 'var(--color-status-success, #10b981)' : status === 'partial' ? '#f59e0b' : 'var(--color-muted, #6b7280)' }}>{label}</span>
      {timestamp && <span style={{ fontSize: 9, color: 'var(--color-muted, #6b7280)' }}>{timestamp.slice(0, 19).replace('T', ' ')} UTC</span>}
    </div>
  );
}

function AuditTimeline({ events }) {
  if (!events || !events.length) return null;
  const dotColor = a => a?.includes('ml') ? '#f59e0b' : a?.includes('ocr') ? '#6366f1' : '#10b981';
  return (
    <div className="glass-card" style={{ padding: '14px 18px', marginTop: 14 }}>
      <h4 style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 13, marginBottom: 10 }}>
        <FileText size={13} /> Audit Trail
        <span className="badge text-xs" style={{ background: 'rgba(99,102,241,0.15)', color: '#a5b4fc', border: '1px solid rgba(99,102,241,0.3)', marginLeft: 4 }}>Immutable</span>
      </h4>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {events.map((e, i) => (
          <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor(e.action), marginTop: 4, flexShrink: 0 }} />
            <div>
              <div style={{ fontSize: 12, fontWeight: 500, textTransform: 'capitalize' }}>{(e.action || '').replaceAll('_', ' ')}</div>
              <div style={{ fontSize: 10, color: 'var(--color-muted, #6b7280)' }}>{e.log_time || e.timestamp}</div>
              {e.detail && <div style={{ fontSize: 11, color: 'var(--color-secondary, #9ca3af)', marginTop: 2 }}>{e.detail}</div>}
              {e.error && <div style={{ fontSize: 10, color: '#f87171', marginTop: 2 }}>{e.error}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function InvoiceUploadSection() {
  const [mode, setMode] = useState('attach');
  const [requests, setRequests] = useState([]);
  const [requestsLoaded, setRequestsLoaded] = useState(false);
  const [requestSearch, setRequestSearch] = useState('');
  const [selectedRequest, setSelectedRequest] = useState(null);
  const [invState, setInvState] = useState('idle');
  const [invResult, setInvResult] = useState(null);
  const [invError, setInvError] = useState('');

  const loadRequests = async () => {
    if (requestsLoaded) return;
    try { const { data } = await procurementApi.requestsIndex(); setRequests(data); setRequestsLoaded(true); } catch { setRequests([]); }
  };
  const filtered = requests.filter(r => `${r.label} ${r.supplier}`.toLowerCase().includes(requestSearch.toLowerCase()));

  const handleInvoiceUpload = async (file) => {
    if (mode === 'attach' && !selectedRequest) { setInvError('Select a procurement request to attach this invoice to.'); setInvState('error'); return; }
    setInvState('uploading'); setInvError(''); setInvResult(null);
    try {
      const { data } = await procurementApi.uploadInvoice(file, mode === 'attach' ? selectedRequest?.id : null, mode);
      setInvResult(data); setInvState('done');
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || 'Invoice upload failed.';
      setInvError(typeof msg === 'string' ? msg : JSON.stringify(msg)); setInvState('error');
    }
  };

  const ocr = invResult?.ocr_result || {};
  const ml = invResult?.ml_assessment;
  const steps = invResult?.pipeline_steps || [];
  const trail = invResult?.audit_trail || [];

  return (
    <div className="upload-section-card mb-6" style={{ marginTop: 28 }}>
      <h3 id="invoice-import" className="upload-section-title">
        3. Invoice Upload
        <span className="badge text-xs" style={{ background: 'rgba(239,153,118,0.18)', color: '#ef9976', border: '1px solid rgba(239,153,118,0.35)', marginLeft: 10, verticalAlign: 'middle' }}>Procurement</span>
      </h3>
      <p className="upload-section-sub">Upload a supplier invoice — OCR reads the fields, ML checks for fraud, and it's linked to a request with a full timestamped audit trail.</p>

      {/* Mode selector */}
      <div className="upload-mode-buttons">
        {[['attach', Link2, 'Attach to existing request'], ['new', FilePlus, 'New standalone invoice']].map(([m, Icon, label]) => (
          <button key={m} className={`upload-mode-btn ${mode === m ? 'active' : ''}`}
            onClick={() => { setMode(m); setInvResult(null); setInvState('idle'); setInvError(''); if (m === 'attach') loadRequests(); else setSelectedRequest(null); }}>
            <Icon size={14} />{label}
          </button>
        ))}
      </div>

      {/* Attach mode: request search */}
      {mode === 'attach' && (
        <div className="upload-target-search">
          <label className="text-xs text-secondary mb-2 block font-semibold">Target Procurement Request</label>
          <div style={{ position: 'relative', marginBottom: 8 }}>
            <Search size={15} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', opacity: 0.5, pointerEvents: 'none' }} />
            <input type="text" className="input"
              placeholder="Search PR number, title, or supplier…"
              value={requestSearch}
              onFocus={loadRequests}
              onChange={e => { setRequestSearch(e.target.value); loadRequests(); }} />
          </div>
          {requestSearch && filtered.length > 0 && (
            <div className="glass-card" style={{ padding: '6px 0', maxHeight: 200, overflowY: 'auto', marginBottom: 12, background: '#241e1a' }}>
              {filtered.map(r => (
                <button key={r.id} style={{ width: '100%', padding: '10px 16px', textAlign: 'left', display: 'block', background: selectedRequest?.id === r.id ? 'rgba(239,153,118,0.15)' : 'transparent', borderBottom: '1px solid rgba(255,255,255,0.06)' }}
                  className="text-xs text-primary" onClick={() => { setSelectedRequest(r); setRequestSearch(''); }}>
                  <span className="font-semibold text-accent-primary">{r.label}</span>
                  <span className="text-muted" style={{ marginLeft: 10 }}>{r.status} · {r.supplier}</span>
                </button>
              ))}
            </div>
          )}
          {selectedRequest && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'rgba(239,153,118,0.1)', borderRadius: 8, border: '1px solid rgba(239,153,118,0.3)', marginBottom: 14 }}>
              <CheckCircle size={16} style={{ color: '#34d399' }} />
              <span className="text-xs font-semibold text-primary">{selectedRequest.label}</span>
              <span className="text-muted text-xs">· {selectedRequest.status}</span>
              <button className="text-muted text-xs hover:text-primary" style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => setSelectedRequest(null)}>✕ Clear</button>
            </div>
          )}
        </div>
      )}

      {/* New mode info */}
      {mode === 'new' && (
        <div className="mb-6" style={{ padding: '14px 18px', background: 'rgba(239,153,118,0.08)', borderRadius: 10, border: '1px solid rgba(239,153,118,0.25)' }}>
          <p className="text-xs text-secondary"><span className="font-semibold text-primary">Auto-create mode:</span> A new Draft procurement request will be created from the extracted invoice fields. Review and complete it in the Procurement section.</p>
        </div>
      )}

      {/* File upload */}
      <FileUpload label="Upload invoice PDF / image"
        accept="image/*,application/pdf,.txt"
        onUpload={handleInvoiceUpload}
        uploadState={invState === 'uploading' ? 'uploading' : invState === 'done' ? 'complete' : invState === 'error' ? 'error' : 'idle'} />

      {invError && (
        <div className="glass-card mt-4 flex items-center p-4 border-l-4 border-status-danger">
          <AlertTriangle size={14} style={{ color: '#f87171', marginRight: 8, flexShrink: 0 }} />
          <span className="text-sm">{invError}</span>
        </div>
      )}

      {/* Results */}
      {invResult && (<>
        {/* Request linkage banner */}
        <div className="glass-card mt-4" style={{ padding: '12px 16px', background: 'rgba(16,185,129,0.07)', border: '1px solid rgba(16,185,129,0.25)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <CheckCircle size={15} style={{ color: '#10b981' }} />
            <span className="text-sm font-medium">
              {mode === 'new' ? 'New request created: ' : 'Invoice attached to: '}
              <strong>PR-{String(invResult.request_id).padStart(4, '0')} · {invResult.request_title}</strong>
            </span>
            <span className="badge text-xs" style={{ background: 'rgba(16,185,129,0.15)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.3)' }}>{invResult.request_status}</span>
          </div>
        </div>

        {/* Pipeline steps */}
        {steps.length > 0 && (
          <div className="glass-card mt-4" style={{ padding: '14px 18px' }}>
            <h4 style={{ fontWeight: 600, fontSize: 13, marginBottom: 14 }}>Pipeline Status</h4>
            <div style={{ display: 'flex', alignItems: 'flex-start' }}>
              {steps.map((s, i) => (
                <React.Fragment key={s.step}>
                  <PipelineStep label={s.step} status={s.status} timestamp={s.timestamp} />
                  {i < steps.length - 1 && <div style={{ flex: 1, height: 1, background: s.status === 'done' ? 'rgba(16,185,129,0.4)' : 'rgba(255,255,255,0.08)', margin: '10px 8px 0' }} />}
                </React.Fragment>
              ))}
            </div>
          </div>
        )}

        {/* OCR Result card */}
        {(ocr.supplier_id || ocr.total || ocr.invoice_number) && (
          <div className="glass-card mt-4" style={{ padding: '14px 18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <h4 style={{ fontWeight: 600, fontSize: 13, color: 'var(--color-accent-primary, #6366f1)' }}>OCR Extraction Result</h4>
              <span className={`badge text-xs ${ocr.ocr_confidence === 'high' ? 'badge-green' : ''}`}
                style={ocr.ocr_confidence === 'partial' ? { background: 'rgba(245,158,11,0.15)', color: '#fbbf24', border: '1px solid rgba(245,158,11,0.3)' } : {}}>
                {ocr.ocr_confidence === 'high' ? '✓ High confidence' : ocr.ocr_confidence === 'partial' ? 'Partial' : 'Failed'}
              </span>
            </div>
            <div className="grid-cols-2 gap-3 text-xs">
              {ocr.supplier_id && <div><span className="text-secondary">Vendor</span><div className="font-medium">{ocr.supplier_id}</div></div>}
              {ocr.invoice_number && <div><span className="text-secondary">Invoice #</span><div className="font-medium">{ocr.invoice_number}</div></div>}
              {ocr.total && <div><span className="text-secondary">Total</span><div className="font-medium">{ocr.currency || ''} {ocr.total}</div></div>}
              {ocr.invoice_date && <div><span className="text-secondary">Date</span><div className="font-medium">{ocr.invoice_date}</div></div>}
              {ocr.tax && <div><span className="text-secondary">Tax</span><div className="font-medium">{ocr.tax}</div></div>}
              {ocr.delivery && <div><span className="text-secondary">Delivery</span><div className="font-medium">{ocr.delivery}</div></div>}
            </div>
            {ocr.items?.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div className="text-xs text-secondary mb-1 font-medium">Line items extracted</div>
                {ocr.items.map((item, i) => (
                  <div key={i} className="text-xs" style={{ display: 'flex', gap: 10, padding: '4px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: 4, marginBottom: 2 }}>
                    <span className="text-secondary">#{i + 1}</span><span>{item.description || item.sku}</span>
                    <span className="text-secondary">×{item.quantity}</span>
                    <span className="font-medium" style={{ marginLeft: 'auto' }}>{ocr.currency || ''} {item.unit_price}</span>
                  </div>
                ))}
              </div>
            )}
            {ocr.ocr_error && <p className="text-xs mt-2" style={{ color: '#f87171' }}>OCR note: {ocr.ocr_error}</p>}
            {ocr.raw_excerpt && <details className="mt-3"><summary className="text-xs text-muted cursor-pointer">View raw OCR excerpt</summary><pre className="mono-pre mt-2 text-xs p-2 rounded" style={{ whiteSpace: 'pre-wrap', maxHeight: 100 }}>{ocr.raw_excerpt}</pre></details>}
          </div>
        )}

        {/* ML Fraud card */}
        {ml && (
          <div className="glass-card mt-4" style={{ padding: '14px 18px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <h4 style={{ fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 5 }}>ML Fraud Assessment</h4>
              {ml.fraud_decision && (
                <span className="badge text-xs" style={ml.is_fraud ? { background: 'rgba(239,68,68,0.15)', color: '#f87171', border: '1px solid rgba(239,68,68,0.3)' } : { background: 'rgba(16,185,129,0.15)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.3)' }}>
                  {ml.is_fraud ? 'FRAUD RISK FLAGGED' : '✓ CONSIDERED NOT FRAUD'}
                </span>
              )}
              {!ml.fraud_decision && ml.status && <span className="badge text-xs text-muted">{ml.status}</span>}
            </div>
            {ml.score != null && (
              <div className="text-xs" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div>Anomaly Score: <strong>{(ml.score * 100).toFixed(1)}%</strong>{ml.threshold ? ` (threshold ${(ml.threshold * 100).toFixed(1)}%)` : ''}</div>
                {ml.recommendation && <div style={{ marginTop: 6, padding: '6px 10px', borderRadius: 5, background: ml.is_fraud ? 'rgba(239,68,68,0.08)' : 'rgba(16,185,129,0.08)', borderLeft: `3px solid ${ml.is_fraud ? '#ef4444' : '#10b981'}` }}><strong>Recommendation:</strong> {ml.recommendation}</div>}
              </div>
            )}
            {ml.reason && <p className="text-xs text-muted mt-2">{ml.reason}</p>}
          </div>
        )}

        {/* Immutable audit trail */}
        <AuditTimeline events={trail} />

        <p className="text-xs text-muted mt-3">{invResult.note} · <a href="/procurement/requests" style={{ color: 'var(--color-accent-primary, #6366f1)' }}>Open in Procurement →</a></p>
      </>)}
    </div>
  );
}
// ── End Invoice Upload Pipeline ───────────────────────────────────────────────


export default function Upload() {
  const [csvUploadState, setCsvUploadState] = useState('idle');
  const [rcpUploadState, setRcpUploadState] = useState('idle');
  const [rcpClaimId, setRcpClaimId] = useState('');
  const [receiptData, setReceiptData] = useState(null);
  const [message, setMessage] = useState(null);
  const [scoring, setScoring] = useState(false);
  const [automaticChecks,setAutomaticChecks]=useState(null);

  const navigate = useNavigate();
  const { user } = useAuth();
  const { profile, companyName, currency } = useAuditProfile();

  const handleCsvUpload = async (file) => {
    setCsvUploadState('uploading');
    setMessage(null);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await claimsApi.upload(formData);
      setCsvUploadState('complete');setAutomaticChecks(res.data.checks);
      setMessage({ type: 'success', text: res.data.message });
    } catch (err) {
      console.error(err);
      setCsvUploadState('error');
      setMessage({
        type: 'error',
        text: err.response?.data?.detail || (err.response?.status >= 500 ? "The server could not finish importing the claims. Your file may be valid; please retry or contact support." : !err.response ? "Unable to reach the server. Check the connection and try again." : "Upload failed. Check the required columns and row values.")
      });
    }
  };

  const handleReceiptUpload = async (file) => {
    if (!rcpClaimId.trim()) {
      setRcpUploadState('error');
      setMessage({ type: 'error', text: 'Enter the existing Target Claim ID before uploading a receipt so the OCR evidence can be linked and scored.' });
      return;
    }
    setRcpUploadState('processing');
    setMessage(null);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await claimsApi.uploadReceipt(rcpClaimId, formData);
      if (res.data.upload_status !== 'processed') {
        throw new Error('Receipt saved, but OCR could not read it. Try a clearer single-page image or PDF.');
      }
      setAutomaticChecks(res.data.checks);
      const receiptResponse = await receiptsApi.get(res.data.receipt_id);
      setReceiptData(receiptResponse.data);
      setRcpUploadState('complete');
      setMessage({ type: 'success', text: `Receipt processed: ${res.data.receipt_id}. OCR fields are shown below. Relevant checks ran automatically. See the check status below.` });
    } catch (err) {
      console.error(err);
      setRcpUploadState('error');
      setMessage({ type: 'error', text: err.response?.data?.detail || err.message || "Receipt upload failed." });
    }
  };

  const runScoring = async () => {
    setScoring(true);
    setMessage({ type: 'info', text: 'Running Autoencoder + Isolation Forest scoring pipeline...' });
    try {
      const res = await fraudApi.score();
      if (!res.data.scored_count) {
        setMessage({
          type: 'error',
          text: 'No pending claims were found to score. Upload a claims file or attach the receipt to a valid Target Claim ID first.'
        });
        return;
      }
      setMessage({
        type: 'success',
        text: `Scoring complete! Scored ${res.data.scored_count} claims. Found ${res.data.flagged_count} anomalies.`
      });
      setTimeout(() => navigate('/claims'), 3000);
    } catch (err) {
      console.error(err);
      setMessage({ type: 'error', text: err.response?.data?.detail || "Scoring pipeline failed. Try retraining the model first." });
    } finally {
      setScoring(false);
    }
  };

  return (
    <div className="main-content">
      {/* Header Context */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm text-muted">
          <span>Global Auditing</span>
          <span>/</span>
          <span className="text-secondary font-medium">{companyName} · {currency}</span>
        </div>
        <span
          className="badge text-xs"
          style={{ background: `${profile.color}20`, color: profile.color, border: `1px solid ${profile.color}40` }}
        >
          {profile.name}
        </span>
      </div>

      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Data Ingestion</h1>
          <p className="text-xs text-secondary mt-1">
            Upload expense batches, attach receipt evidence for OCR, and synchronize reference datasets.
          </p>
        </div>
      </div>

      {message && (
        <div className={`glass-card mb-6 flex items-center p-4 border-l-4 ${message.type === 'error' ? 'border-status-danger' :
            message.type === 'success' ? 'border-status-success' : 'border-accent-primary'
          }`}>
          <span className="text-sm">{message.text}</span>
        </div>
      )}

      {/* Main Upload Cards */}
      <div className="grid-cols-2 mb-6">
        <div className="glass-card">
          <h3 id="expense-import" className="text-lg font-semibold mb-1">1. Upload Expense Claims</h3>
          <p className="text-secondary text-xs mb-5">Upload employee expense claim CSV records for ML anomaly scoring.</p>

          <FileUpload
            label="Upload claims.csv"
            accept=".csv,.json"
            onUpload={handleCsvUpload}
            uploadState={csvUploadState}
          />
        </div>

        <div className="glass-card">
          <h3 id="receipt-import" className="text-lg font-semibold mb-1">2. Upload Receipt (Optional)</h3>
          <p className="text-secondary text-xs mb-5">Attach an invoice or receipt image to an existing claim for OCR text & amount extraction.</p>

          <div className="mb-4">
            <label className="text-xs text-secondary mb-1 block font-medium">Target Claim ID</label>
            <input
              type="text"
              className="input text-sm"
              placeholder="e.g. CLM-00001"
              value={rcpClaimId}
              onChange={(e) => setRcpClaimId(e.target.value)}
            />
          </div>

          <FileUpload
            label="Upload receipt image/PDF"
            accept="image/*,application/pdf"
            onUpload={handleReceiptUpload}
            uploadState={rcpUploadState}
          />

          {receiptData?.ocr_result && (
            <div className="glass-card mt-5" style={{ padding: '16px' }}>
              <div className="flex justify-between items-center mb-3">
                <h4 className="font-semibold text-accent-primary text-sm">OCR Extraction Result</h4>
                <span className="badge badge-green text-xs">Processed</span>
              </div>
              <div className="grid-cols-2 gap-3 text-xs">
                <div><span className="text-secondary">Vendor:</span> <div className="font-medium text-primary">{receiptData.ocr_result.extracted_vendor || 'Not detected'}</div></div>
                <div><span className="text-secondary">Amount:</span> <div className="font-medium text-primary">{receiptData.ocr_result.extracted_amount != null ? `₹${Number(receiptData.ocr_result.extracted_amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : 'Not detected'}</div></div>
                <div><span className="text-secondary">Date:</span> <div className="font-medium text-primary">{receiptData.ocr_result.extracted_date || 'Not detected'}</div></div>
                <div><span className="text-secondary">Confidence:</span> <div className="font-medium text-primary">{receiptData.ocr_result.extraction_confidence != null ? `${Math.round(receiptData.ocr_result.extraction_confidence * 100)}%` : 'Not available'}</div></div>
              </div>
              {receiptData.ocr_result.raw_ocr_text && (
                <details className="mt-3">
                  <summary className="text-xs text-muted cursor-pointer hover:text-secondary">View raw OCR text</summary>
                  <pre className="mono-pre mt-2 text-xs p-2 rounded" style={{ whiteSpace: 'pre-wrap', maxHeight: '120px' }}>{receiptData.ocr_result.raw_ocr_text}</pre>
                </details>
              )}
            </div>
          )}
        </div>
      </div>

      <InvoiceUploadSection />

      {isReviewer(user) && <MasterDataImport/>}
      <AutomaticCheckResult checks={automaticChecks}/>

      {isReviewer(user) && (csvUploadState === 'complete' || rcpUploadState === 'complete') && (
        <div className="glass-card mb-6 flex items-center justify-between gap-5" style={{ padding: '18px 24px' }}>
          <div>
            <h3 className="font-semibold text-sm">Automated screening triggers after upload</h3>
            <p className="text-xs text-secondary mt-0.5">The pipeline combines claim metadata, vendor master checks, and any OCR extraction evidence.</p>
          </div>
          <button className="btn btn-primary text-xs" onClick={runScoring} disabled={scoring}>
            <Play size={15} />
            <span>{scoring ? 'Scoring…' : 'Run Pending Claim Scoring'}</span>
          </button>
        </div>
      )}

      <div className="pipeline-status-card">
        <h3 className="text-base font-semibold mb-4">Pipeline Status</h3>
        <div className="flex items-center justify-between text-xs">
          <div className={`flex flex-col items-center ${csvUploadState === 'complete' ? 'text-status-success' : 'text-muted'}`}>
            <div className="w-3.5 h-3.5 rounded-full bg-current mb-1.5"></div>
            <span>Data Ingestion</span>
          </div>
          <div className="h-px bg-border-light flex-1 mx-3"></div>
          <div className={`flex flex-col items-center ${rcpUploadState === 'complete' ? 'text-status-success' : 'text-muted'}`}>
            <div className="w-3.5 h-3.5 rounded-full bg-current mb-1.5"></div>
            <span>OCR Extraction</span>
          </div>
          <div className="h-px bg-border-light flex-1 mx-3"></div>
          <div className="flex flex-col items-center text-muted">
            <div className="w-3.5 h-3.5 rounded-full bg-current mb-1.5"></div>
            <span>Feature Engineering</span>
          </div>
          <div className="h-px bg-border-light flex-1 mx-3"></div>
          <div className="flex flex-col items-center text-muted">
            <div className="w-3.5 h-3.5 rounded-full bg-current mb-1.5"></div>
            <span>ML Scoring</span>
          </div>
        </div>
      </div>
    </div>
  );
}
