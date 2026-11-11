import React from 'react';
import RecordLink from './RecordLink';
import PolicyEvidence from './PolicyEvidence';
import {snapshotGroups} from './evidenceRecords';

const label=value=>value.replaceAll('_',' ');
export function ReadableValue({value}) {
  if(value==null)return <span>Not saved</span>;
  if(Array.isArray(value))return value.length?<><ol>{value.slice(0,10).map((v,i)=><li key={i}><ReadableValue value={v}/></li>)}</ol>{value.length>10&&<details><summary>Show all {value.length} entries</summary><ol start={11}>{value.slice(10).map((v,i)=><li key={i}><ReadableValue value={v}/></li>)}</ol></details>}</>:<span>None</span>;
  if(typeof value==='object')return <dl>{Object.entries(value).map(([k,v])=><React.Fragment key={k}><dt>{label(k)}</dt><dd><ReadableValue value={v}/></dd></React.Fragment>)}</dl>;
  return <span>{String(value)}</span>;
}
function triggeredFields(item) {
  const e=item.evidence||{};
  const fields=new Set([...(Array.isArray(e.trigger_fields)?e.trigger_fields:[]),...(Array.isArray(e.matched_fields)?e.matched_fields:[]),e.trigger_field,e.matched_field,e.shared_attribute,e.field].filter(v=>typeof v==='string'));
  if(item.case_type==='circular_payment')['sender_account','receiver_account','amount','timestamp'].forEach(f=>fields.add(f));
  for(const flag of e.flags||[]) {
    if(flag.includes('amount')||flag.includes('total'))['claimed_amount','amount'].forEach(f=>fields.add(f));
    if(flag.includes('currency'))fields.add('currency');
    if(flag.includes('approval'))['timestamp','approved_at','status'].forEach(f=>fields.add(f));
    if(flag.includes('rejected'))fields.add('status');
    if(flag.includes('multiple'))fields.add('claim_id');
  }
  for(const check of e.policy?.checks||[])if(check.status==='review'){
    for(const field of check.fields||[])fields.add(field);
    if(check.code?.includes('receipt'))fields.add('claimed_amount');
  }
  const groups=snapshotGroups(item);
  if(item.case_type==='vendor_check'||item.case_type==='payroll_check') {
    for(const field of ['bank_account','pan','gstin','phone','address']) {
      const values=groups.flatMap(g=>g.rows).map(r=>r[field]).filter(Boolean);
      if(values.length>new Set(values).size)fields.add(field);
    }
  }
  return fields;
}
function SnapshotRows({group,fields}) {
  const rows=group.rows;
  const render=list=><div className="table-container"><table><thead><tr><th>Live record</th><th>Saved evidence fields</th></tr></thead><tbody>{list.map((r,i)=><tr key={`${r[group.idKey]}-${i}`}><td><RecordLink kind={group.kind} id={r[group.idKey]}/></td><td><dl>{Object.entries(r).map(([k,v])=><React.Fragment key={k}><dt className={fields.has(k)?'evidence-trigger':''}>{label(k)}{fields.has(k)&&' · Rule trigger'}</dt><dd className={fields.has(k)?'evidence-trigger':''}><ReadableValue value={v}/></dd></React.Fragment>)}</dl></td></tr>)}</tbody></table></div>;
  return <section className="evidence-records"><h4>{group.title} ({rows.length})</h4>{render(rows.slice(0,10))}{rows.length>10&&<details><summary>Show all {rows.length} records ({rows.length-10} more)</summary>{render(rows.slice(10))}</details>}</section>;
}
function Records({item}){return snapshotGroups(item).map(g=><SnapshotRows key={g.title} group={g} fields={triggeredFields(item)}/>);}
function ModelScoreEvidence({ prediction }) {
  if (!prediction) return <div className="evidence-records"><p className="text-secondary text-xs italic">No model score saved.</p></div>;

  const score = prediction.combined_fraud_score ?? prediction.score;
  const scorePercent = score != null ? Math.round(Number(score) * 100) : null;
  const isHigh = scorePercent != null && scorePercent >= 65;
  const isModerate = scorePercent != null && scorePercent >= 35 && scorePercent < 65;
  const featureValues = prediction.feature_values || {};

  // Extract human-meaningful flags (not log math or raw z-scores)
  const humanFlags = [];
  if (Number(featureValues.weekend_flag || featureValues.is_weekend || 0) >= 1) {
    humanFlags.push({ label: 'Weekend submission', desc: 'Expense claimed on a weekend' });
  }
  if (Number(featureValues.is_holiday || 0) >= 1) {
    humanFlags.push({ label: 'Holiday receipt', desc: 'Transaction date is a company holiday' });
  }
  if (Number(featureValues.is_after_hours || 0) >= 1) {
    humanFlags.push({ label: 'After-hours transaction', desc: 'Submitted outside normal business hours' });
  }
  if (Number(featureValues.vendor_is_new || 0) >= 1) {
    humanFlags.push({ label: 'First-time vendor', desc: 'Vendor has no prior billing history' });
  }
  if (Number(featureValues.duplicate_prior || 0) >= 1) {
    humanFlags.push({ label: 'Potential duplicate', desc: 'Similar amount or vendor found in prior claims' });
  }
  if (Number(featureValues.z_global || 0) >= 2.0 || Number(featureValues.z_vendor || 0) >= 2.0) {
    humanFlags.push({ label: 'Statistical amount outlier', desc: 'Amount is significantly higher than historical averages' });
  }

  return (
    <div className="evidence-records p-4 rounded-lg bg-bg-surface/70 border border-border-light mb-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <strong className="text-sm">Risk Score at Capture:</strong>
          {scorePercent != null ? (
            <span className={`badge ${isHigh ? 'badge-red' : isModerate ? 'badge-amber' : 'badge-green'} text-xs font-bold`}>
              {scorePercent}/100 · {isHigh ? 'High Risk' : isModerate ? 'Review Suggested' : 'Normal / Low Risk'}
            </span>
          ) : (
            <span className="text-muted text-xs">Unscored</span>
          )}
        </div>
        {prediction.reconstruction_error != null && (
          <span className="text-xs text-muted">
            Normality fit error: {Number(prediction.reconstruction_error).toFixed(3)}
          </span>
        )}
      </div>

      {humanFlags.length > 0 ? (
        <div className="my-2">
          <span className="text-xs text-muted block mb-1 font-semibold uppercase">Triggered AI Signals:</span>
          <div className="flex flex-wrap gap-2">
            {humanFlags.map((flag, i) => (
              <span key={i} className="badge badge-amber text-xs" title={flag.desc}>
                {flag.label}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-xs text-secondary my-1">No critical behavioral anomalies flagged in feature signals.</p>
      )}

      {/* Tucked away behind an engineering dropdown */}
      {Object.keys(featureValues).length > 0 && (
        <details className="mt-3 pt-2 border-t border-glass">
          <summary className="text-[11px] text-muted cursor-pointer hover:text-secondary">
            View technical ML feature vectors ({Object.keys(featureValues).length} variables)
          </summary>
          <div className="grid-cols-2 gap-2 mt-2 text-[11px] font-mono bg-bg-card p-3 rounded max-h-48 overflow-y-auto">
            {Object.entries(featureValues).map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-glass pb-0.5">
                <span className="text-muted">{k}:</span>
                <span className="text-primary">{typeof v === 'number' ? Number(v).toFixed(4) : String(v)}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function ReceiptEvidence({ receipt }) {
  if (!receipt || (typeof receipt === 'string' && receipt === 'No receipt saved.')) {
    return <div className="evidence-records"><p className="text-secondary text-xs italic">No physical receipt image attached to this case.</p></div>;
  }
  if (typeof receipt === 'object') {
    return (
      <div className="evidence-records p-3 rounded-lg bg-bg-surface/70 border border-border-light mb-4 text-xs">
        <div className="grid-cols-2 gap-3 text-secondary">
          <div>Extracted Bill Amount: <strong className="text-primary">{receipt.extracted_amount ? `₹${Number(receipt.extracted_amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : 'Not detected'}</strong></div>
          <div>Extracted Vendor: <strong className="text-primary">{receipt.extracted_vendor || 'Not detected'}</strong></div>
        </div>
        {receipt.raw_ocr_text && (
          <details className="mt-2 text-muted">
            <summary className="cursor-pointer hover:text-primary text-[11px]">View raw extracted text</summary>
            <pre className="mono-pre mt-1 p-2 text-[11px] max-h-24 overflow-y-auto">{receipt.raw_ocr_text}</pre>
          </details>
        )}
      </div>
    );
  }
  return <div className="evidence-records"><ReadableValue value={receipt}/></div>;
}

function ExpenseEvidence({item}) {
  const e=item.evidence||{};
  return <><h3>Expense claim evidence</h3><Records item={item}/>{!Object.hasOwn(e,'payments')&&<p>Linked payments were not captured in this older snapshot. Any current links appear separately under Related records.</p>}
    <h4>Receipt at capture</h4><ReceiptEvidence receipt={e.receipt}/>
    <h4>Model score and risk factors at capture</h4><ModelScoreEvidence prediction={e.prediction}/>
    {e.policy&&<PolicyEvidence result={e.policy}/>}<p>{e.snapshot_note}</p></>;
}
function CircularEvidence({item}) {const e=item.evidence||{};return <><h3>Circular payment evidence</h3><p className="transfer-path">{(e.accounts||[]).join(' → ')||'Account path not saved'}</p><p>{e.currency} {e.initial_amount} sent; {e.returned_amount} returned ({e.return_ratio==null?'Unknown':(e.return_ratio*100).toFixed(1)}%).</p><p>{e.reason}</p><Records item={item}/></>;}
function ReconciliationEvidence({item}) {const e=item.evidence||{};return <><h3>Payment reconciliation evidence</h3><p>Claim {e.claim_currency} {e.claim_amount}; paid {e.paid_total??'Total not saved'}.</p><ul>{(e.flags||[]).map(f=><li key={f}>{label(f)}</li>)}</ul><Records item={item}/></>;}
function GenericEvidence({item}) {const extra=Object.fromEntries(Object.entries(item.evidence||{}).filter(([k])=>!['vendors','transactions','payments','payment','employees','employee','roster_records','roster_record'].includes(k)));return <><h3>Saved evidence</h3><Records item={item}/><div className="evidence-records"><ReadableValue value={Object.keys(extra).length?extra:{note:'No additional evidence fields were saved.'}}/></div></>;}
export default function CaseEvidence({item}) {
  const Viewer={expense_claim:ExpenseEvidence,circular_payment:CircularEvidence,reconciliation:ReconciliationEvidence}[item.case_type]||GenericEvidence;
  return <section aria-label="Evidence snapshot"><p>Evidence snapshot saved at case creation. Highlighted fields triggered the rule; live links may show later changes.</p><Viewer item={item}/></section>;
}
