import React from 'react';
import {FileText, Clock3, BadgeIndianRupee, MessageSquareMore, ArrowUpRight} from 'lucide-react';
import './ProcurementOverview.css';

const INR = new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'});
const count = value => new Intl.NumberFormat('en-IN').format(value);

export function workspaceRecords({purchases=[], sourcing=[]}={}) {
  const approved = purchases.map(row => ({...row,status:row.current_status || row.status, kind:'purchase', record_key:`purchase-${row.id}`}));
  const drafts = sourcing.filter(row => row.version > 1 || row.requirements?.product || row.requirements?.budget)
    .map(row => {
      const req = row.requirements || {};
      return {id:row.id, kind:'sourcing', record_key:`sourcing-${row.id}`, title:req.product || 'Untitled purchase request',
        status:row.current_status || row.status, progress:row.progress || {}, can_edit:row.can_edit ?? true, can_delete:row.can_delete ?? true,
        total:(req.line_items || []).reduce((sum,item) => sum + Number(item.quantity || 0)*Number(item.unit_price || 0),0),
        budget_limit:req.budget, terms:{currency:req.currency || 'INR', supplier_id:req.preferred_vendors || req.vendor_preference || ''},
        details:{department:req.department || req.line_items?.[0]?.department}, created_at:row.created_at,
        updated_at:row.workspace?.updated_at || row.created_at, intake_step:row.workspace?.step || 0,
        document_count:0, invoice_status:'not_received'};
    });
  return [...approved,...drafts].sort((a,b)=>String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at)));
}

export function overviewStats(records) {
  const pending=records.filter(r=>r.kind==='purchase' && r.status==='submitted');
  const approved=records.filter(r=>r.kind==='purchase' && r.status==='approved');
  const needsInfo=records.filter(r=>['needs_info','sent_back'].includes(r.status));
  const sourcing=records.filter(r=>r.kind==='sourcing');
  return {pending, approved, needsInfo, sourcing,
    commitments:approved.filter(r=>r.terms.currency==='INR').reduce((sum,r)=>sum+Number(r.total || 0),0),
    otherCurrencies:[...new Set(approved.filter(r=>r.terms.currency!=='INR').map(r=>r.terms.currency))]};
}

function Card({title, value, subtitle, Icon, children, footnote, tone}) {
  return <article className={`p-insight p-insight-${tone}`} aria-label={title}>
    <div className="p-insight-heading"><span className="p-insight-icon"><Icon size={17}/></span><h2>{title}</h2><ArrowUpRight size={15} aria-hidden="true"/></div>
    <strong className="p-insight-value">{value}</strong><p className="p-insight-subtitle">{subtitle}</p>
    <div className="p-insight-visual">{children}</div><p className="p-insight-footnote">{footnote}</p>
  </article>;
}

function Ring({value,total,label}) {
  const percentage=total ? Math.round(value/total*100) : 0;
  return <div className="p-insight-ring-wrap" role="img" aria-label={`${label}: ${value} of ${total} requests, ${percentage}%`}>
    <svg viewBox="0 0 120 120" className="p-insight-ring" aria-hidden="true"><circle cx="60" cy="60" r="46" className="track"/>
      <circle cx="60" cy="60" r="46" className="fill" pathLength="100" opacity={percentage ? 1 : 0} strokeDasharray={`${percentage} 100`} transform="rotate(-90 60 60)"/>
      <text x="60" y="58" textAnchor="middle">{percentage}%</text><text x="60" y="76" className="caption" textAnchor="middle">of requests</text></svg>
    <div className="p-insight-key"><span><i/>{count(value)} awaiting</span><span><i className="muted"/>{count(Math.max(total-value,0))} other</span></div>
  </div>;
}

