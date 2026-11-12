import React, { useEffect, useState } from 'react';
import { Database } from 'lucide-react';
import { masterDataApi, claimsApi, transfersApi } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import AutomaticCheckResult from './AutomaticCheckResult';

const DATASETS = {
  'vendor-master': 'Vendor master',
  'employee-roster': 'Employee roster',
  'payroll-payments': 'Payroll payments',
};
const ALL_TYPES = {
  ...DATASETS,
  'expense-claims': 'Expense claims',
  'receipts': 'Receipt',
  'bank-transfers': 'Bank transfers',
};

export default function MasterDataImport() {
  const { user } = useAuth();
  const [dataset, setDataset] = useState('vendor-master');
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState([]);
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [claimId, setClaimId] = useState('');

  const load = () => masterDataApi.status().then((r) => setStatus(r.data));
  useEffect(() => {
    load().catch(() => setError('Could not load master-data import status.'));
  }, []);

  const upload = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    setReport(null);
    try {
      let r;
      if (DATASETS[dataset]) r = await masterDataApi.upload(dataset, file);
      else {
        const body = new FormData();
        body.append('file', file);
        r =
          dataset === 'bank-transfers'
            ? await transfersApi.upload(body)
            : dataset === 'expense-claims'
            ? await claimsApi.upload(body)
            : await claimsApi.uploadReceipt(claimId.trim(), body);
      }
      setReport({ ...r.data, dataset: r.data.dataset || ALL_TYPES[dataset] });
    } catch (e) {
      const detail = e.response?.data;
      if (detail?.errors) setReport(detail);
      else setError(typeof detail?.detail === 'string' ? detail.detail : 'Import failed.');
    } finally {
      try {
        await load();
      } catch {
        setError('Could not refresh import status.');
      }
      setBusy(false);
    }
  };

  return (
    <section className="upload-section-card mb-6">
      <div className="flex items-center gap-2 mb-2">
        <Database size={20} className="text-accent-primary" />
        <h2 className="upload-section-title" style={{ margin: 0 }}>Master Reference Data & Ledger Ingestion</h2>
      </div>
      <p className="upload-section-sub">
        Upload reference datasets once. Internal checks and collusion screening run automatically.
      </p>

      {/* Dataset status summary pills */}
      <div className="master-pills-grid">
        {Object.entries(DATASETS).map(([key, label]) => {
          const s = status.find((r) => r.dataset === key);
          const isLoaded = (s?.rows_loaded ?? 0) > 0;
          return (
            <div key={key} className="master-pill-card">
              <div>
                <div className="pill-title">{label}</div>
                <div className="pill-sub">
                  {s?.rows_loaded ?? 0} rows; last attempt {s?.last_imported_at || 'Never'}; status {s?.last_import_status || 'Not imported'}
                </div>
              </div>
              <span className={`badge text-[11px] ${isLoaded ? 'badge-green' : 'badge-gray'}`} style={{ padding: '3px 10px', borderRadius: '6px' }}>
                {isLoaded ? 'Loaded' : 'Pending'}
              </span>
            </div>
          );
        })}
      </div>

      {user?.roles?.includes('admin') ? (
        <form className="master-form-controls" onSubmit={upload}>
          <label>
            Dataset type
            <select
              value={dataset}
              onChange={(e) => {
                setDataset(e.target.value);
                setFile(null);
                setReport(null);
              }}
            >
              {Object.entries(ALL_TYPES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          {dataset === 'receipts' && (
            <label>
              Target Claim ID
              <input required value={claimId} onChange={(e) => setClaimId(e.target.value)} placeholder="AST-DEMO-CLM-001" />
            </label>
          )}
          <label htmlFor="master-csv-file-input">
            {dataset === 'receipts' ? 'Receipt image or PDF' : 'CSV file'}
            <div className="custom-file-input">
              <span className="custom-file-btn">Choose file</span>
              <span className="custom-file-name">{file ? file.name : 'No file chosen'}</span>
              <input
                id="master-csv-file-input"
                aria-label={dataset === 'receipts' ? 'Receipt image or PDF' : 'CSV file'}
                key={dataset}
                type="file"
                accept={dataset === 'receipts' ? '.png,.jpg,.jpeg,.pdf,.tiff,.bmp' : '.csv,text/csv'}
                required
                onChange={(e) => setFile(e.target.files[0] || null)}
              />
            </div>
          </label>
          <button className="btn btn-primary" disabled={busy || !file || (dataset === 'receipts' && !claimId.trim())}>
            {busy ? 'Importing and checking...' : 'Import and check'}
          </button>
          {DATASETS[dataset] ? (
            <a href={`/samples/master-data/${dataset}.csv`} download className="text-xs text-accent-primary hover:underline" style={{ alignSelf: 'center', marginLeft: 'auto' }}>
              Download synthetic example CSV
            </a>
          ) : (
            <a href="/downloads/aster/aster_upload_pack.zip" download className="text-xs text-accent-primary hover:underline" style={{ alignSelf: 'center', marginLeft: 'auto' }}>
              Download Aster demo files
            </a>
          )}
        </form>
      ) : (
        <p className="text-xs text-muted">
          An administrator can use this combined import. Your existing claim and receipt upload controls are available below.
        </p>
      )}

      {error && <p role="alert" className="glass-card mb-4 text-xs text-status-danger">{error}</p>}
      {report && (
        <div role="status" className="mt-4 p-3 rounded-lg bg-bg-surface border border-border-light text-xs">
          <AutomaticCheckResult checks={report.checks} />
          <p className="mt-2 text-secondary">
            {report.dataset}: {report.status || report.upload_status || 'Imported'}.{' '}
            {report.inserted != null
              ? `Inserted ${report.inserted}; updated ${report.updated}; skipped ${report.skipped}; rejected ${report.rejected}.`
              : report.message ||
                (report.imported != null
                  ? `${report.imported} transfers imported; ${report.skipped} skipped.`
                  : report.upload_status === 'processed'
                  ? 'Receipt processed.'
                  : 'See upload status.')}
          </p>
          {report.errors?.length > 0 && (
            <details open className="mt-2">
              <summary className="cursor-pointer font-medium text-status-warning">
                Row rejection report ({report.errors.length})
              </summary>
              <ul className="mt-1 pl-4 list-disc text-muted">
                {report.errors.map((e, i) => (
                  <li key={i}>
                    Row {e.row ?? 'file'}: {e.reason || e.error}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