export default function ProcurementOverview({records, now=new Date()}) {
  const {pending,approved,needsInfo,sourcing,commitments,otherCurrencies}=overviewStats(records);
  const stages=[['Sourcing',sourcing.length,'sourcing'],['In review',pending.length,'review'],['Approved',approved.length,'approved']];
  const other=Math.max(records.length-stages.reduce((sum,s)=>sum+s[1],0),0);
  // Six actual calendar weeks, including this week. No simulated trend or currency conversion.
  const monday=new Date(now); monday.setUTCHours(0,0,0,0); monday.setUTCDate(monday.getUTCDate()-((monday.getUTCDay()+6)%7));
  const weeks=Array.from({length:6},(_,i)=>{const start=new Date(monday);start.setUTCDate(start.getUTCDate()-(5-i)*7);return {start,value:0};});
  approved.filter(r=>r.terms.currency==='INR').forEach(row=>{
    const date=new Date(`${row.approved_at || row.created_at}${/Z$|[+-]\d\d:\d\d$/.test(row.approved_at || row.created_at)?'':'Z'}`);
    const week=weeks.find(w=>date>=w.start && date.getTime()<w.start.getTime()+7*86400000);
    if(week) week.value+=Number(row.total || 0);
  });
  const max=Math.max(...weeks.map(w=>w.value),1);
  const chartNote=approved.some(r=>r.terms.currency==='INR' && !r.approved_at)?'Approved requests by creation week':'Approved POs by approval week';
  return <section className="p-overview-insights" aria-label="Procurement analytics">
    <Card title="Purchase requests" value={count(records.length)} subtitle="Your saved purchase pipeline" Icon={FileText} tone="orange" footnote="Saved sourcing briefs and purchase requests">
      <div className="p-insight-segments" role="img" aria-label={stages.map(s=>`${s[0]}: ${s[1]}`).concat(`Other: ${other}`).join(', ')}>
        {records.length ? [...stages,['Other',other,'other']].filter(s=>s[1]).map(s=><span key={s[0]} className={s[2]} style={{flex:s[1]}}/>) : <span className="other"/>}
      </div><div className="p-insight-stage-key">{stages.map(s=><span key={s[0]}><b>{count(s[1])}</b>{s[0]}</span>)}</div>
    </Card>
    <Card title="Awaiting approval" value={count(pending.length)} subtitle="Submitted requests needing a decision" Icon={Clock3} tone="gold" footnote="Independent human approval required">
      <Ring value={pending.length} total={records.length} label="Awaiting approval"/>
    </Card>
    <Card title="Approved commitments" value={INR.format(commitments)} subtitle="Approved PO value · INR" Icon={BadgeIndianRupee} tone="green" footnote={otherCurrencies.length?`${otherCurrencies.join(', ')} approvals excluded; no FX conversion`:'Commitments only · payment is recorded separately'}>
      <div className="p-insight-bars" role="img" aria-label={`${chartNote}. ${weeks.map(w=>`${w.start.toISOString().slice(0,10)}: ${INR.format(w.value)}`).join('; ')}`}>
        {weeks.map(w=><div key={w.start.toISOString()}><span className="p-insight-bar-track"><i style={{height:`${w.value/max*100}%`}}/></span><small>{w.start.toLocaleDateString('en-IN',{day:'numeric',month:'short',timeZone:'UTC'})}</small></div>)}
      </div><span className="p-insight-chart-label">{chartNote} · 6 weeks</span>
    </Card>
    <Card title="Needs information" value={count(needsInfo.length)} subtitle="Waiting for the requester’s response" Icon={MessageSquareMore} tone="blue" footnote={records.length?`${Math.round(needsInfo.length/records.length*100)}% of saved requests need clarification`:'No requests need clarification'}>
      <div className="p-insight-dots" role="img" aria-label={`${needsInfo.length} requests need information; ${records.length} total requests`}>
        {Array.from({length:40},(_,i)=><i key={i} className={i < (records.length?Math.ceil(needsInfo.length/records.length*40):0)?'active':''}/>)}
      </div><div className="p-insight-response"><span>Action needed</span><strong>{count(needsInfo.length)} request{needsInfo.length===1?'':'s'}</strong></div>
    </Card>
  </section>;
}
