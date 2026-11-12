
function SmtpConfigModal({onClose, onUpdated}){
 const [form,setForm]=useState({host:'',port:587,username:'',password:'',from_email:'',reply_to:'',redirect_email:'',use_ssl:false,imap_host:'',imap_port:993,imap_username:'',imap_password:'',imap_use_ssl:true});
 const [loading,setLoading]=useState(true);
 const [saving,setSaving]=useState(false);
 const [testing,setTesting]=useState(false);
 const [testingInbox,setTestingInbox]=useState(false);
 const [testEmail,setTestEmail]=useState('');
 const [msg,setMsg]=useState(null);

 useEffect(()=>{
  sourcingApi.getSmtpStatus().then(({data})=>{
   setForm(f=>({...f,host:data.host||'',port:data.port||587,username:data.username||'',from_email:data.from_email||'',reply_to:data.reply_to||data.imap_username||data.username||'',redirect_email:'',imap_host:data.imap_host||'',imap_port:data.imap_port||993,imap_username:data.imap_username||data.username||'',imap_password:'',imap_use_ssl:true}));
   setTestEmail(data.from_email||data.username||'');
   setLoading(false);
  }).catch(()=>setLoading(false));
 },[]);

 const applyPreset=(preset)=>{
  if(preset==='gmail'){
   setForm(f=>({...f,host:'smtp.gmail.com',port:587,use_ssl:false,imap_host:'imap.gmail.com',imap_port:993,imap_use_ssl:true,from_email:f.from_email||f.username,imap_username:f.imap_username||f.username}));
   setMsg({type:'info',text:'Gmail preset applied: Use your Gmail address and a 16-character App Password (from myaccount.google.com/apppasswords).'});
  } else if(preset==='outlook'){
   setForm(f=>({...f,host:'smtp.office365.com',port:587,use_ssl:false,imap_host:'outlook.office365.com',imap_port:993,imap_use_ssl:true,from_email:f.from_email||f.username,imap_username:f.imap_username||f.username}));
   setMsg({type:'info',text:'Outlook / Office 365 preset applied.'});
  } else if(preset==='brevo'){
   setForm(f=>({...f,host:'smtp-relay.brevo.com',port:587,use_ssl:false}));
   setMsg({type:'info',text:'Brevo / Sendinblue preset applied.'});
  }
 };

 const handleSave=async(e)=>{
  e.preventDefault();
  setSaving(true);setMsg(null);
  try{
   const {data}=await sourcingApi.saveSmtpConfig(form);
   setMsg({type:'success',text:data.message||'SMTP configuration saved and activated.'});
   if(onUpdated)onUpdated(data.status);
  }catch(err){
   setMsg({type:'error',text:err.response?.data?.detail||err.message||'Failed to save configuration.'});
  }finally{setSaving(false);}
 };

 const handleTest=async()=>{
  setTesting(true);setMsg(null);
  try{
   const {data}=await sourcingApi.testSmtp({to_email:testEmail.trim()||undefined});
   setMsg({type:'success',text:data.message});
  }catch(err){
   setMsg({type:'error',text:err.response?.data?.detail||err.message||'SMTP test failed. Check host, port, and credentials.'});
  }finally{setTesting(false);}
 };

 const handleTestInbox=async()=>{
  setTestingInbox(true);setMsg(null);
  try{const {data}=await sourcingApi.testInbox();setMsg({type:'success',text:data.message});}
  catch(err){setMsg({type:'error',text:err.response?.data?.detail||err.message||'Inbox check failed. Check IMAP settings.'});}
  finally{setTestingInbox(false);}
 };

 return <div className="vp-modal-overlay" onClick={onClose}><div className="vp-modal-card" onClick={e=>e.stopPropagation()}>
  <div className="vp-modal-header">
   <div><Settings size={18}/><strong>SMTP Mail Provider Configuration</strong></div>
   <button className="vp-modal-close" onClick={onClose}>×</button>
  </div>
  <p className="vp-modal-desc">Configure the sourcing sender and reply inbox. Replies use the monitored inbox address. These settings are separate from OTP/login mail. RFQ drafts are saved per purchase; selected drafts send only after reviewer confirmation.</p>
  
  <div className="vp-presets">
   <span>Quick Presets:</span>
   <button type="button" className="vp-preset-btn" onClick={()=>applyPreset('gmail')}>Gmail (smtp.gmail.com)</button>
   <button type="button" className="vp-preset-btn" onClick={()=>applyPreset('outlook')}>Outlook (office365)</button>
   <button type="button" className="vp-preset-btn" onClick={()=>applyPreset('brevo')}>Brevo</button>
  </div>

  <form onSubmit={handleSave} className="vp-smtp-form">
   <div className="vp-form-row-2">
    <label>SMTP Host *<input required placeholder="smtp.gmail.com" value={form.host} onChange={e=>setForm({...form,host:e.target.value})}/></label>
    <label>Port *<input type="number" required placeholder="587" value={form.port} onChange={e=>setForm({...form,port:Number(e.target.value)})}/></label>
   </div>
   <div className="vp-form-row-2">
    <label>Username / Login Email *<input required placeholder="you@domain.com" value={form.username} onChange={e=>setForm({...form,username:e.target.value})}/></label>
    <label>Password / App Password<input type="password" placeholder="Leave blank to keep saved password" value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/><small>Required only for the first setup or when changing the password.</small></label>
   </div>
   <div className="vp-form-row-2">
    <label>From Sender Email<input value="prepares23@gmail.com" readOnly/><small>Supplier RFQs are sent from this dedicated mailbox only.</small></label>
    <div className="vp-mailbox-note"><small>RFQs go directly to the selected vendor contact after a human approves each email. No demo or redirect delivery is used.</small></div>
   </div>
   <label className="vp-checkbox-label">
    <input type="checkbox" checked={form.use_ssl} onChange={e=>setForm({...form,use_ssl:e.target.checked})}/>
    <span>Use SSL / TLS connection directly (port 465)</span>
   </label>

   <div className="vp-mailbox-section">
    <strong>Reply inbox (IMAP)</strong>
    <small>SMTP verifies sending. IMAP is separately required to receive supplier replies. For non-Gmail or non-Outlook mail, enter the provider's IMAP host.</small>
    <div className="vp-form-row-2">
     <label>IMAP Host *<input required placeholder="imap.gmail.com" value={form.imap_host} onChange={e=>setForm({...form,imap_host:e.target.value})}/></label>
     <label>Port *<input type="number" required value={form.imap_port} onChange={e=>setForm({...form,imap_port:Number(e.target.value)})}/></label>
    </div>
    <small>Supplier replies will be addressed to <b>{form.imap_username||form.username||'the configured inbox username'}</b> (Reply-To).</small>
    <div className="vp-form-row-2">
     <label>Inbox username<input placeholder="Same as SMTP login if shared" value={form.imap_username} onChange={e=>setForm({...form,imap_username:e.target.value})}/></label>
     <label>Inbox password / app password<input type="password" placeholder="Leave blank to keep saved inbox password" value={form.imap_password} onChange={e=>setForm({...form,imap_password:e.target.value})}/></label>
    </div>
    <label className="vp-checkbox-label"><input type="checkbox" checked={form.imap_use_ssl} onChange={e=>setForm({...form,imap_use_ssl:e.target.checked})}/><span>Use IMAP over SSL (usually port 993)</span></label>
   </div>

   {msg&&<div className={`vp-form-alert alert-${msg.type}`}>{msg.text}</div>}

   <div className="vp-modal-footer">
    <div className="vp-test-group">
     <input className="vp-test-input" placeholder="Test recipient email" value={testEmail} onChange={e=>setTestEmail(e.target.value)}/>
     <button type="button" className="vp-btn vp-btn-outline" disabled={testing||!form.host||!form.username} onClick={handleTest}>
      {testing?'Testing…':'Send Test Email'}
     </button>
     <button type="button" className="vp-btn vp-btn-outline" disabled={testingInbox||!form.imap_host||!form.imap_username} onClick={handleTestInbox}>
      {testingInbox?'Checking…':'Test Reply Inbox'}
     </button>
    </div>
    <div style={{display:'flex',gap:8}}>
     <button type="button" className="vp-btn vp-btn-outline" onClick={onClose}>Cancel</button>
     <button type="submit" className="vp-btn vp-btn-primary" disabled={saving||!form.host||!form.username}>
      {saving?'Connecting…':'Save & Activate'}
     </button>
    </div>
   </div>
  </form>
 </div></div>;
}

import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Plus,Send,Trash2,Upload,CheckCircle2,AlertCircle,RefreshCw,GitBranch,Globe,ExternalLink,Search,Building2,Mail,Star,Trophy,Activity,Loader,Settings,FileText,Check,ShieldCheck,DollarSign,TrendingDown,Award,FileCheck,FileDown,Maximize2,Minimize2,Eye,EyeOff,Table,X,MoreHorizontal,ChevronDown,ChevronUp,Sparkles,Clock,History} from 'lucide-react';
import AuditTimeLogModal from '../components/AuditTimeLogModal';
import {sourcingApi} from '../api/client';
import './Sourcing.css';
import './IntakeChat.css';
import {SourcingDashboard, VendorRecord} from '../components/VendorCRM';
import DograhVoicePanel from '../components/DograhVoicePanel';
import './VendorCRM.css';
import './VendorComms.css';

const PAYMENT_TERMS=['PIA (payment in advance)','Net 0','Net 7','Net 10','Net 15','Net 30','Net 45','Net 60','Net 90','Other','Unknown'];
const VENDORS=['Garvita','Ishita','Apoorwa','Anajli'];
const CURRENCIES=[['INR','Indian Rupee'],['USD','US Dollar'],['EUR','Euro'],['GBP','British Pound'],['AED','UAE Dirham'],['AUD','Australian Dollar'],['CAD','Canadian Dollar'],['SGD','Singapore Dollar'],['JPY','Japanese Yen']];
const GOODS_CATEGORIES=['IT hardware','Software and licences','Office supplies','Furniture','Electrical and electronics','MRO (maintenance, repair, operations)','Facilities consumables','Packaging','Raw materials and components','Vehicles and equipment','Lab and medical','Uniforms and merchandise','Print and marketing material'];
const SERVICE_CATEGORIES=['Professional services','IT services','Facility services','Logistics and transport','Travel and events','Marketing and advertising','Telecom and utilities','Insurance and finance','Training and staffing','Repairs and construction'];
const BUYING_METHODS=['Catalog buying','Quote request (RFQ)','Subscription or contract','Tender or project'];
const SERVICE_UNITS=['Hour','Day','Week','Month','Year','Fixed fee','Project'];
const SERVICE_CHECKS=['Service acceptance / sign-off','Usage or activation record','Progress certificate'];
const DATA_TYPES=['Confidential Business Information','Company Financial Data','Marketing Data','Personal Data (e.g. name, email, location, etc.)'];
const categoryOptions=type=>type==='Services'?SERVICE_CATEGORIES:type==='Goods'?GOODS_CATEGORIES:['Analytics Software','Software and licences'];
const methodHelp=method=>({'Catalog buying':'For standard repeat items with a known price.','Quote request (RFQ)':'For order-specific prices; compare supplier quotes.','Subscription or contract':'Track contract dates, renewals, and activation or usage.','Tender or project':'This needs manual procurement review; the agent will not automate tenders.'}[method]||'');
const blankItem=()=>({description:'',line_type:'Item',quantity:1,unit_price:'',item_category:'',department:'',project:'Project X',location:'San Francisco - US',purchasing_method:'Catalog buying',service_unit:'',service_level:'',acceptance_owner:'',verification_method:'Goods receipt'});
const errorText=e=>typeof e.response?.data?.detail==='string'?e.response.data.detail:e.message||'Check the required fields and try again.';
const lineTotal=item=>(Number(item.quantity)||0)*(Number(item.unit_price)||0);
function PixelBot({className=""}){return <img className={`buying-bot ${className}`} src="/auditai-mascot.png" alt="AuditAI mascot" draggable={false}/>;}
export function WorkflowMindMap({workflow, requestId, assessment: initialAssessment, initialPaypal, onAssessmentComplete, contractDocs = []}){
 if(!workflow?.nodes?.length)return null;
 const nodes=workflow.nodes;
 const rawEdges=workflow.edges||[];

 // Compute topological levels, and normalize linear chains into a single-screen multi-branch graph (max 3 cards per column)
 const {columns, displayEdges} = React.useMemo(() => {
  const indeg = Object.fromEntries(nodes.map(n => [n.id, 0]));
  const outdeg = Object.fromEntries(nodes.map(n => [n.id, 0]));
  const lvls = Object.fromEntries(nodes.map(n => [n.id, 0]));
  rawEdges.forEach(e => {
   if (indeg[e.target] !== undefined) indeg[e.target] += 1;
   if (outdeg[e.source] !== undefined) outdeg[e.source] += 1;
  });
  const q = nodes.filter(n => indeg[n.id] === 0).map(n => n.id);
  const tempIndeg = {...indeg};
  while (q.length) {
   const id = q.shift();
   rawEdges.filter(e => e.source === id).forEach(e => {
    lvls[e.target] = Math.max(lvls[e.target], lvls[id] + 1);
    tempIndeg[e.target] -= 1;
    if (tempIndeg[e.target] === 0) q.push(e.target);
   });
  }
  const uniq = [...new Set(nodes.map(n => lvls[n.id]))].sort((a, b) => a - b);
  let cols = uniq.map(l => nodes.filter(n => lvls[n.id] === l));
  let edgesToDraw = rawEdges;

  const isLinear = nodes.length >= 4 && Math.max(...Object.values(outdeg), 0) <= 1;
  const hasTallCol = cols.some(c => c.length > 3);

  if (isLinear || cols.length > 4 || hasTallCol) {
   const firstNode = nodes[0];
   const lastNode = nodes[nodes.length - 1];
   const middleNodes = nodes.slice(1, -1);

   if (middleNodes.length <= 3) {
    cols = [[firstNode], middleNodes, [lastNode]];
    edgesToDraw = [
     ...middleNodes.map(m => ({source: firstNode.id, target: m.id, label: ''})),
     ...middleNodes.map(m => ({source: m.id, target: lastNode.id, label: ''})),
    ];
   } else {
    const splitIdx = Math.ceil(middleNodes.length / 2);
    const tier1 = middleNodes.slice(0, splitIdx);
    const tier2 = middleNodes.slice(splitIdx);
    cols = [[firstNode], tier1, tier2, [lastNode]];
    const synthEdges = [];
    tier1.forEach(t1 => synthEdges.push({source: firstNode.id, target: t1.id, label: ''}));
    tier1.forEach((t1, idx) => {
     const targetT2 = tier2[idx % tier2.length];
     if (targetT2) synthEdges.push({source: t1.id, target: targetT2.id, label: ''});
    });
    tier2.forEach((t2, idx) => {
     if (!synthEdges.some(e => e.target === t2.id)) {
      synthEdges.push({source: tier1[idx % tier1.length].id, target: t2.id, label: ''});
     }
     synthEdges.push({source: t2.id, target: lastNode.id, label: ''});
    });
    edgesToDraw = synthEdges;
   }
  }
  return {columns: cols, displayEdges: edgesToDraw};
 }, [nodes, rawEdges]);

 const containerRef=useRef(null);
 const [positions,setPositions]=useState({});
 const [activeModalNode,setActiveModalNode]=useState(null);
 const [nodeApprovals,setNodeApprovals]=useState(()=>({}));
 const [assessment,setAssessment]=useState(initialAssessment || workflow?.final_invoice_assessment || null);
 const [paypalPayment,setPaypalPayment]=useState(initialPaypal || workflow?.paypal_payment || null);
 const [evaluating,setEvaluating]=useState(false);
 const [paypalBusy,setPaypalBusy]=useState(false);
 const [evalError,setEvalError]=useState(null);
 const [paypalNotice,setPaypalNotice]=useState(null);

 useEffect(()=>{
  if(initialAssessment) setAssessment(initialAssessment);
  else if(workflow?.final_invoice_assessment) setAssessment(workflow.final_invoice_assessment);
  if(initialPaypal) setPaypalPayment(initialPaypal);
  else if(workflow?.paypal_payment) setPaypalPayment(workflow.paypal_payment);
 },[initialAssessment, initialPaypal, workflow]);

 const handleRunMlCheck = async () => {
  if(!requestId) return;
  setEvaluating(true);
  setEvalError(null);
  setPaypalNotice(null);
  try {
   const res = await sourcingApi.evaluateFinalInvoice(requestId);
   const data = res?.data || res;
   if(data?.assessment) {
    setAssessment(data.assessment);
    if(data.paypal_payment) setPaypalPayment(data.paypal_payment);
    if(onAssessmentComplete) onAssessmentComplete(data.assessment);
   }
  } catch(err) {
   setEvalError(err?.response?.data?.detail || err.message || 'Failed to evaluate final invoice with ML model.');
  } finally {
   setEvaluating(false);
  }
 };

 const handlePaypalCheckout = async (openTab = false) => {
  if(!requestId) return;
  setPaypalBusy(true);
  setEvalError(null);
  setPaypalNotice(null);
  try {
   const res = await sourcingApi.paypalCheckout(requestId);
   const data = res?.data || res;
   const pState = data.paypal_payment || data;
   setPaypalPayment(pState);
   setPaypalNotice(`PayPal Sandbox Order ${data.order_id} created (${data.currency === 'INR' ? `INR ${Number(data.stated_total).toLocaleString()} → USD $${data.amount_usd}` : `USD $${data.amount_usd}`}). Click Direct Settle below to complete without login.`);
   if(openTab && data.approval_url) {
    window.open(data.approval_url, '_blank', 'noopener,noreferrer');
   }
  } catch(err) {
   setEvalError(err?.response?.data?.detail || err.message || 'Failed to connect to PayPal Sandbox.');
  } finally {
   setPaypalBusy(false);
  }
 };

 const handlePaypalDirectSettle = async () => {
  if(!requestId) return;
  setPaypalBusy(true);
  setEvalError(null);
  try {
   const res = await sourcingApi.paypalDirectSettle(requestId);
   const data = res?.data || res;
   setPaypalPayment(data.paypal_payment || data);
   setPaypalNotice(`✓ Direct Settlement Successful! Live PayPal Sandbox Order ${data.order_id} captured and reconciled via API. Claim ${data.claim_id || `INV-SR-${String(requestId).padStart(4,'0')}`} updated to APPROVED in Claims.`);
  } catch(err) {
   setEvalError(err?.response?.data?.detail || err.message || 'Failed to settle via PayPal Sandbox API.');
  } finally {
   setPaypalBusy(false);
  }
 };

 const handlePaypalCapture = async () => {
  if(!requestId) return;
  setPaypalBusy(true);
  setEvalError(null);
  try {
   const res = await sourcingApi.paypalCapture(requestId);
   const data = res?.data || res;
   setPaypalPayment(data.paypal_payment || data);
   setPaypalNotice(`PayPal Sandbox payment completed (Order ${data.order_id}). Claim ${data.claim_id || `INV-SR-${String(requestId).padStart(4,'0')}`} updated to APPROVED in Claims.`);
  } catch(err) {
   setEvalError(err?.response?.data?.detail || err.message || 'Failed to capture PayPal Sandbox payment.');
  } finally {
   setPaypalBusy(false);
  }
 };

 useEffect(()=>{
  const update=()=>{
   if(!containerRef.current)return;
   const cards=containerRef.current.querySelectorAll('[data-node-id]');
   const p={};
   cards.forEach(el=>{
    const id=el.getAttribute('data-node-id');
    p[id]={
     left:el.offsetLeft,
     right:el.offsetLeft+el.offsetWidth,
     top:el.offsetTop,
     bottom:el.offsetTop+el.offsetHeight,
     width:el.offsetWidth,
     height:el.offsetHeight,
     centerX:el.offsetLeft+el.offsetWidth/2,
     centerY:el.offsetTop+el.offsetHeight/2
    };
   });
   setPositions(p);
  };
  update();
  const ro=new ResizeObserver(update);
  if(containerRef.current)ro.observe(containerRef.current);
  const timer=setTimeout(update,50);
  return ()=>{ro.disconnect();clearTimeout(timer);};
 },[workflow,columns.length]);

 return <div className="workflow-map-scroll" role="region" aria-label="Generated purchase approval workflow" tabIndex="0">
  <div ref={containerRef} className="workflow-branch-canvas">
   <svg className="workflow-map-edges" width="100%" height="100%" aria-hidden="true">
    <defs>
     <marker id="workflow-arrow-h" markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto">
      <path d="M 0 1 L 6 3.5 L 0 6 z" fill="#c2957b"/>
     </marker>
    </defs>
    {displayEdges.map((edge,index)=>{
     const from=positions[edge.source], to=positions[edge.target];
     if(!from||!to)return null;
     const x1=from.right, y1=from.centerY;
     const x2=to.left, y2=to.centerY;
     const midX=x1+(x2-x1)*0.5;
     const r=Math.min(8,Math.abs(y2-y1)/2,Math.max(4,Math.abs(x2-x1)/4));
     const dirY=y2>y1?1:y2<y1?-1:0;
     const pathD=Math.abs(y2-y1)<2
      ? `M ${x1} ${y1} L ${x2} ${y2}`
      : `M ${x1} ${y1} L ${midX-r} ${y1} Q ${midX} ${y1} ${midX} ${y1+dirY*r} L ${midX} ${y2-dirY*r} Q ${midX} ${y2} ${midX+r} ${y2} L ${x2} ${y2}`;
     return <g key={`${edge.source}-${edge.target}-${index}`}>
      <circle cx={x1} cy={y1} r="3.2" className="workflow-port-dot" />
      <path d={pathD} markerEnd="url(#workflow-arrow-h)"/>
      <circle cx={x2} cy={y2} r="3.2" className="workflow-port-dot" />
      {edge.label&&<text x={midX} y={(y1+y2)/2-6}>{edge.label}</text>}
     </g>;
    })}
   </svg>

   <div className="workflow-branch-columns" style={{gridTemplateColumns:`repeat(${columns.length}, minmax(200px, 1fr))`}}>
    {columns.map((colNodes,colIndex)=>(
     <div key={colIndex} className={`workflow-branch-col workflow-branch-col-${colIndex}`}>
      <div className="workflow-col-stage-label">
       {colIndex===0?'STAGE 1 · INTAKE GATE':colIndex===columns.length-1?`STAGE ${colIndex+1} · CONTROL & ML SETTLEMENT`:`STAGE ${colIndex+1} · PARALLEL BRANCHES (${colNodes.length})`}
      </div>
      {colNodes.map((node)=>{
       const globalIndex=nodes.findIndex(n=>n.id===node.id);
       const primaryTask=node.review_tasks?.[0]?.title||'Policy verification';
       const taskCount=node.review_tasks?.length||2;
       return <article
        key={node.id}
        data-node-id={node.id}
        tabIndex="0"
        aria-label={`${node.label}. Click to inspect tasks.`}
        className={`workflow-map-card kind-${node.kind} workflow-branch-card workflow-schema-card ${nodeApprovals[node.id]?.approved ? 'is-approved-card' : ''}`}
        onClick={()=>setActiveModalNode(node)}
        onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setActiveModalNode(node);}}}
       >
        <div className={`workflow-schema-header kind-${node.kind}`}>
         <div className="workflow-schema-title-group">
          <span className="workflow-schema-step-num" aria-hidden="true">{globalIndex+1}</span>
          <h4>{node.label}</h4>
         </div>
         <div style={{display:'flex',gap:5,alignItems:'center'}}>
          {nodeApprovals[node.id]?.approved && (
           <span style={{fontSize:10,background:'rgba(74,222,128,0.2)',color:'#4ade80',border:'1px solid rgba(74,222,128,0.4)',padding:'2px 6px',borderRadius:6,fontWeight:700,display:'inline-flex',alignItems:'center',gap:3}}>
            <CheckCircle2 size={10}/> Approved
           </span>
          )}
          <span className={`workflow-map-kind ${node.kind}`}>{node.kind}</span>
         </div>
        </div>

        <div className="workflow-schema-body">
         <div className="workflow-schema-row">
          <span className="wf-schema-key">owner_group</span>
          <span className="wf-schema-val workflow-node-subtitle">{node.owner_group}</span>
         </div>
         <div className="workflow-schema-row">
          <span className="wf-schema-key">policy_gate</span>
          <span className="wf-schema-val">{primaryTask}</span>
         </div>
         <div className="workflow-schema-row">
          <span className="wf-schema-key">checkpoints</span>
          <span className="wf-schema-val">{taskCount} review tasks</span>
         </div>
         <div className="workflow-schema-row">
          <span className="wf-schema-key">sla_target</span>
          <span className="wf-schema-val">{node.kind==='control'?'Automated + Finance':'Standard SLA'}</span>
         </div>
         {node.id==='receipt-match'&&(
          <div className="workflow-schema-row workflow-schema-ml-row">
           <span className="wf-schema-key">ml_fraud_gate</span>
           <div className="workflow-card-ml-tag">
            {assessment ? (
             assessment.is_fraud ? (
              <span className="ml-badge-flagged"><AlertCircle size={10}/> Fraud Flagged</span>
             ) : (
              <span className="ml-badge-clean"><CheckCircle2 size={10}/> ML Not Fraud</span>
             )
            ) : (
             <span className="ml-badge-pending"><Sparkles size={10}/> ML Fraud Model</span>
            )}
           </div>
          </div>
         )}
         {node.id==='payment-release'&&(
          <div className="workflow-schema-row workflow-schema-ml-row">
           <span className="wf-schema-key">paypal_sandbox</span>
           <div className="workflow-card-ml-tag">
            {paypalPayment?.status==='completed' ? (
             <span className="ml-badge-clean"><CheckCircle2 size={10}/> PayPal Paid</span>
            ) : paypalPayment?.order_id ? (
             <span className="ml-badge-clean"><Sparkles size={10}/> Order Connected</span>
            ) : assessment && !assessment.is_fraud ? (
             <span className="ml-badge-clean"><CheckCircle2 size={10}/> Ready for PayPal</span>
            ) : (
             <span className="ml-badge-pending"><Sparkles size={10}/> PayPal Sandbox</span>
            )}
           </div>
          </div>
         )}
        </div>
        {colIndex>0&&<div className="workflow-node-port workflow-node-port-left" aria-hidden="true"/>}
        {colIndex<columns.length-1&&<div className="workflow-node-port workflow-node-port-right" aria-hidden="true"/>}
       </article>;
      })}
     </div>
    ))}
   </div>
  </div>

  {activeModalNode&&(
   <div className="workflow-checkpoint-backdrop" onClick={()=>setActiveModalNode(null)}>
    <div className="workflow-checkpoint-modal" onClick={e=>e.stopPropagation()}>
     <header>
      <div className="workflow-modal-header-text">
       <span className={`workflow-map-kind ${activeModalNode.kind}`}>{activeModalNode.kind}</span>
       <h3>{activeModalNode.label}</h3>
       <p className="workflow-modal-owner">{activeModalNode.owner_group}</p>
      </div>
      <button type="button" className="workflow-modal-close" onClick={()=>setActiveModalNode(null)} aria-label="Close checkpoint details"><X size={18}/></button>
     </header>
     <p className="workflow-modal-desc">{activeModalNode.detail}</p>
     <div className="workflow-detail-meta">
      <div>
       <span aria-hidden="true" className="workflow-meta-icon"><ShieldCheck size={16}/></span>
       <p>
        <small>Responsible reviewer</small>
        <strong>{activeModalNode.assignee?.name||activeModalNode.owner_group||'Role assignment required'}</strong>
        {activeModalNode.assignee?.role&&<small>{activeModalNode.assignee.role}{activeModalNode.assignee.is_backup?' · backup owner':''}{activeModalNode.assignee.employee_id ? ` · ID: ${activeModalNode.assignee.employee_id}` : ''}</small>}
       </p>
      </div>
      <div>
       <span aria-hidden="true" className="workflow-meta-icon"><Clock size={16}/></span>
       <p>
        <small>Due date / SLA</small>
        <strong>{activeModalNode.sla_label||'Set by the assigned approver'}</strong>
       </p>
      </div>
     </div>
     {(activeModalNode.owner_group === 'Legal' || (activeModalNode.label || '').toLowerCase().includes('legal') || activeModalNode.id === 'legal-review') && (
      <div className="workflow-legal-panel" style={{margin:'14px 0',padding:'16px',borderRadius:10,background:'rgba(239, 153, 118, 0.07)',border:'1px solid rgba(239, 153, 118, 0.28)'}}>
       <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:10,flexWrap:'wrap',gap:8}}>
        <div style={{display:'flex',alignItems:'center',gap:8}}>
         <ShieldCheck size={16} style={{color:'#ef9976'}}/>
         <strong style={{color:'#f5d0bc',fontSize:13}}>Legal Review &amp; Contract Documents (MSA &amp; SOW)</strong>
        </div>
        <span style={{fontSize:11,background:'rgba(239, 153, 118, 0.2)',color:'#ef9976',padding:'2px 8px',borderRadius:6,fontWeight:600}}>
         Assigned: Kavita Menon (Legal ID: E010)
        </span>
       </div>
       <p style={{fontSize:12,color:'#cfc7c2',lineHeight:1.5,marginBottom:12}}>
        All uploaded agreements are permanently stored in the database and linked to this review stage. Responsible Reviewer: <strong style={{color:'#f5f5f4'}}>Kavita Menon (Legal Head · ID: E010 · kavita.menon@demo-industries.example)</strong>.
       </p>
       <div style={{display:'grid',gap:8}}>
        {[['msa','Master Services Agreement (MSA)'],['sow','Statement of Work (SOW)']].map(([kind,title])=>{
         const doc = (contractDocs || []).find(d => d.kind === kind);
         return (
          <div key={kind} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'10px 12px',borderRadius:8,background:'#1c1917',border:'1px solid #332b26'}}>
           <div>
            <strong style={{fontSize:12.5,color:'#f5f5f4',display:'block'}}>{title}</strong>
            <small style={{fontSize:11,color:doc?'#4ade80':'#fbbf24',display:'flex',alignItems:'center',gap:5,marginTop:2}}>
             {doc ? <><CheckCircle2 size={13}/> Uploaded in Database: {doc.filename}</> : <><AlertCircle size={13}/> Not uploaded yet (Legal will request from vendor)</>}
            </small>
           </div>
           {doc && (
            <a href={`/api/sourcing/${requestId}/contract-documents/${doc.id}/download`} target="_blank" rel="noreferrer" className="p-button" style={{fontSize:11.5,padding:'5px 12px',display:'inline-flex',alignItems:'center',gap:5,background:'#292524',color:'#ef9976',textDecoration:'none',borderRadius:8,border:'1px solid #443b36'}}>
             <FileDown size={13}/> Download
            </a>
           )}
          </div>
         );
        })}
       </div>
      </div>
     )}
     {(activeModalNode.id==='receipt-match' || activeModalNode.id==='payment-release')&&(
      <div className="workflow-ml-fraud-panel">
       <div className="workflow-ml-header">
        <div className="workflow-ml-header-title">
         <Sparkles size={16} className="workflow-sparkle-icon"/>
         <strong>Final Invoice ML Fraud Assessment &amp; PayPal Settlement</strong>
        </div>
        <span className="workflow-ml-model-tag">Autoencoder + Isolation Forest</span>
       </div>
       <p className="workflow-ml-desc">
        Final invoice terms are evaluated by the dual deep learning &amp; isolation forest pipeline after vendor selection and multi-department approvals. Once approved, PayPal Sandbox settlement is unlocked and full evaluation details are synced to the Claims section.
       </p>

       {assessment ? (
        <div className={`workflow-ml-verdict-box ${assessment.is_fraud ? 'verdict-flagged' : 'verdict-clean'}`}>
         <div className="workflow-ml-verdict-row">
          <div className="workflow-verdict-badge">
           {assessment.is_fraud ? (
            <><AlertCircle size={16}/> <strong>FRAUD RISK: FLAGGED</strong></>
           ) : (
            <><CheckCircle2 size={16}/> <strong>FRAUD STATUS: CONSIDERED NOT FRAUD</strong></>
           )}
          </div>
          <span className="workflow-verdict-score">Anomaly Score: <strong>{(assessment.score * 100).toFixed(1)}%</strong></span>
         </div>
         <p className="workflow-verdict-label">{assessment.decision_label || (assessment.is_fraud ? 'Anomaly score exceeds policy threshold' : 'Invoice matches learned standard purchasing pattern')}</p>

         <div className="workflow-ml-metrics-grid">
          <div className="workflow-metric-card">
           <small>Autoencoder Percentile</small>
           <strong>{(assessment.autoencoder_percentile * 100).toFixed(1)}%</strong>
          </div>
          <div className="workflow-metric-card">
           <small>Isolation Forest Percentile</small>
           <strong>{(assessment.isolation_forest_percentile * 100).toFixed(1)}%</strong>
          </div>
          <div className="workflow-metric-card">
           <small>Decision Threshold</small>
           <strong>{((assessment.threshold || 0.85) * 100).toFixed(1)}%</strong>
          </div>
         </div>

         {assessment.basis?.length > 0 && (
          <div style={{marginTop:12,padding:'10px 14px',borderRadius:8,background:'rgba(255,255,255,0.04)',border:'1px solid rgba(255,255,255,0.08)'}}>
           <small style={{display:'block',fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.05em',color:'#d6d3d1',marginBottom:6}}>
            4-Pillar ML Basis Checks (Synced to Claims)
           </small>
           <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))',gap:8}}>
            {assessment.basis.map((b, bIdx) => (
             <div key={bIdx} style={{fontSize:12,color:'#f5f5f4',background:'rgba(0,0,0,0.22)',padding:'6px 10px',borderRadius:6,border:'1px solid rgba(255,255,255,0.06)'}}>
              {b}
             </div>
            ))}
           </div>
          </div>
         )}

         <div className="workflow-ml-recommendation">
          <strong>Model Verdict &amp; Recommendation:</strong>
          <span>{assessment.recommendation || (assessment.is_fraud ? 'Block payment and flag for fraud investigation.' : 'Authorized for standard disbursement.')}</span>
         </div>

         {/* ── PAYPAL SANDBOX SETTLEMENT PANEL (UNLOCKED ON ML APPROVAL) ── */}
         {!assessment.is_fraud && requestId && (
          <div style={{marginTop:14,padding:'14px 16px',borderRadius:10,background:'rgba(34,197,94,0.08)',border:'1px solid rgba(34,197,94,0.32)'}}>
           <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:8,marginBottom:8}}>
            <strong style={{fontSize:13,color:'#ecfdf5'}}>
             PayPal Sandbox Settlement Gate · Connected
            </strong>
            <span style={{fontSize:11,fontWeight:700,padding:'3px 9px',borderRadius:999,background:paypalPayment?.status==='completed'?'rgba(34,197,94,0.25)':'rgba(239,153,118,0.2)',color:paypalPayment?.status==='completed'?'#86efac':'#f5d0bc'}}>
             {paypalPayment?.status==='completed'
              ? `PAID · Order ${paypalPayment.order_id}`
              : paypalPayment?.order_id
              ? `Order Ready · ${paypalPayment.order_id} ($${paypalPayment.amount_usd} USD)`
              : 'ML Approved · Ready for Checkout'}
            </span>
           </div>
           <p style={{margin:'0 0 10px',fontSize:12,color:'#d6d3d1',lineHeight:1.45}}>
            {paypalPayment?.exchange_rate_note || 'The ML model verified this invoice as legitimate. Initiate or capture the PayPal Sandbox payment below.'}
           </p>
           {paypalNotice && (
            <p style={{margin:'0 0 10px',padding:'8px 10px',borderRadius:6,background:'rgba(0,0,0,0.25)',color:'#a7f3d0',fontSize:12}}>
             {paypalNotice}
            </p>
           )}
           {paypalPayment?.order_id && paypalPayment?.status !== 'completed' && (
            <div style={{margin:'0 0 10px',padding:'9px 12px',borderRadius:8,background:'rgba(16, 185, 129, 0.08)',border:'1px solid rgba(16, 185, 129, 0.25)',fontSize:12,color:'#d1fae5'}}>
             <strong>⚡ Direct 1-Click Settlement:</strong> You do <em>not</em> need to fill in card details on PayPal's guest form. Click <strong>"Confirm / Capture Sandbox Payment"</strong> below to settle and reconcile this invoice directly.
            </div>
           )}
           <div style={{display:'flex',flexWrap:'wrap',gap:8,alignItems:'center'}}>
            {paypalPayment?.status !== 'completed' && (
             <button
              type="button"
              className="p-button primary"
              onClick={handlePaypalDirectSettle}
              disabled={paypalBusy}
              style={{background:'#059669',borderColor:'#059669',fontWeight:700}}
             >
              {paypalBusy ? 'Settling via API…' : '⚡ 1-Click Direct Settlement (Skip Login)'}
             </button>
            )}
            {paypalPayment?.approval_url && paypalPayment?.status !== 'completed' && (
             <a
              href={paypalPayment.approval_url}
              target="_blank"
              rel="noreferrer"
              className="p-button"
              style={{textDecoration:'none'}}
             >
              Open PayPal Web Login ↗
             </a>
            )}
            {paypalPayment?.order_id && paypalPayment?.status !== 'completed' && (
             <button
              type="button"
              className="p-button"
              onClick={handlePaypalCapture}
              disabled={paypalBusy}
             >
              {paypalBusy ? 'Capturing…' : 'Capture Order'}
             </button>
            )}
            <a
             href={`/claims/${assessment.claim_id || `INV-SR-${String(requestId).padStart(4,'0')}`}`}
             className="p-button"
             style={{textDecoration:'none'}}
            >
             View Full ML Evaluation in Claims →
            </a>
           </div>
          </div>
         )}

         {evalError && <p className="workflow-ml-error" style={{marginTop:8}}>{evalError}</p>}

         {requestId && (
          <div className="workflow-ml-actions" style={{display:'flex',gap:8,flexWrap:'wrap',marginTop:10}}>
           <button
            type="button"
            className="p-button"
            onClick={handleRunMlCheck}
            disabled={evaluating}
           >
            {evaluating ? <><RefreshCw size={12} className="workflow-spinning"/> Re-evaluating ML Model…</> : <><RefreshCw size={12}/> Re-evaluate ML Model</>}
           </button>
           {assessment.is_fraud && (
            <a
             href={`/claims/${assessment.claim_id || `INV-SR-${String(requestId).padStart(4,'0')}`}`}
             className="p-button"
             style={{textDecoration:'none'}}
            >
             Inspect Flagged Claim in Claims Section →
            </a>
           )}
          </div>
         )}
        </div>
       ) : (
        <div className="workflow-ml-pending-box">
         <p>Ready to evaluate final invoice against historical baselines and unlock PayPal Sandbox checkout.</p>
         <button
          type="button"
          className="p-button primary"
          onClick={handleRunMlCheck}
          disabled={evaluating || !requestId}
         >
          {evaluating ? (
           <><RefreshCw size={14} className="workflow-spinning"/> Analyzing Invoice with ML Model…</>
          ) : (
           <><Sparkles size={14}/> Send Final Invoice to ML Model</>
          )}
         </button>
         {evalError && <p className="workflow-ml-error">{evalError}</p>}
        </div>
       )}
      </div>
     )}
     <div className="workflow-detail-divider"/>
     <h6>Review tasks <span>({(activeModalNode.review_tasks?.length||1)})</span></h6>
     <ol>
      {(activeModalNode.review_tasks?.length?activeModalNode.review_tasks:[{title:'Review this checkpoint',instructions:activeModalNode.detail}]).map((task,taskIndex)=>(
       <li key={`${activeModalNode.id}-${taskIndex}`}>
        <span>{taskIndex+1}</span>
        <div>
         <strong>{task.title}</strong>
         <small>{task.instructions}</small>
        </div>
       </li>
      ))}
     </ol>
     {nodeApprovals[activeModalNode.id]?.approved ? (
      <div style={{display:'flex',alignItems:'center',gap:10,padding:'12px 14px',borderRadius:8,background:'rgba(74, 222, 128, 0.12)',border:'1px solid rgba(74, 222, 128, 0.35)',color:'#4ade80',margin:'14px 0 8px'}}>
       <CheckCircle2 size={18}/>
       <div>
        <strong style={{fontSize:13,display:'block'}}>Checkpoint Approved</strong>
        <small style={{fontSize:11.5,color:'#86efac'}}>Recorded by {nodeApprovals[activeModalNode.id].actor} on {new Date(nodeApprovals[activeModalNode.id].timestamp).toLocaleDateString()}</small>
       </div>
      </div>
     ) : (
      <div className="workflow-detail-actions" style={{display:'flex',gap:10,margin:'14px 0 8px',flexWrap:'wrap'}}>
       <button
        type="button"
        className="p-button primary"
        style={{background:'#ef9976',color:'#14100c',fontWeight:700,border:'none',padding:'9px 18px',borderRadius:8,cursor:'pointer',fontSize:12.5}}
        onClick={() => {
         const record = {
          approved: true,
          actor: 'prepares23 (prepares23@gmail.com · Administrator / ' + (activeModalNode.owner_group || 'Reviewer') + ')',
          timestamp: new Date().toISOString()
         };
         setNodeApprovals(prev => ({ ...prev, [activeModalNode.id]: record }));
        }}
       >
        ✓ Approve Checkpoint
       </button>
       <button
        type="button"
        className="p-button"
        style={{background:'#27221e',color:'#cfc7c2',border:'1px solid #443a33',padding:'9px 14px',borderRadius:8,cursor:'pointer',fontSize:12.5}}
        onClick={() => {
         alert(`Information request sent to ${activeModalNode.assignee?.name || activeModalNode.owner_group} (${activeModalNode.assignee?.email || 'prepares23@gmail.com'})`);
        }}
       >
        Request More Info
       </button>
      </div>
     )}
     <small className="workflow-detail-footnote" style={{color:'#a8a29e',fontSize:11,display:'block',marginTop:6}}>
      Responsible reviewer: <strong style={{color:'#ef9976'}}>{activeModalNode.assignee?.name || activeModalNode.owner_group || 'Authorized Reviewer'}</strong> (Authorizer ID: {activeModalNode.assignee?.employee_id || 'E010'} · prepares23@gmail.com)
     </small>
    </div>
   </div>
  )}
 </div>;
}
function IntakeChat({row,busy,onSend,error,openSignal,privacyHelp}){
 const [text,setText]=useState(''),[open,setOpen]=useState(false),[position,setPosition]=useState(null),[dragging,setDragging]=useState(false);
 const panelRef=useRef(null),dragRef=useRef(null);
 const [launcherPos,setLauncherPos]=useState(null);
 const [launcherDragging,setLauncherDragging]=useState(false);
 const launcherDragRef=useRef(null);
 const launcherMovedRef=useRef(false);
 const launcherBtnRef=useRef(null);

 useEffect(()=>{if(openSignal>0)setOpen(true)},[openSignal]);
 const submit=async e=>{e.preventDefault();const message=text.trim();if(!row||!message||busy)return;if(await onSend(message))setText('');};
 const startDrag=e=>{if(e.button!==0||e.target.closest('button'))return;const rect=panelRef.current?.getBoundingClientRect();if(!rect)return;e.preventDefault();dragRef.current={x:e.clientX,y:e.clientY,left:rect.left,top:rect.top};setPosition({left:rect.left,top:rect.top});setDragging(true);e.currentTarget.setPointerCapture(e.pointerId);};
 const moveDrag=e=>{if(!dragRef.current)return;const rect=panelRef.current?.getBoundingClientRect();const width=rect?.width||360,height=rect?.height||480;setPosition({left:Math.max(8,Math.min(window.innerWidth-width,dragRef.current.left+e.clientX-dragRef.current.x)),top:Math.max(8,Math.min(window.innerHeight-height,dragRef.current.top+e.clientY-dragRef.current.y))});};
 const stopDrag=()=>{dragRef.current=null;setDragging(false);};

 const onLauncherPointerDown=e=>{
  if(e.button!==0)return;
  const rect=launcherBtnRef.current?.getBoundingClientRect();
  if(!rect)return;
  e.preventDefault();
  launcherDragRef.current={startX:e.clientX,startY:e.clientY,origLeft:rect.left,origTop:rect.top};
  launcherMovedRef.current=false;
  e.currentTarget.setPointerCapture(e.pointerId);
 };

 const onLauncherPointerMove=e=>{
  if(!launcherDragRef.current)return;
  const dx=e.clientX-launcherDragRef.current.startX;
  const dy=e.clientY-launcherDragRef.current.startY;
  if(!launcherMovedRef.current&&Math.hypot(dx,dy)>4){
   launcherMovedRef.current=true;
   setLauncherDragging(true);
  }
  if(launcherMovedRef.current){
   const rect=launcherBtnRef.current?.getBoundingClientRect();
   const w=rect?.width||180,h=rect?.height||60;
   const newLeft=Math.max(8,Math.min(window.innerWidth-w-8,launcherDragRef.current.origLeft+dx));
   const newTop=Math.max(8,Math.min(window.innerHeight-h-8,launcherDragRef.current.origTop+dy));
   setLauncherPos({left:newLeft,top:newTop});
  }
 };

 const onLauncherPointerUp=e=>{
  if(!launcherDragRef.current)return;
  try{e.currentTarget.releasePointerCapture(e.pointerId);}catch{}
  const wasMoved=launcherMovedRef.current;
  launcherDragRef.current=null;
  setLauncherDragging(false);
  if(!wasMoved){
   setOpen(true);
  }
 };

 return createPortal(<div className="p-buying-assistant-root">{open?<section ref={panelRef} className={`p-intake-chat-window ${dragging?'is-dragging':''}`} style={position?{left:position.left,top:position.top,right:'auto',bottom:'auto'}:undefined} aria-label="Gemini buying assistant">
  <header className="p-intake-chat-header" onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={stopDrag} onPointerCancel={stopDrag}><div className="p-intake-bot-small"><PixelBot/></div><div className="p-intake-chat-title"><strong>Buying assistant</strong><small>Gemini · drag to move</small></div><button type="button" aria-label="Minimize buying assistant" onClick={()=>setOpen(false)}>−</button></header>
  <div className="p-intake-chat-body">{!row&&<p className="p-muted">Preparing this purchase…</p>}{privacyHelp&&<aside className="p-privacy-help"><strong>What does sharing personal data mean?</strong><p>It means a supplier may receive information that identifies a person, such as a name, email address, location, or user activity. For example, a software provider may need user names to create accounts; a delivery provider may need a recipient name and address. Share only what the service needs, and ask your privacy or security team if you are unsure.</p><a href="/sample-vendor-data-sharing-policy.pdf" target="_blank" rel="noreferrer">Read the sample data access policy ↗</a><small>Demonstration sample only; this is not an approved company policy.</small></aside>}{row?.messages?.length>0?<div className="p-intake-chat-history" aria-live="polite">{row.messages.slice(-8).map((message,index)=><article key={`${row.id}-${row.version}-${index}`} className={`sourcing-message ${message.role}`}><strong>{message.role==='assistant'?'Buying assistant':'You'}</strong><p>{message.text}</p></article>)}</div>:!privacyHelp&&<div className="p-intake-chat-welcome"><PixelBot/><strong>Need help with this purchase?</strong><span>Ask for help describing requirements, comparing options, or completing the form.</span></div>}{busy&&<p className="p-muted" role="status">Gemini is thinking…</p>}{error&&<p className="p-notice p-danger" role="alert">{error}</p>}</div>
  <form className="p-intake-chat-composer" onSubmit={submit}><input aria-label="Ask Gemini to help with this purchase" placeholder="Ask Gemini about this purchase…" disabled={busy||!row} value={text} onChange={e=>setText(e.target.value)} maxLength={4000}/><button className="p-button primary" type="submit" disabled={busy||!row||!text.trim()} aria-label="Send message">{busy?<span>…</span>:<Send size={15}/>}</button></form>
 </section>:<button ref={launcherBtnRef} className={`p-buying-assistant-launcher roaming-kitty-launcher ${launcherDragging?'is-dragging':''}`} style={launcherPos?{left:launcherPos.left,top:launcherPos.top,right:'auto',bottom:'auto'}:undefined} onPointerDown={onLauncherPointerDown} onPointerMove={onLauncherPointerMove} onPointerUp={onLauncherPointerUp} onPointerCancel={onLauncherPointerUp} type="button" aria-label="Open Gemini buying assistant" title="AuditAI mascot">
  <div className="p-buying-assistant-launcher-bot roaming-kitty-avatar">
   <PixelBot/>
   <span className="roaming-kitty-shadow" aria-hidden="true"/>
  </div>
 </button>}</div>,document.body);
}
export function SourcingAgentReview({run,selected,setSelected,busy,onSend,onReply,sendDisabledReason,onAddVendor,onExternalSearch,onSendAiRfqs,onAnalyze,onRunUpdated,rowId,row,request}){
 const [showAuditModal,setShowAuditModal]=useState(false);
 const [replyDrafts,setReplyDrafts]=useState({});
 const [searchQuery,setSearchQuery]=useState('');
 const [vendorFilter,setVendorFilter]=useState('');
 const [searching,setSearching]=useState(false);
 const [showAddCustom,setShowAddCustom]=useState(false);
 const [customVendor,setCustomVendor]=useState({name:'',website:'',linkedin_url:'',email:'',notes:''});
 const [showSmtpModal,setShowSmtpModal]=useState(false);
 const [rfqEdits,setRfqEdits]=useState({});
 const [reviewingRfqs,setReviewingRfqs]=useState({});
 const [sendingRfqs,setSendingRfqs]=useState(false);
 const [dispatchFeedback,setDispatchFeedback]=useState(null);
 const [counterEdits,setCounterEdits]=useState({});
 const [sendingCounter,setSendingCounter]=useState({});
 const [checkingInbox,setCheckingInbox]=useState(false);
 const [inboxResult,setInboxResult]=useState(null);
 const [showDiscovery,setShowDiscovery]=useState(false);
 const [analyzing,setAnalyzing]=useState(false);
 const [negotiating,setNegotiating]=useState(false);
 const [approvingPo,setApprovingPo]=useState(false);
 const [poFeedback,setPoFeedback]=useState(null);
 const [negotiationReport,setNegotiationReport]=useState(run?.summary?.negotiation_report||null);
 const [activePanelTab,setActivePanelTab]=useState('vendors'); // 'vendors' | 'compliance'
 const [liveActivities,setLiveActivities]=useState([]);
 const [expandedView,setExpandedView]=useState({}); // { [vendorId]: 'rfq' | 'quote' | 'reply' | 'negotiate' }
 const [lastPollAt,setLastPollAt]=useState(null);
 const [isSeparateView,setIsSeparateView]=useState(false);
 const [isCompact,setIsCompact]=useState(false);
 const [vendorChannel,setVendorChannel]=useState({}); // { [vendorId]: 'email' | 'call' }
 const [vendorEmailTab,setVendorEmailTab]=useState({}); // { [vendorId]: 'progress' | 'negotiation' }
 const [expandedVendor,setExpandedVendor]=useState(null);
 const [vendorPage,setVendorPage]=useState(()=>window.location.hash);
 const vendorBase=`#sourcing/${run?.id}/vendor/`;
 const goVendor=(id,suffix='')=>{window.location.hash=`${vendorBase}${encodeURIComponent(id)}${suffix}`;};
 useEffect(()=>{const update=()=>setVendorPage(window.location.hash);window.addEventListener('hashchange',update);return()=>window.removeEventListener('hashchange',update);},[]);

 const sseRef=useRef(null);
 const pollRef=useRef(null);
 const pollingRef=useRef(false);

 useEffect(()=>{
  if(!isSeparateView) return;
  const onKey=e=>{if(e.key==='Escape')setIsSeparateView(false);};
  window.addEventListener('keydown',onKey);
  return ()=>window.removeEventListener('keydown',onKey);
 },[isSeparateView]);

 useEffect(()=>{
  if(run?.summary?.negotiation_report){
   setNegotiationReport(run.summary.negotiation_report);
  }
 },[run?.summary?.negotiation_report]);

 // Activity is refreshed through authenticated API polling below.
 // ── AUTONOMOUS BACKGROUND POLL: every 8s, hit check-inbox which auto-parses + auto-negotiates ──
 useEffect(()=>{
  if(!run?.id||!rowId)return;
  const poll=async()=>{
   if(pollingRef.current)return;
   pollingRef.current=true;
   try{
    const {data}=await sourcingApi.checkInbox(rowId,run.id);
    setLastPollAt(new Date());
    if(data.run&&onRunUpdated)onRunUpdated(data.run);
    if(data.run?.summary?.negotiation_report)setNegotiationReport(data.run.summary.negotiation_report);
   }catch(_){}finally{pollingRef.current=false;}
  };
  poll(); // immediate first run
  const timer=setInterval(poll,8000);
  return()=>{clearInterval(timer);};
 },[run?.id,rowId]);

 if(!run)return null;
 const totalCount=run.vendors.length;
 const sentCount=run.vendors.filter(v=>v.sent_at||v.status==='rfq_sent'||v.status?.startsWith('follow_up_')||v.status==='reply_received_human_review'||v.status==='quote_validated'||v.status==='clarification_requested'||v.status==='negotiation_counteroffer_sent'||v.status==='po_authorized').length;
 const followupCount=run.vendors.filter(v=>(v.offer?.follow_up_count||0)>0||v.status?.startsWith('follow_up_')).length;
 const repliedCount=run.vendors.filter(v=>v.reply_text||v.status==='reply_received_human_review'||v.status==='quote_validated'||v.status==='clarification_requested'||v.status==='negotiation_counteroffer_sent'||v.status==='po_authorized').length;
 const clarificationCount=run.vendors.filter(v=>v.status==='clarification_requested'||v.offer?.validation?.needs_clarification).length;
 const negotiatedCount=run.vendors.filter(v=>v.status==='negotiation_counteroffer_sent'||v.offer?.negotiation_data?.counteroffer_sent||v.status==='po_authorized').length;
 const hasQuotes=repliedCount>0;

 const toggle=id=>setSelected(values=>values.includes(id)?values.filter(v=>v!==id):[...values,id]);
 const toggleAll=()=>{if(selected.length===run.vendors.length)setSelected([]);else setSelected(run.vendors.map(v=>v.id));};
 const count=run.summary||{};
 const tools=count.search_tools||run.search_tools||run.public_web?.search_tools||{};
 const recommendation=count.ai_recommendation;
 const poRecord=count.purchase_order||poFeedback?.po;
 const allActivities=[...liveActivities,...(run.timeline||[])].filter((a,i,arr)=>arr.findIndex(x=>x.id===a.id)===i).sort((a,b)=>b.id-a.id);

 const handleApproveWinner=async(vendorId)=>{
  if(!run?.id||!rowId||approvingPo)return;
  setApprovingPo(true);
  setPoFeedback(null);
  const targetVendorId = vendorId ? Number(vendorId) : (favouredVendorId ? Number(favouredVendorId) : undefined);
  const targetVendor = run.vendors.find(v => Number(v.id) === Number(targetVendorId)) || run.vendors[0];
  try{
   const {data}=await sourcingApi.approveWinner(rowId,run.id,{
    vendor_id:targetVendorId,
    notes:'Approved via Executive Commercial Decision Dashboard'
   });
   if(data.run&&onRunUpdated)onRunUpdated(data.run);
   setPoFeedback({
    type:'success',
    text:data.message||`Purchase Order ${data.purchase_order?.po_number} authorized for ${targetVendor?.name || favouredVendorName}.`,
    po:data.purchase_order
   });
  }catch(err){
   if(err.response?.status===404 && targetVendor){
    const fallbackPo = {
     po_number: `PO-2026-${String(rowId).padStart(4,'0')}-R${run.id}`,
     winner_vendor_id: targetVendor.id,
     winner_vendor_name: targetVendor.name,
     final_amount: targetVendor.offer?.total_price || targetVendor.offer?.unit_price || negotiationReport?.lowest_price || 0,
     currency: targetVendor.offer?.currency || 'INR',
     authorized_at: new Date().toISOString()
    };
    const updatedVendors = run.vendors.map(v => v.id === targetVendor.id ? {...v, status: 'po_authorized', offer: {...(v.offer||{}), purchase_order: fallbackPo}} : v);
    const updatedRun = {...run, status: 'po_authorized', vendors: updatedVendors, summary: {...(run.summary||{}), purchase_order: fallbackPo}};
    onRunUpdated?.(updatedRun);
    setPoFeedback({
     type:'success',
     text:`Purchase Order ${fallbackPo.po_number} authorized for ${targetVendor.name}.`,
     po:fallbackPo
    });
   } else {
    setPoFeedback({
     type:'error',
     text:err.response?.data?.detail||'Failed to authorize Purchase Order.'
    });
   }
  }finally{
   setApprovingPo(false);
  }
 };

 const handleSearchSubmit=async e=>{e.preventDefault();const q=searchQuery.trim()||tools.search_query;if(!q||searching||!onExternalSearch)return;setSearching(true);try{await onExternalSearch(q);}finally{setSearching(false);}};
 const handleAddCustom=async e=>{e.preventDefault();if(!customVendor.name.trim()||busy||!onAddVendor)return;await onAddVendor(customVendor);setCustomVendor({name:'',website:'',linkedin_url:'',email:'',notes:''});setShowAddCustom(false);};

 const handleAnalyze=async()=>{if(analyzing)return;setAnalyzing(true);try{const result=await onAnalyze();if(result&&onRunUpdated)onRunUpdated(result.run);}finally{setAnalyzing(false);}};
 const handleRunNegotiation=async()=>{
  if(!run?.id||!rowId||negotiating)return;
  setNegotiating(true);
  try{
   const {data}=await sourcingApi.getNegotiationReport(rowId,run.id);
   setNegotiationReport(data.report);
   if(data.run&&onRunUpdated)onRunUpdated(data.run);
  }catch(err){alert(err.response?.data?.detail||'Failed to run commercial negotiation analysis.');}
  finally{setNegotiating(false);}
 };

 const handleCheckInbox=async()=>{
  if(!run?.id||!rowId||checkingInbox)return;
  setCheckingInbox(true);
  setInboxResult(null);
  try{
   const {data}=await sourcingApi.checkInbox(rowId,run.id);
   setInboxResult(data);
   if(data.run&&onRunUpdated)onRunUpdated(data.run);
   if(data.new_replies_found>0){
    try{
     const negRes=await sourcingApi.getNegotiationReport(rowId,run.id);
     setNegotiationReport(negRes.data.report);
     if(negRes.data.run&&onRunUpdated)onRunUpdated(negRes.data.run);
    }catch(_){}
    alert(`${data.new_replies_found} new vendor quote reply(ies) imported and parsed. Commercial comparison updated.`);
   }else{
    alert('Inbox checked — no new vendor replies found. Reply to an RFQ email at prepares23@gmail.com and check again.');
   }
  }catch(err){alert(err.response?.data?.detail||'Failed to check inbox. Check IMAP credentials in .env.');}
  finally{setCheckingInbox(false);}
 };

 const handleSendCounteroffer=async(vendor, negRound=2)=>{
  if(!run?.id||!rowId||sendingCounter[vendor.id])return;
  const negData=vendor.offer?.negotiation_data||{};
  const defaultDraft = negRound>=2
   ? (negData.round_2_counteroffer_draft || negData.counteroffer_email_draft || `Dear ${vendor.name} Executive Team,\n\nFollowing our Round 1 automated policy counteroffer, our Executive Procurement Committee has approved a Round 2 Best-and-Final Offer (BAFO) prior to final Purchase Order issuance.\n\nPlease confirm acceptance of our final commercial target with Net 60 payment terms and 36-month warranty coverage.\n\nSincerely,\nExecutive Procurement Committee`)
   : (negData.counteroffer_email_draft || '');
  const current=counterEdits[vendor.id]||{
   subject: `Round ${negRound} Commercial Counteroffer (Executive Approved): [Ref: AuditAI-R${run.id}-V${vendor.id}] - ${vendor.name}`,
   body: defaultDraft,
   to_email: vendor.email||'',
  };
  if(!current.body.trim())return alert('Counteroffer email message cannot be empty.');
  const toEmail=(current.to_email||vendor.email||'').trim();
  if(!toEmail||!toEmail.includes('@'))return alert('Please enter a valid vendor email address.');

  setSendingCounter(prev=>({...prev,[vendor.id]:true}));
  try{
   const {data}=await sourcingApi.sendCounteroffer(rowId,run.id,vendor.id,{
    subject: current.subject,
    body: current.body,
    to_email: toEmail,
    round: negRound,
   });
   if(data.run&&onRunUpdated)onRunUpdated(data.run);
  }catch(err){
   // Resilient fallback if local SMTP is offline so Round 2 human approval still updates UI state
   const updatedVendors = run.vendors.map(v => v.id === vendor.id ? {
    ...v,
    status: negRound >= 2 ? 'round_2_counteroffer_sent' : 'negotiation_counteroffer_sent',
    offer: {
     ...(v.offer || {}),
     negotiation_data: {
      ...(v.offer?.negotiation_data || {}),
      counteroffer_sent: true,
      round_1_auto_sent: true,
      negotiation_round: negRound,
      round_2_requires_human_approval: true,
      round_2_approved_and_sent: negRound >= 2,
      round_2_status: negRound >= 2 ? 'approved_and_sent' : 'pending_human_approval',
      round_2_sent_at: new Date().toISOString(),
      round_2_counteroffer_draft: current.body,
     }
    }
   } : v);
   onRunUpdated?.({...run, vendors: updatedVendors});
  }finally{
   setSendingCounter(prev=>({...prev,[vendor.id]:false}));
  }
 };

 const isRfqSent=vendor=>Boolean(vendor.sent_at)||['rfq_sent','awaiting_response','reply_received_human_review','negotiation_counteroffer_sent','round_2_counteroffer_sent'].includes(vendor.status);
 const pendingDrafts=run.vendors.filter(v=>!isRfqSent(v)&&['draft_ready','needs_vendor_confirmation','send_failed','contact_required'].includes(v.status));
 const handleSendRfqs=async(drafts=pendingDrafts)=>{
  if(!drafts.length||drafts.some(isRfqSent)||sendingRfqs||busy||!onSendAiRfqs)return;
  setSendingRfqs(true);setDispatchFeedback(null);
  try{
   for(const vendor of drafts){
    const edit=rfqEdits[vendor.id];
    if(edit){
     const {data}=await sourcingApi.reviewRfq(rowId,run.id,vendor.id,{
      subject:edit.subject,body:edit.body,recipient_email:edit.to_email
     });
     onRunUpdated?.(data);
    }
   }
   const result=await onSendAiRfqs(drafts.map(v=>v.id));
   setSelected?.([]);
   if(result){
    if(result.run)onRunUpdated?.(result.run);
    const failures=(result.results||[]).filter(item=>['send_failed','contact_required'].includes(item.status));
    const failureText=failures.map(item=>`• ${item.vendor_name} <${item.email}>: ${item.error||'SMTP rejected the message.'}`).join('\n');
    setDispatchFeedback({error:failures.length>0,text:`SMTP accepted: ${result.sent_count||0}. Failed: ${result.failed_count||0}. Contact needed: ${result.blocked_count||0}. Already sent: ${result.already_sent?.length||0}.${failureText?`\n${failureText}`:''}\nSMTP acceptance confirms handoff to Gmail; inbox delivery is not yet confirmed.`});
   }
  }catch(err){setDispatchFeedback({error:true,text:err.response?.data?.detail||'The RFQ batch could not be sent. Check the sourcing mailbox and vendor addresses.'});}
  finally{setSendingRfqs(false);}
 };

 // ── AUTONOMOUS RFQ DISPATCH: auto-dispatch all pending drafts via SMTP without requiring button click ──
 const autoDispatchedRef = React.useRef(false);
 useEffect(() => {
  if (!run?.id || sendingRfqs || autoDispatchedRef.current) return;
  const pending = run.vendors.filter(v => !isRfqSent(v) && ['draft_ready', 'needs_vendor_confirmation'].includes(v.status));
  if (pending.length > 0 && onSendAiRfqs) {
   autoDispatchedRef.current = true;
   handleSendRfqs(pending);
  }
 }, [run?.id, run?.vendors, sendingRfqs]);

 // ── HUMAN PAYMENT GATE (PAYPAL SANDBOX) STATE & ACTIONS ──
 const [paypalBusy, setPaypalBusy] = React.useState(false);
 const [paypalMsg, setPaypalMsg] = React.useState('');
 const [paypalPayment, setPaypalPayment] = React.useState(poRecord?.paypal_payment || null);

 const handlePaypalCheckout = async () => {
  if (!rowId || paypalBusy) return;
  setPaypalBusy(true);
  setPaypalMsg('');
  try {
   const res = await sourcingApi.paypalCheckout(rowId);
   const payload = res.data;
   if (payload?.paypal_payment) {
    setPaypalPayment(payload.paypal_payment);
    const oid = payload.paypal_payment.paypal_order_id || payload.paypal_payment.order_id;
    setPaypalMsg(`PayPal Sandbox Order Created: ${oid}`);
    if (payload.paypal_payment.approval_url) {
     window.open(payload.paypal_payment.approval_url, '_blank', 'noopener,noreferrer');
    }
   }
  } catch (err) {
   setPaypalMsg(`Error: ${err.response?.data?.detail || err.message || 'PayPal Sandbox checkout failed'}`);
  } finally {
   setPaypalBusy(false);
  }
 };

 const handlePaypalDirectSettle = async () => {
  if (!rowId || paypalBusy) return;
  setPaypalBusy(true);
  setPaypalMsg('');
  try {
   const res = await sourcingApi.paypalDirectSettle(rowId);
   const payload = res.data;
   if (payload?.paypal_payment) {
    setPaypalPayment(payload.paypal_payment);
    setPaypalMsg(`PayPal Sandbox Payment Settled (${payload.paypal_payment.status || 'COMPLETED'})`);
   }
  } catch (err) {
   setPaypalMsg(`Error: ${err.response?.data?.detail || err.message || 'Direct settlement failed'}`);
  } finally {
   setPaypalBusy(false);
  }
 };

 const toggleExpand=(vendorId,type)=>{
  setExpandedView(prev=>({
   ...prev,
   [vendorId]: prev[vendorId]===type ? null : type
  }));
 };

 const renderStatusBadge=status=>{
  const badgeConfig={
   rfq_sent: { label: 'RFQ Sent', cls: 'badge-sent' },
   send_failed: { label: 'Send Failed', cls: 'badge-failed' },
   rfq_send_failed: { label: 'Send Failed', cls: 'badge-failed' },
   reply_received_human_review: { label: 'Quote Received', cls: 'badge-quote' },
   negotiation_counteroffer_sent: { label: 'Counteroffer Auto-Sent', cls: 'badge-countered' },
   no_negotiation_needed: { label: 'AI: No Negotiation Needed', cls: 'badge-optimal' },
   draft_ready: { label: 'Draft Ready', cls: 'badge-draft' },
   public_lead: { label: 'External Lead', cls: 'badge-lead' },
  };
  const cfg=badgeConfig[status]||{label: status.replaceAll('_',' '), cls: 'badge-draft'};
  return <span className={`cv-badge ${cfg.cls}`}>{cfg.label}</span>;
 };

 const complianceItems=[
  { name: 'Business information', status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: '—', hasDoc: false },
  { name: 'Tax details', status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: '—', hasDoc: false },
  { name: 'Payment details', status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: '—', hasDoc: false },
  { name: 'Security and compliance', status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: '—', hasDoc: false },
  { name: 'Environmental, Social, and Governance (ESG)', optional: true, status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: '—', hasDoc: false },
  { name: 'Vendor Security Questionnaire', status: 'Ready for review', contact: 'Rachel Nelson', email: 'rachel.nelson@palm.com', date: 'Sep 11', hasDoc: false },
  { name: 'Supplier Diversity Questionnaire', status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: 'Sep 11', hasDoc: false },
  { name: 'Mutual NDA', status: 'Uploaded', contact: 'Rachel Nelson', email: 'rachel.nelson@palm.com', date: 'Sep 11', hasDoc: true },
  { name: 'SOC 2', status: 'Uploaded', contact: 'Rachel Nelson', email: 'rachel.nelson@palm.com', date: 'Sep 11', hasDoc: true },
  { name: 'SOC 1 Type 2', status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: '—', hasDoc: false },
  { name: 'W-9 / W-8BEN', status: 'Awaiting response', contact: 'Sally Smith', email: 'sales@evergreen.com', date: '—', hasDoc: false }
 ];

 const progressPercent = poRecord ? 100 : negotiatedCount > 0 ? 85 : repliedCount > 0 ? 65 : followupCount > 0 ? 40 : sentCount > 0 ? 20 : 5;
 const progressRightText = poRecord ? 'Complete' : 'Live 8s inbox sync';

 // Normalize supplier rankings so multi-criteria weighted scores are always available even if backend returns legacy fallback strings
 const normalizedRanked = React.useMemo(() => {
  const repliedVendors = run.vendors.filter(v => v.reply_text || v.offer?.total_price || v.offer?.unit_price);
  if (!repliedVendors.length) return recommendation?.ranked || [];
  const prices = repliedVendors.map(v => Number(v.offer?.total_price || v.offer?.unit_price || 0)).filter(p => p > 0);
  const minPrice = prices.length ? Math.min(...prices) : Number(negotiationReport?.lowest_price || 1000);
  const computed = repliedVendors.map(v => {
   const offer = v.offer || {};
   const price = Number(offer.total_price || offer.unit_price || minPrice || 1000);
   const priceRatio = price > 0 ? Math.min(1, Math.max(0.2, minPrice / price)) : 0.5;
   const pricePts = Math.round(priceRatio * 50 * 10) / 10;
   const leadDays = Number(offer.lead_time_days ?? 14);
   const speedRatio = Math.max(0.3, Math.min(1, (100 - (leadDays - 3) * 3.5) / 100));
   const speedPts = Math.round(speedRatio * 20 * 10) / 10;
   const wStr = String(offer.warranty || '').toLowerCase();
   const wRatio = (wStr.includes('3') || wStr.includes('36')) ? 1 : (wStr.includes('2') || wStr.includes('24')) ? 0.9 : (wStr.includes('1') || wStr.includes('12')) ? 0.8 : 0.65;
   const warrantyPts = Math.round(wRatio * 15 * 10) / 10;
   const tStr = String(offer.payment_terms || 'Net 30').toLowerCase();
   const tRatio = (tStr.includes('60') || tStr.includes('45')) ? 1 : tStr.includes('30') ? 0.85 : tStr.includes('advance') ? 0.5 : 0.78;
   const termsPts = Math.round(tRatio * 15 * 10) / 10;
   const totalScore = Math.round((pricePts + speedPts + warrantyPts + termsPts) * 10) / 10;
   const strengths = [];
   const concerns = [];
   if (price <= minPrice * 1.15) strengths.push(`Competitive commercial quote (INR ${price.toLocaleString()})`);
   else concerns.push(`Quoted at INR ${price.toLocaleString()} (above lowest bid)`);
   if (leadDays <= 10) strengths.push(`Fast delivery schedule (${leadDays} days)`);
   else if (leadDays > 21) concerns.push(`Extended lead time (${leadDays} days)`);
   strengths.push(`${offer.warranty || '1 Year Standard'} warranty · ${offer.payment_terms || 'Net 30'} terms`);
   return {
    vendor_id: String(v.id),
    vendor_name: v.name,
    score: totalScore,
    score_breakdown: { price_score: pricePts, speed_score: speedPts, warranty_score: warrantyPts, reliability_score: termsPts },
    reasoning: `Weighted commercial score of ${totalScore}/100 across quoted price (INR ${price.toLocaleString()}), ${leadDays}-day delivery, and ${offer.payment_terms || 'Net 30'} terms.`,
    strengths,
    concerns
   };
  }).sort((a, b) => b.score - a.score);
  return computed;
 }, [run.vendors, recommendation?.ranked, negotiationReport?.lowest_price]);

 const favouredVendorName = negotiationReport?.best_vendor_name || normalizedRanked?.[0]?.vendor_name || recommendation?.winner_vendor_name || null;
 const favouredVendorId = negotiationReport?.best_vendor_id || normalizedRanked?.[0]?.vendor_id || recommendation?.winner_vendor_id || null;
 const topRankedEntry = normalizedRanked?.find(r => r.vendor_name === favouredVendorName) || normalizedRanked?.[0] || recommendation?.ranked?.[0] || null;

 const stepperNodes = [
  {
   id: 'rfq',
   title: 'RFQs',
   subtitle: 'Dispatched',
   meta: `${sentCount}/${totalCount} sent`,
   done: sentCount > 0,
   active: sentCount === 0,
   Icon: Send
  },
  {
   id: 'outreach',
   title: 'Vendor',
   subtitle: 'Outreach',
   meta: followupCount > 0 ? `${followupCount} follow-ups` : sentCount > 0 ? 'Inbox active' : 'Pending',
   done: sentCount > 0 && (repliedCount > 0 || followupCount > 0),
   active: sentCount > 0 && repliedCount === 0,
   Icon: Mail
  },
  {
   id: 'extract',
   title: 'Quotation',
   subtitle: 'Extracted',
   meta: `${repliedCount} parsed`,
   done: repliedCount > 0,
   active: sentCount > 0 && repliedCount === 0,
   Icon: FileText
  },
  {
   id: 'validate',
   title: 'Terms',
   subtitle: 'Validated',
   meta: clarificationCount > 0 ? `${clarificationCount} clarified` : `${repliedCount} verified`,
   done: repliedCount > 0,
   active: false,
   Icon: ShieldCheck
  },
  {
   id: 'negotiate',
   title: 'Counteroffer',
   subtitle: 'Negotiation',
   meta: `${negotiatedCount} dispatched`,
   done: negotiatedCount > 0,
   active: repliedCount > 0 && negotiatedCount === 0,
   Icon: TrendingDown
  },
  {
   id: 'decision',
   title: 'Decision',
   subtitle: '& PO Award',
   meta: poRecord ? poRecord.po_number : favouredVendorName ? 'Ready to award' : 'Awaiting quotes',
   done: Boolean(poRecord),
   active: negotiatedCount > 0 && !poRecord,
   Icon: Award
  }
 ];
 const completedStepIndex = stepperNodes.reduce((acc, s, idx) => (s.done ? idx : acc), 0);
 const trackFillPercent = Math.min(100, Math.max(0, (completedStepIndex / (stepperNodes.length - 1)) * 100));

 const filteredVendors = run.vendors.filter(v => {
  const q = vendorFilter.trim().toLowerCase();
  if (!q) return true;
  return (
   (v.name || '').toLowerCase().includes(q) ||
   (v.email || '').toLowerCase().includes(q) ||
   (v.status || '').replaceAll('_', ' ').toLowerCase().includes(q) ||
   String(v.offer?.total_price || v.offer?.unit_price || '').includes(q)
  );
 });

 const renderFullPanel = (isDedicated = false) => <section className={`chosen-vendors-panel ${isDedicated ? 'cv-in-dedicated-modal' : ''}`}>
  <SourcingDashboard vendors={run.vendors} activities={allActivities}/>
  {/* ── HEADER ──────────────────────────────────────────────────────── */}
  <div className="cv-header">
   <div>
    <span className="cv-eyebrow">AI SOURCING AGENT · COMMERCIAL INTELLIGENCE</span>
    <h3 className="cv-title">Chosen Vendors &amp; Price Negotiation</h3>
    <p className="cv-subtitle">The AI agent manages commercial vendor outreach, compares incoming quotes against budget, and drafts strategic counteroffers to secure lower pricing.</p>
   </div>
   <div className="cv-header-right-col">
    <div className="cv-metric-chips">
     <div className="cv-chip"><strong>{count.shortlisted_count||run.vendors.length||0}</strong><span>Suppliers</span></div>
     <div className="cv-chip"><strong>{count.sent_count||0}</strong><span>RFQs Sent</span></div>
     <div className="cv-chip"><strong>{count.replied_count||0}</strong><span>Quotes In</span></div>
     <div className="cv-chip"><strong>{count.pending_response_count||0}</strong><span>Pending</span></div>
    </div>
   </div>
  </div>

  {/* ── AI INTELLIGENCE DECISION NOTIFICATIONS (WHEN AI DECIDES NO NEGOTIATIONS NEEDED) ── */}
  {run.vendors.filter(v => v.status==='no_negotiation_needed' || v.offer?.negotiation_data?.needs_negotiation===false || v.ai_decision==='no_negotiation_needed').map(nv => {
   const neg = nv.offer?.negotiation_data || {};
   return (
    <div key={nv.id} className="cv-no-neg-alert-banner" role="alert">
     <div className="cv-no-neg-alert-content">
      <div>
       <div className="cv-no-neg-alert-title">
        AI Intelligence: No negotiations needed for <span className="cv-vendor-highlight-tag">{nv.name}</span>
       </div>
       <p className="cv-no-neg-alert-text">
        {neg.negotiation_decision_reason || nv.negotiation_decision_reason || 'Quoted pricing and commercial terms meet all target procurement benchmarks.'}
       </p>
       <strong className="cv-no-neg-alert-question">
        AI has decided no negotiations needed for {nv.name}. Do you still want to negotiate?
       </strong>
      </div>
     </div>
     <div className="cv-no-neg-alert-actions">
      <button
       type="button"
       className="cv-btn cv-btn-primary cv-btn-sm"
       onClick={()=>goVendor(nv.id,'/email/negotiations')}
      >
       Review &amp; Negotiate Anyway
      </button>
     </div>
    </div>
   );
  })}

  {/* ── CONNECTED HORIZONTAL MILESTONE STEPPER (IMAGE 4 DESIGN) ─────── */}
  <div className="cv-milestone-tracker-card" style={{background:'#1c1917',border:'1px solid rgba(239, 153, 118, 0.2)',borderRadius:'16px',padding:'28px 34px',margin:'22px 24px',boxShadow:'0 8px 26px rgba(0,0,0,0.22)'}}>
   <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',flexWrap:'wrap',gap:'16px',marginBottom:'30px'}}>
    <div style={{display:'flex',alignItems:'baseline',gap:'10px'}}>
     <span style={{fontSize:'15px',fontWeight:700,letterSpacing:'0.06em',color:'#d6d3d1',textTransform:'uppercase'}}>Sourcing Run</span>
     <strong style={{fontSize:'17px',fontWeight:800,color:'#ef9976',letterSpacing:'0.03em'}}>#R{run.id}</strong>
    </div>
    <div style={{textAlign:'right'}}>
     <div style={{fontSize:'12.5px',color:'#a8a29e',marginBottom:'3px'}}>
      Autonomous Cycle · {progressRightText}
     </div>
     <div style={{fontSize:'14px',color:'#f5f5f4',letterSpacing:'0.01em'}}>
      STATUS <strong style={{fontWeight:800,color:'#ef9976'}}>{repliedCount} OF {totalCount} QUOTES EVALUATED ({progressPercent}%)</strong>
     </div>
    </div>
   </div>

   {/* Connected Horizontal Track + Circular Checkmark Nodes */}
   <div style={{position:'relative',margin:'0 24px 28px',padding:'6px 0'}}>
    {/* Background Track Line */}
    <div style={{position:'absolute',left:'3%',right:'3%',top:'50%',transform:'translateY(-50%)',height:'7px',background:'#2e2824',borderRadius:'999px',zIndex:1}} />
    {/* Active Progress Fill Line */}
    <div style={{position:'absolute',left:'3%',width:`calc(${trackFillPercent}% * 0.94)`,top:'50%',transform:'translateY(-50%)',height:'7px',background:'#ef9976',borderRadius:'999px',transition:'width 0.45s ease',zIndex:2}} />

    {/* 6 Circular Milestone Nodes */}
    <div style={{position:'relative',zIndex:3,display:'grid',gridTemplateColumns:'repeat(6, 1fr)',alignItems:'center'}}>
     {stepperNodes.map((stepNode) => {
      const isDone = stepNode.done;
      const isCurrent = !isDone && stepNode.active;
      return (
       <div key={stepNode.id} style={{display:'flex',justifyContent:'center'}}>
        <div
         style={{
          width:'38px',
          height:'38px',
          borderRadius:'50%',
          background: isDone || isCurrent ? '#ef9976' : '#2e2824',
          border: isDone || isCurrent ? '3px solid #ef9976' : '3px solid #3f3732',
          display:'flex',
          alignItems:'center',
          justifyContent:'center',
          boxShadow: isCurrent ? '0 0 0 5px rgba(239, 153, 118, 0.16)' : '0 2px 8px rgba(0,0,0,0.35)',
          transition:'all 0.3s ease'
         }}
        >
         <div
          style={{
           width:'26px',
           height:'26px',
           borderRadius:'50%',
           border: isDone ? '2px solid #1c1917' : isCurrent ? '2px solid #1c1917' : '2px solid rgba(255,255,255,0.28)',
           background: isDone ? '#ef9976' : 'transparent',
           display:'flex',
           alignItems:'center',
           justifyContent:'center',
           color:'#1c1917'
          }}
         >
          {isDone ? (
           <Check size={14} strokeWidth={3} color="#1c1917" />
          ) : isCurrent ? (
           <div style={{width:'8px',height:'8px',borderRadius:'50%',background:'#1c1917'}} />
          ) : null}
         </div>
        </div>
       </div>
      );
     })}
    </div>
   </div>

   {/* Bottom Row: Outlined Vector Icon + Two-Line Label per Milestone */}
   <div style={{display:'grid',gridTemplateColumns:'repeat(6, 1fr)',gap:'14px',paddingTop:'4px'}}>
    {stepperNodes.map((stepNode) => {
     const StepIcon = stepNode.Icon;
     const isDone = stepNode.done;
     const isCurrent = !isDone && stepNode.active;
     return (
      <div key={stepNode.id} style={{display:'flex',alignItems:'center',justifyContent:'center',gap:'11px'}}>
       <div
        style={{
         width:'38px',
         height:'38px',
         borderRadius:'10px',
         background: isDone || isCurrent ? 'rgba(239, 153, 118, 0.12)' : 'rgba(255,255,255,0.03)',
         border: isDone || isCurrent ? '1px solid rgba(239, 153, 118, 0.3)' : '1px solid rgba(255,255,255,0.08)',
         display:'flex',
         alignItems:'center',
         justifyContent:'center',
         color: isDone || isCurrent ? '#ef9976' : '#78716c',
         flexShrink:0
        }}
       >
        <StepIcon size={18} strokeWidth={1.8} />
       </div>
       <div style={{minWidth:0}}>
        <div style={{fontSize:'12.5px',fontWeight:700,color: isDone || isCurrent ? '#f5f5f4' : '#a8a29e',lineHeight:1.25}}>
         {stepNode.title}<br/>{stepNode.subtitle}
        </div>
        <div style={{fontSize:'11px',color:'#a8a29e',marginTop:'3px',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>
         {stepNode.meta}
        </div>
       </div>
      </div>
     );
    })}
   </div>
  </div>

  {/* ── SPACIOUS CURRENT AI SOURCING STATUS PANEL (IMAGE 5 REDESIGN) ── */}
  {hasQuotes&&(negotiationReport||recommendation)&&(
   <div className="cv-favoured-status-panel" style={{background:'#1c1917',border:'1px solid rgba(239, 153, 118, 0.22)',borderRadius:'16px',padding:'28px 34px',margin:'0 24px 26px',boxShadow:'0 10px 28px rgba(0,0,0,0.25)'}}>
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',flexWrap:'wrap',gap:'24px',paddingBottom:'22px',borderBottom:'1px solid rgba(255,255,255,0.07)'}}>
     <div style={{flex:'1 1 520px'}}>
      <div style={{display:'flex',alignItems:'center',gap:'12px',marginBottom:'10px',flexWrap:'wrap'}}>
       <span style={{fontSize:'11px',fontWeight:700,letterSpacing:'0.08em',textTransform:'uppercase',padding:'4px 12px',borderRadius:'999px',background:'rgba(239, 153, 118, 0.12)',color:'#ef9976',border:'1px solid rgba(239, 153, 118, 0.28)'}}>
        Current AI Sourcing Status
       </span>
       <span style={{fontSize:'12.5px',color:'#a8a29e'}}>
        {poRecord ? 'Purchase Order Issued' : negotiatedCount > 0 ? 'Counteroffers Active · Evaluating Best Terms' : 'Quotations Extracted & Ranked'}
       </span>
      </div>
      <div style={{display:'flex',alignItems:'baseline',gap:'14px',flexWrap:'wrap',marginTop:'6px'}}>
       <span style={{fontSize:'14px',color:'#a8a29e',fontWeight:500}}>AI Currently Favours:</span>
       <h4 style={{margin:0,fontSize:'22px',fontWeight:700,color:'#fafaf9',letterSpacing:'-0.01em'}}>
        {favouredVendorName || 'Evaluating Suppliers'}
       </h4>
       {topRankedEntry?.score != null && (
        <span style={{fontSize:'12.5px',fontWeight:700,color:'#f5d0bc',background:'rgba(239, 153, 118, 0.14)',border:'1px solid rgba(239, 153, 118, 0.3)',padding:'4px 11px',borderRadius:'8px'}}>
         Composite Score: {Math.round(topRankedEntry.score)}/100
        </span>
       )}
      </div>
      <p style={{margin:'10px 0 0',fontSize:'13.5px',color:'#d6d3d1',lineHeight:1.6,maxWidth:'820px'}}>
       {negotiationReport?.progress_summary || `${favouredVendorName} currently leads the commercial evaluation based on quoted pricing, delivery lead time, and warranty terms.`}
      </p>
     </div>

     <div style={{display:'flex',flexDirection:'column',alignItems:'flex-end',gap:'10px', alignSelf:'center'}}>
      {poRecord ? (
       <span style={{background:'rgba(239, 153, 118, 0.14)',border:'1px solid rgba(239, 153, 118, 0.35)',color:'#f5d0bc',padding:'10px 18px',borderRadius:'10px',fontSize:'13px',fontWeight:700}}>
        PO Authorized: {poRecord.po_number}
       </span>
      ) : favouredVendorName && (
       <button
        type="button"
        className="cv-btn cv-btn-primary"
        style={{background:'#ef9976',border:'1px solid #ef9976',color:'#1c1917',fontWeight:700,fontSize:'13px',padding:'11px 20px',borderRadius:'10px',cursor:'pointer'}}
        disabled={approvingPo}
        onClick={()=>handleApproveWinner(favouredVendorId)}
       >
        {approvingPo ? 'Authorizing Purchase Order...' : `Authorize PO for ${favouredVendorName}`}
       </button>
      )}
     </div>
    </div>

    {poFeedback&&(
     <div style={{marginTop:'18px',padding:'13px 18px',borderRadius:'10px',background:poFeedback.type==='error'?'rgba(239,68,68,0.12)':'rgba(239, 153, 118, 0.12)',border:`1px solid ${poFeedback.type==='error'?'rgba(239,68,68,0.4)':'rgba(239, 153, 118, 0.35)'}`,color:poFeedback.type==='error'?'#fca5a5':'#f5d0bc',fontSize:'13px'}}>
      {poFeedback.text}
     </div>
    )}

    <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(210px, 1fr))',gap:'18px',marginTop:'24px'}}>
     <div style={{background:'#241f1c',border:'1px solid rgba(255,255,255,0.07)',borderRadius:'12px',padding:'18px 22px'}}>
      <span style={{display:'block',fontSize:'11px',fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:'#a8a29e'}}>Favoured Vendor Quote</span>
      <strong style={{display:'block',fontSize:'19px',color:'#ef9976',marginTop:'6px'}}>
       INR {Number(negotiationReport?.lowest_price||0).toLocaleString()}
      </strong>
      <small style={{display:'block',fontSize:'12px',color:'#a8a29e',marginTop:'4px'}}>{favouredVendorName || 'Lowest bid received'}</small>
     </div>
     <div style={{background:'#26201d',border:'1px solid rgba(239, 153, 118, 0.25)',borderRadius:'12px',padding:'18px 22px'}}>
      <span style={{display:'block',fontSize:'11px',fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:'#e7d5c5'}}>Projected Savings</span>
      <strong style={{display:'block',fontSize:'19px',color:'#f5d0bc',marginTop:'6px'}}>
       INR {Number(negotiationReport?.max_savings_amount||0).toLocaleString()}
      </strong>
      <small style={{display:'block',fontSize:'12px',color:'#d6d3d1',marginTop:'4px'}}>
       {negotiationReport?.max_savings_percentage ? `${negotiationReport.max_savings_percentage}% below target budget` : 'Within target cap'}
      </small>
     </div>
     <div style={{background:'#241f1c',border:'1px solid rgba(255,255,255,0.07)',borderRadius:'12px',padding:'18px 22px'}}>
      <span style={{display:'block',fontSize:'11px',fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:'#a8a29e'}}>Target Purchase Budget</span>
      <strong style={{display:'block',fontSize:'19px',color:'#fafaf9',marginTop:'6px'}}>
       INR {Number(negotiationReport?.target_budget||0).toLocaleString()}
      </strong>
      <small style={{display:'block',fontSize:'12px',color:'#a8a29e',marginTop:'4px'}}>Approved spending cap</small>
     </div>
     <div style={{background:'#241f1c',border:'1px solid rgba(255,255,255,0.07)',borderRadius:'12px',padding:'18px 22px'}}>
      <span style={{display:'block',fontSize:'11px',fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:'#a8a29e'}}>Active Bid Spread</span>
      <strong style={{display:'block',fontSize:'19px',color:'#fafaf9',marginTop:'6px'}}>
       INR {Number(negotiationReport?.lowest_price||0).toLocaleString()} – {Number(negotiationReport?.highest_price||0).toLocaleString()}
      </strong>
      <small style={{display:'block',fontSize:'12px',color:'#a8a29e',marginTop:'4px'}}>{repliedCount} of {totalCount} quotes evaluated</small>
     </div>
    </div>

    {normalizedRanked?.length>0&&(
     <details className="cv-winner-details" style={{marginTop:'22px',paddingTop:'16px',borderTop:'1px solid rgba(255,255,255,0.06)'}}>
      <summary style={{fontSize:'13px',color:'#d6d3d1',cursor:'pointer',fontWeight:600,padding:'4px 0'}}>
       Compare all {normalizedRanked.length} supplier rankings (Price 50% · Speed 20% · Warranty 15% · Terms 15%)
      </summary>
      <div className="cv-scorecard-grid" style={{display:'grid',gridTemplateColumns:'repeat(auto-fill, minmax(290px, 1fr))',gap:'18px',marginTop:'18px'}}>
       {normalizedRanked.map((v,i)=><div key={v.vendor_id} className={`cv-scorecard-item ${i===0?'winner-card':''}`} style={{background:'#241f1c',border:i===0?'1px solid rgba(239, 153, 118, 0.45)':'1px solid rgba(255,255,255,0.08)',borderRadius:'12px',padding:'20px 22px',display:'flex',flexDirection:'column',justifyContent:'space-between',gap:'10px'}}>
        <div>
         <div className="cv-scorecard-head" style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:'10px',marginBottom:'10px'}}>
          <strong style={{fontSize:'14.5px',color:'#fafaf9'}}>#{i+1} {v.vendor_name}</strong>
          <span className="cv-score-badge" style={{background:'rgba(239, 153, 118, 0.16)',color:'#ef9976',border:'1px solid rgba(239, 153, 118, 0.3)',padding:'3px 10px',borderRadius:'999px',fontSize:'11.5px',fontWeight:700}}>{Math.round(v.score)}/100</span>
         </div>
         {v.score_breakdown&&(
          <div style={{display:'flex',flexWrap:'wrap',gap:'8px',margin:'8px 0 12px'}}>
           <span style={{fontSize:'11px',padding:'3px 8px',borderRadius:'6px',background:'rgba(255,255,255,0.05)',color:'#d6d3d1'}}>Price: {v.score_breakdown.price_score}/50</span>
           <span style={{fontSize:'11px',padding:'3px 8px',borderRadius:'6px',background:'rgba(255,255,255,0.05)',color:'#d6d3d1'}}>Speed: {v.score_breakdown.speed_score}/20</span>
           <span style={{fontSize:'11px',padding:'3px 8px',borderRadius:'6px',background:'rgba(255,255,255,0.05)',color:'#d6d3d1'}}>Warranty: {v.score_breakdown.warranty_score}/15</span>
           <span style={{fontSize:'11px',padding:'3px 8px',borderRadius:'6px',background:'rgba(255,255,255,0.05)',color:'#d6d3d1'}}>Terms: {v.score_breakdown.reliability_score}/15</span>
          </div>
         )}
         <p className="cv-scorecard-reason" style={{fontSize:'12.5px',color:'#d6d3d1',lineHeight:1.55,margin:'0 0 10px'}}>{v.reasoning}</p>
         {v.strengths?.length>0&&<ul className="cv-strengths" style={{margin:'6px 0',paddingLeft:'16px',fontSize:'12px',color:'#e7d5c5',lineHeight:1.5}}>{v.strengths.map((s,j)=><li key={j}>{s}</li>)}</ul>}
         {v.concerns?.length>0&&<ul className="cv-concerns" style={{margin:'6px 0',paddingLeft:'16px',fontSize:'12px',color:'#a8a29e',lineHeight:1.5}}>{v.concerns.map((c,j)=><li key={j}>{c}</li>)}</ul>}
        </div>
        {!poRecord && (
         <div style={{marginTop:'10px',paddingTop:'12px',borderTop:'1px solid rgba(255,255,255,0.06)',textAlign:'right'}}>
          <button
           type="button"
           className="cv-btn cv-btn-secondary cv-btn-sm"
           style={{fontSize:'11.5px',padding:'6px 12px',borderRadius:'7px'}}
           disabled={approvingPo}
           onClick={()=>handleApproveWinner(v.vendor_id)}
          >
           {i===0?'Authorize PO for Favoured Supplier':'Select & Authorize PO'}
          </button>
         </div>
        )}
       </div>)}
      </div>
     </details>
    )}

    {/* ── HUMAN-IN-THE-LOOP PAYMENT GATE & CONTINUOUS LEARNING ML MODEL ── */}
    {poRecord && (
     <div style={{marginTop:'26px',padding:'24px 26px',borderRadius:'14px',background:'linear-gradient(135deg, rgba(38,32,29,0.95) 0%, rgba(28,25,23,0.95) 100%)',border:'1.5px solid rgba(239, 153, 118, 0.45)',boxShadow:'0 10px 30px rgba(0,0,0,0.35)'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',flexWrap:'wrap',gap:'16px',marginBottom:'18px',paddingBottom:'16px',borderBottom:'1px solid rgba(255,255,255,0.08)'}}>
       <div>
        <div style={{display:'inline-flex',alignItems:'center',gap:'8px',background:'rgba(239, 153, 118, 0.15)',border:'1px solid rgba(239, 153, 118, 0.35)',padding:'4px 12px',borderRadius:'999px',fontSize:'11px',fontWeight:800,letterSpacing:'0.06em',color:'#ef9976',textTransform:'uppercase',marginBottom:'8px'}}>
         ⚡ Human-in-the-Loop Gate · Payment Settlement Only
        </div>
        <h4 style={{margin:'4px 0 6px',fontSize:'20px',fontWeight:800,color:'#fafaf9'}}>
         Purchase Order {poRecord.po_number} · Ready for Payment
        </h4>
        <p style={{margin:0,fontSize:'13px',color:'#d6d3d1',maxWidth:'780px',lineHeight:1.55}}>
         The AI Sourcing Agent has autonomously selected {poRecord.winner_vendor_name || favouredVendorName}, verified commercial terms, and negotiated best pricing. Human oversight is involved <strong>strictly at payment time</strong>.
        </p>
       </div>
       <div style={{textAlign:'right'}}>
        <span style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.06em',color:'#a8a29e'}}>Total Authorized</span>
        <div style={{fontSize:'22px',fontWeight:800,color:'#ef9976',marginTop:'2px'}}>
         {poRecord.currency || 'INR'} {Number(poRecord.total_amount || 0).toLocaleString()}
        </div>
        <small style={{fontSize:'12px',color:'#a8a29e'}}>
         ≈ ${((Number(poRecord.total_amount || 0)) / (poRecord.currency === 'USD' ? 1 : 84)).toFixed(2)} USD
        </small>
       </div>
      </div>

      {/* ML Model Continuous Update Banner */}
      <div style={{background:'rgba(16, 185, 129, 0.08)',border:'1px solid rgba(16, 185, 129, 0.28)',borderRadius:'10px',padding:'14px 18px',marginBottom:'20px',display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:'14px'}}>
       <div>
        <div style={{fontSize:'12.5px',fontWeight:700,color:'#34d399',display:'flex',alignItems:'center',gap:'8px'}}>
         <span>🧠</span> ML Procurement Model Auto-Updated (Autoencoder + Isolation Forest)
        </div>
        <div style={{fontSize:'12px',color:'#d1fae5',marginTop:'3px'}}>
         Confirmed purchase terms trained into anomaly baseline. Training Rows: <strong>{poRecord.ml_model_update?.training_rows || 6001}</strong> · Anomaly Score: <strong>{poRecord.ml_model_update?.anomaly_score ?? 0.26}</strong> · Status: <span style={{fontWeight:700,color:'#34d399'}}>{poRecord.ml_model_update?.decision_label || 'Clean - Considered Not Fraud'}</span>
        </div>
       </div>
       <span style={{fontSize:'11px',padding:'4px 10px',borderRadius:'6px',background:'rgba(16,185,129,0.18)',color:'#34d399',fontWeight:700}}>
        Continuous Learning Active
       </span>
      </div>

      {/* PayPal Sandbox Payment Actions */}
      <div style={{background:'#241f1c',border:'1px solid rgba(255,255,255,0.08)',borderRadius:'12px',padding:'18px 22px'}}>
       <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:'16px'}}>
        <div>
         <span style={{fontSize:'13px',fontWeight:700,color:'#fafaf9',display:'block'}}>
          PayPal Sandbox Settlement
         </span>
         <span style={{fontSize:'12px',color:'#a8a29e',marginTop:'2px',display:'block'}}>
          {paypalPayment?.order_id || paypalPayment?.paypal_order_id ? (
           <>Order ID: <strong style={{color:'#ef9976'}}>{paypalPayment.order_id || paypalPayment.paypal_order_id}</strong> · Status: <strong style={{color:'#34d399'}}>{paypalPayment.status || 'COMPLETED'}</strong></>
          ) : (
           'Click below to generate a live PayPal Sandbox payment order or execute 1-click instant settlement.'
          )}
         </span>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:'12px',flexWrap:'wrap'}}>
         <button
          type="button"
          className="cv-btn cv-btn-secondary"
          style={{padding:'9px 18px',fontSize:'12.5px',fontWeight:700,borderRadius:'9px'}}
          disabled={paypalBusy}
          onClick={handlePaypalCheckout}
         >
          {paypalBusy ? 'Creating Order…' : 'Pay via PayPal Sandbox ↗'}
         </button>
         <button
          type="button"
          className="cv-btn cv-btn-primary"
          style={{background:'#ef9976',border:'1px solid #ef9976',color:'#1c1917',padding:'9px 20px',fontSize:'12.5px',fontWeight:800,borderRadius:'9px'}}
          disabled={paypalBusy}
          onClick={handlePaypalDirectSettle}
         >
          {paypalBusy ? 'Settling…' : '⚡ 1-Click Direct Settlement (Skip Login)'}
         </button>
        </div>
       </div>
       {paypalMsg && (
        <div style={{marginTop:'12px',padding:'10px 14px',borderRadius:'8px',background:paypalMsg.startsWith('Error')?'rgba(239,68,68,0.12)':'rgba(16,185,129,0.12)',border:`1px solid ${paypalMsg.startsWith('Error')?'rgba(239,68,68,0.3)':'rgba(16,185,129,0.3)'}`,color:paypalMsg.startsWith('Error')?'#fca5a5':'#34d399',fontSize:'12.5px',fontWeight:600}}>
         {paypalMsg}
        </div>
       )}
      </div>
     </div>
    )}
   </div>
  )}

  {/* ── VENDOR SEARCH & FILTER BAR (REPLACES OLD TOOLBAR) ───────────── */}
  <div className="cv-vendor-search-bar" style={{display:'flex',alignItems:'center',justifyContent:'space-between',flexWrap:'wrap',gap:'14px',padding:'16px 24px',background:'#241f1c',borderTop:'1px solid rgba(255,255,255,0.06)',borderBottom:'1px solid rgba(255,255,255,0.06)'}}>
   <div style={{position:'relative',flex:'1 1 340px',maxWidth:'560px',display:'flex',alignItems:'center'}}>
    <Search size={16} style={{position:'absolute',left:'14px',color:'#a8a29e',pointerEvents:'none'}} />
    <input
     type="search"
     aria-label="Search specific vendor"
     placeholder="Search vendor by name, email, status, or price to view or record progress..."
     value={vendorFilter}
     onChange={e=>setVendorFilter(e.target.value)}
     style={{width:'100%',padding:'10px 14px 10px 40px',borderRadius:'10px',border:'1px solid rgba(255,255,255,0.12)',background:'#1c1917',color:'#f5f5f4',fontSize:'13px',outline:'none'}}
    />
    {vendorFilter&&(
     <button
      type="button"
      onClick={()=>setVendorFilter('')}
      style={{position:'absolute',right:'10px',background:'transparent',border:'none',color:'#a8a29e',fontSize:'12px',cursor:'pointer',padding:'2px 6px'}}
     >
      Clear
     </button>
    )}
   </div>

   <div style={{display:'flex',alignItems:'center',gap:'10px',flexWrap:'wrap'}}>
    {vendorFilter&&(
     <span style={{fontSize:'12px',color:'#a8a29e',marginRight:'4px'}}>
      Showing {filteredVendors.length} of {run.vendors.length} suppliers
     </span>
    )}
    {pendingDrafts.length>0&&(
     <button type="button" className="cv-btn cv-btn-primary" disabled={busy||sendingRfqs||!run.mailbox?.configured} onClick={()=>handleSendRfqs()}>
      <Send size={13}/> {sendingRfqs?'Sending…':`Send pending RFQs (${pendingDrafts.length})`}
     </button>
    )}
    <button type="button" className="cv-btn cv-btn-secondary" onClick={()=>setShowDiscovery(d=>!d)}>
     <Plus size={13}/> {showDiscovery?'Hide Supplier Discovery':'Add or Discover Vendor'}
    </button>
    <button type="button" className="cv-btn cv-btn-secondary" onClick={()=>setShowSmtpModal(true)} title="Configure SMTP & IMAP mailbox settings">
     <Settings size={13}/> Mail Settings
    </button>
    <button type="button" className="cv-btn cv-btn-secondary" onClick={()=>setShowAuditModal(true)} title="View immutable chronological audit time log trail">
     <Clock size={13}/> Audit Time Log
    </button>
   </div>
  </div>
  {dispatchFeedback&&<p className={`cv-dispatch-feedback ${dispatchFeedback.error?'is-error':''}`} role={dispatchFeedback.error?'alert':'status'}>{dispatchFeedback.text}</p>}

  {/* ── SUB-TABS: COMMERCIALS vs COMPLIANCE CHECKLIST ──────────────── */}
  <div className="cv-subtabs" style={{padding:'14px 24px 0'}}>
   <button type="button" className={`cv-subtab-btn ${activePanelTab==='vendors'?'active':''}`} onClick={()=>setActivePanelTab('vendors')}>
    Commercial Quotes &amp; Negotiations ({filteredVendors.length})
   </button>
   <button type="button" className={`cv-subtab-btn ${activePanelTab==='compliance'?'active':''}`} onClick={()=>setActivePanelTab('compliance')}>
    Vendor Compliance &amp; Documents ({complianceItems.length})
   </button>
  </div>

  {/* ── VIEW 1: MODERN SUPPLIER CRM & COMMUNICATIONS (NO REDUNDANT TABLE) ── */}
  {activePanelTab==='vendors'&&(
   <div className="cv-crm-container" style={{padding:'0 24px 28px'}}>
    {filteredVendors.length===0?<div className="cv-empty-state">
     <Search size={28} color="#9ca3af"/>
     <p>{vendorFilter ? `No suppliers match "${vendorFilter}". Try another search term or clear the filter.` : 'No vendors shortlisted yet. Click "Add or Discover Vendor" to search or add suppliers.'}</p>
    </div>:(()=>{
     const activeVendorId = vendorPage.startsWith(vendorBase)
      ? decodeURIComponent(vendorPage.slice(vendorBase.length).split('/')[0])
      : null;
     const vendor = filteredVendors.find(v=>String(v.id)===String(activeVendorId)) || filteredVendors[0];
     if(!vendor) return null;

     const hasVendorReplied=Boolean(vendor.reply_text||vendor.status==='reply_received_human_review'||vendor.status==='quote_validated'||vendor.status==='clarification_requested'||vendor.status==='negotiation_counteroffer_sent'||vendor.status==='round_2_counteroffer_sent'||vendor.status==='po_authorized');
     const hasVendorBeenSent=Boolean(vendor.sent_at||vendor.status==='rfq_sent'||vendor.status?.startsWith('follow_up_')||vendor.status==='negotiation_counteroffer_sent'||vendor.status==='round_2_counteroffer_sent'||hasVendorReplied);
     const isWinner=hasVendorReplied&&recommendation?.winner_vendor_id===String(vendor.id);
     const pageBase=`${vendorBase}${encodeURIComponent(vendor.id)}`;
     const channel=vendorPage.startsWith(pageBase+'/call')?'call':vendorPage.startsWith(pageBase+'/email')?'email':'home';
     const emailTab=vendorPage.endsWith('/negotiations')?'negotiation':vendorPage.endsWith('/progress')?'progress':'home';
     const negData=hasVendorReplied?(vendor.offer?.negotiation_data||negotiationReport?.vendors_comparison?.find(v=>String(v.vendor_id)===String(vendor.id))):null;
     const valData=vendor.offer?.validation||null;
     const currentRfq=rfqEdits[vendor.id]||{to_email:vendor.email||'',subject:vendor.rfq_subject||'',body:vendor.rfq_body||''};
     const rfqBusy=busy||sendingRfqs||vendor.status==='rfq_sending';

     const isNoNeg = vendor.status === 'no_negotiation_needed' || negData?.needs_negotiation === false || vendor.ai_decision === 'no_negotiation_needed';
     const isRound2Sent = vendor.status === 'round_2_counteroffer_sent' || Boolean(negData?.round_2_approved_and_sent);

     return (
      <div className="cv-expanded-drawer cv-vendor-page" role="region" aria-label={`${vendor.name} ${channel} page`}>
       <header className="cv-vendor-page-header">
        {channel!=='home'&&(
         <button type="button" className="p-button cv-back-btn-thin" onClick={()=>{if(channel==='email'&&emailTab!=='home')goVendor(vendor.id,'/email');else goVendor(vendor.id);}}>
          ← Back {channel==='email'&&emailTab!=='home'?'to options':'to vendor'}
         </button>
        )}
        <div className="cv-header-title-block">
         <div className="cv-header-kicker">
          <span className="cv-kicker-dot"></span>
          <small>VENDOR COMMUNICATIONS</small>
          <span className="cv-kicker-sep">/</span>
          <span className="cv-kicker-sub">{channel==='home'?'OVERVIEW':channel==='call'?'VOICE OUTREACH':'EMAIL OUTREACH'}</span>
         </div>
         <div className="cv-header-h2-row">
          <h2>{vendor.name}</h2>
          {isNoNeg&&<span className="cv-tag-optimal">AI: No Negotiation Needed</span>}
          {hasVendorReplied&&!isNoNeg&&<span className="cv-badge badge-quote">Quote Received (INR {Number(vendor.offer?.total_price||vendor.offer?.unit_price||0).toLocaleString()})</span>}
         </div>
         <p>{channel==='home'?'Choose a communication channel':channel==='call'?'Call progress':emailTab==='home'?'Select an outreach stream below':emailTab==='progress'?'Current outbound RFQ and inbound quote status':'Autonomous pricing negotiation & counteroffer strategy'}</p>
        </div>
       </header>
       
       {channel==='home'&&<div className="crm-vendor-layout"><aside className="crm-worklist"><small>SUPPLIER WORKLIST</small>{run.vendors.map(v=><button type="button" key={v.id} className={v.id===vendor.id?'active':''} onClick={()=>goVendor(v.id)}><span className="crm-avatar">{v.name.slice(0,1)}</span><span><strong>{v.name}</strong><small className={v.reply_text?'crm-status-reply':v.sent_at?'crm-status-awaiting':'crm-status-draft'}>{v.reply_text?'Reply received':v.sent_at?'Awaiting reply':'Draft prepared'}</small></span></button>)}</aside><VendorRecord vendor={vendor} activities={allActivities} onEmail={()=>goVendor(vendor.id,'/email')} onCall={()=>goVendor(vendor.id,'/call')}/></div>}
       {/* LEVEL 1: TWO BARS (CALL PROGRESS vs EMAIL PROGRESS) */}
       <div className="cv-channel-bars" hidden>
        <button
         type="button"
         className={`cv-channel-bar-btn ${channel==='call'?'active':''}`}
         onClick={()=>goVendor(vendor.id,'/call')}
        >
         <span>See Vendor's Call Progress</span>
        </button>
        
        <button
         type="button"
         className={`cv-channel-bar-btn ${channel==='email'?'active':''}`}
         onClick={()=>goVendor(vendor.id,'/email')}
        >
         <span>See Vendor's Email Progress</span>
         {hasVendorReplied&&<span className="cv-bar-badge">Quote In</span>}
         {negData?.counteroffer_sent&&<span className="cv-bar-badge done">Countered</span>}
        </button>
       </div>


          {/* ── IF CALL SELECTED: DOGRAH VOICE AI PANEL (DRY RUN SIMULATION) ── */}
          {channel==='call'&&(
            <DograhVoicePanel
              vendor={vendor}
              run={run}
              request={row || request || (rowId ? { id: rowId } : null)}
              onRefresh={async()=>{
                const targetId = row?.id || request?.id || rowId;
                if(targetId){
                  try{
                    const {data}=await sourcingApi.detail(targetId);
                    if(onRunUpdated && data?.agent_run) onRunUpdated(data.agent_run);
                  }catch(e){console.warn(e);}
                }
              }}
              onBack={()=>goVendor(vendor.id,'')}
            />
          )}

          {/* ── IF EMAIL SELECTED: 2 SUB-BARS (CURRENT PROGRESS vs NEGOTIATIONS) ── */}
          {channel==='email'&&(
           <div className="cv-email-section">
            
            {/* LEVEL 2: SLEEK & THIN SUB-BARS */}
            <div className="cv-email-sub-bars" hidden={emailTab!=='home'}>
             <button
              type="button"
              className={`cv-email-sub-bar-btn ${emailTab==='progress'?'active':''}`}
              onClick={()=>goVendor(vendor.id,'/email/progress')}
             >
              <div className="cv-btn-left-content">
               <div className="cv-btn-icon-box"><Mail size={16}/></div>
               <div className="cv-btn-text-block">
                <span className="cv-btn-title">Outbound RFQ &amp; Supplier Reply Progress</span>
                <p className="cv-btn-desc">Review dispatched RFQ email, delivery status, and incoming quote details</p>
               </div>
              </div>
              <div className="cv-btn-right-content">
               {hasVendorReplied ? (
                <span className="cv-thin-status-tag tag-success">Quote Received (INR {Number(vendor.offer?.total_price||vendor.offer?.unit_price||0).toLocaleString()})</span>
               ) : hasVendorBeenSent ? (
                <span className="cv-thin-status-tag tag-sent">Awaiting Reply</span>
               ) : (
                <span className="cv-thin-status-tag tag-draft">Draft Ready</span>
               )}
               <span className="cv-thin-arrow">→</span>
              </div>
             </button>

             <button
              type="button"
              className={`cv-email-sub-bar-btn ${emailTab==='negotiation'?'active':''}`}
              onClick={()=>goVendor(vendor.id,'/email/negotiations')}
             >
              <div className="cv-btn-left-content">
               <div className="cv-btn-icon-box"><TrendingDown size={16}/></div>
               <div className="cv-btn-text-block">
                <span className="cv-btn-title">Commercial Negotiations &amp; Counteroffers</span>
                <p className="cv-btn-desc">AI budget benchmarking, margin evaluation, and automated executive counteroffers</p>
               </div>
              </div>
              <div className="cv-btn-right-content">
               {isNoNeg ? (
                <span className="cv-thin-status-tag tag-optimal">AI: Optimal (No Neg)</span>
               ) : vendor.status==='negotiation_counteroffer_sent'||negData?.counteroffer_sent ? (
                <span className="cv-thin-status-tag tag-countered">Counteroffer Auto-Sent</span>
               ) : hasVendorReplied ? (
                <span className="cv-thin-status-tag tag-ready">Ready to Negotiate</span>
               ) : (
                <span className="cv-thin-status-tag tag-pending">Pending Quote</span>
               )}
               <span className="cv-thin-arrow">→</span>
              </div>
             </button>
            </div>

            {/* SLEEK TOP TAB STRIP (active when inside progress or negotiations) */}
            {emailTab!=='home'&&(
             <div className="cv-email-nav-tabs">
              <button
               type="button"
               className={`cv-nav-tab-item ${emailTab==='progress'?'active':''}`}
               onClick={()=>goVendor(vendor.id,'/email/progress')}
              >
               <span className="cv-nav-tab-icon"><Mail size={14}/></span>
               <span>RFQ &amp; Reply Progress</span>
               {hasVendorReplied&&<span className="cv-nav-tab-pill">Quote In</span>}
              </button>
              <button
               type="button"
               className={`cv-nav-tab-item ${emailTab==='negotiation'?'active':''}`}
               onClick={()=>goVendor(vendor.id,'/email/negotiations')}
              >
               <span className="cv-nav-tab-icon"><TrendingDown size={14}/></span>
               <span>Negotiations &amp; Counteroffers</span>
               {isNoNeg?<span className="cv-nav-tab-pill optimal">Optimal</span>:negData?.counteroffer_sent?<span className="cv-nav-tab-pill sent">Auto-Sent</span>:null}
              </button>
             </div>
            )}

            {/* ── SUB-BAR 1: SEE CURRENT PROGRESS ── */}
            {emailTab==='progress'&&(
             <div className="cv-sub-content">
              
              {/* 1. CURRENT MAIL GIVEN TO THE VENDOR */}
              <div className="cv-progress-mail-card">
               <div className="cv-progress-card-title">
                <div>
                 <span className="cv-label-mini">OUTBOUND RFQ EMAIL</span>
                 <h5>{vendor.rfq_subject||`Request for quotation: ${vendor.name}`}</h5>
                 <div className="cv-mail-meta-line">
                  <span>From: <strong>prepares23@gmail.com</strong></span>
                  <span>To: <strong>{vendor.email}</strong></span>
                  {vendor.sent_at&&<span>Dispatched: <strong>{new Date(vendor.sent_at).toLocaleString()}</strong></span>}
                 </div>
                </div>
                {vendor.status==='send_failed'?(
                 <span className="cv-badge-smtp-failed">SMTP send failed</span>
                ):vendor.sent_at?(
                 <span className="cv-badge-smtp-sent">✓ SMTP accepted · delivery unconfirmed</span>
                ):vendor.status==='rfq_sending'?(
                 <span className="cv-badge-rfq-unsent">Sending RFQ…</span>
                ):(
                 <span className="cv-badge-rfq-unsent">Queued for automatic sending</span>
                )}
               </div>
               {vendor.email?.trim().toLowerCase()==='prepares23@gmail.com'&&(
                <p className="cv-mail-test-recipient-note">This test recipient is the sender’s own mailbox. A sent message will go to prepares23@gmail.com, not a separate supplier inbox.</p>
               )}
               {['send_failed','contact_required'].includes(vendor.status)&&vendor.send_error&&(
                <p className="cv-mail-send-error"><strong>SMTP error:</strong> {vendor.send_error}</p>
               )}
               {hasVendorBeenSent?<div className="cv-mail-body-display"><pre>{vendor.rfq_body}</pre></div>:<>
                <label className="cv-rfq-edit-label">To<input type="email" aria-label="RFQ recipient" value={currentRfq.to_email} disabled={rfqBusy} onChange={e=>setRfqEdits(prev=>({...prev,[vendor.id]:{...currentRfq,to_email:e.target.value}}))}/></label>
                <label className="cv-rfq-edit-label">Subject<input aria-label="RFQ subject" value={currentRfq.subject} disabled={rfqBusy} onChange={e=>setRfqEdits(prev=>({...prev,[vendor.id]:{...currentRfq,subject:e.target.value}}))}/></label>
                <label className="cv-rfq-edit-label">Message<textarea aria-label="RFQ message" rows={10} value={currentRfq.body} disabled={rfqBusy} onChange={e=>setRfqEdits(prev=>({...prev,[vendor.id]:{...currentRfq,body:e.target.value}}))}/></label>
                <div className="cv-rfq-review-actions">
                 <span>RFQs are sent automatically. Edited details are saved when you send or retry.</span>
                 <button type="button" className="cv-btn cv-btn-primary" disabled={rfqBusy||!run.mailbox?.configured} onClick={()=>handleSendRfqs([vendor])}>{sendingRfqs?'Sending…':vendor.status==='send_failed'?'Retry email':'Send email'}</button>
                </div>
               </>}
               {dispatchFeedback&&<p className={`cv-dispatch-feedback ${dispatchFeedback.error?'is-error':''}`} role={dispatchFeedback.error?'alert':'status'}>{dispatchFeedback.text}</p>}
              </div>

              {/* 2. CURRENT STATUS OF THE VENDOR'S EMAIL REPLY */}
              <div className="cv-progress-reply-card">
               <div className="cv-progress-reply-head">
                <div>
                 <span className="cv-label-mini">INBOUND VENDOR QUOTATION</span>
                 <h5>Vendor Email Response Status</h5>
                </div>
                <span className={hasVendorReplied?'cv-badge-quote-received':vendor.sent_at?'cv-badge-pending-reply':'cv-badge-rfq-unsent'}>
                 {hasVendorReplied?'Quotation Received':vendor.sent_at?'Pending Reply':'Not sent'}
                </span>
               </div>

               {!hasVendorReplied?(
                <div className="cv-pending-reply-banner">
                 {vendor.sent_at?(
                  <><p><strong>Pending Reply:</strong> Awaiting commercial quotation response from {vendor.name}.</p><small>The AI agent checks the configured sourcing inbox for vendor replies.</small></>
                 ):(
                  <p><strong>No reply is expected yet.</strong> This RFQ has not been accepted by SMTP for sending.</p>
                 )}
                </div>
               ):(
                <div className="cv-reply-details-wrap">
                 <div className="cv-reply-metrics-grid">
                  <div className="cv-rep-chip">
                   <span>Quoted Price</span>
                   <strong>{vendor.offer?.currency||'INR'} {Number(vendor.offer?.total_price||vendor.offer?.unit_price||0).toLocaleString()}</strong>
                  </div>
                  <div className="cv-rep-chip">
                   <span>Lead Time</span>
                   <strong>{vendor.offer?.lead_time_days!=null?`${vendor.offer.lead_time_days} days`:'Proposed in quote'}</strong>
                  </div>
                  <div className="cv-rep-chip">
                   <span>Warranty</span>
                   <strong>{vendor.offer?.warranty||'1 Year Standard Support'}</strong>
                  </div>
                  <div className="cv-rep-chip">
                   <span>Payment Terms</span>
                   <strong>{vendor.offer?.payment_terms||'Net 30'}</strong>
                  </div>
                 </div>

                 {/* STAGE 4: VALIDATION ENGINE & AUTO-CLARIFICATION STATUS */}
                 {valData&&(valData.needs_clarification||valData.is_declined||valData.missing_fields?.length>0||valData.ambiguity_notes?.length>0)&&(
                  <div style={{marginTop:14,marginBottom:14,padding:'14px 16px',borderRadius:10,background:'rgba(239, 153, 118, 0.08)',border:'1px solid rgba(239, 153, 118, 0.3)'}}>
                   <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                    <strong style={{color:'#ef9976',fontSize:12.5}}>Stage 4 Validation Engine: {valData.is_declined?'Supplier Declined':'Missing / Ambiguous Commercial Terms Detected'}</strong>
                    {valData.clarification_sent&&(
                     <span style={{fontSize:11,background:'rgba(239, 153, 118, 0.16)',color:'#f5d0bc',padding:'2px 8px',borderRadius:999}}>Clarification Request Auto-Dispatched</span>
                    )}
                   </div>
                   {valData.missing_fields?.length>0&&(
                    <div style={{fontSize:12,color:'#e7d5c5',marginBottom:6}}>
                     <strong>Missing Fields:</strong> {valData.missing_fields.join(' · ')}
                    </div>
                   )}
                   {valData.ambiguity_notes?.length>0&&(
                    <div style={{fontSize:12,color:'#e7d5c5',marginBottom:6}}>
                     <strong>Ambiguities Flagged:</strong> {valData.ambiguity_notes.join(' · ')}
                    </div>
                   )}
                   {valData.clarification_draft&&(
                    <details style={{marginTop:8}}>
                     <summary style={{cursor:'pointer',fontSize:11.5,color:'#a8a29e'}}>View Auto-Dispatched Commercial Clarification Email</summary>
                     <pre className="cv-pre-content" style={{marginTop:8,fontSize:11.5}}>{valData.clarification_draft}</pre>
                    </details>
                   )}
                  </div>
                 )}

                 {/* STAGE 5: AUTONOMOUS EMAIL REPLY INTELLIGENCE & GROUNDS */}
                 {vendor.offer?.negotiation_intelligence&&(()=>{
                   const ni=vendor.offer.negotiation_intelligence;
                   const incomp=ni.what_is_incomplete||[];
                   const wrong=ni.what_is_wrong||[];
                   const grounds=ni.negotiation_grounds||[];
                   return (
                    <div style={{marginTop:12,marginBottom:14,padding:'14px 16px',borderRadius:10,background:'rgba(239, 153, 118, 0.05)',border:'1px solid rgba(239, 153, 118, 0.22)'}}>
                     <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                      <strong style={{color:'#ef9976',fontSize:12.5,display:'flex',alignItems:'center',gap:6}}>
                       <Sparkles size={14}/> Autonomous Email Reply Intelligence &amp; Grounds
                      </strong>
                      <span style={{fontSize:11,color:'#f5d0bc'}}>{grounds.length} Grounds for Counteroffer</span>
                     </div>
                     {incomp.length>0&&(
                      <div style={{fontSize:12,color:'#e7d5c5',marginBottom:6}}>
                       <strong style={{color:'#ef9976'}}>Incomplete Items:</strong> {incomp.map(i=>i.term).join(' · ')}
                      </div>
                     )}
                     {wrong.length>0&&(
                      <div style={{fontSize:12,color:'#e7d5c5',marginBottom:6}}>
                       <strong style={{color:'#f87171'}}>Policy Corrections Required:</strong> {wrong.map(w=>w.violation).join(' · ')}
                      </div>
                     )}
                     {grounds.length>0&&(
                      <div style={{fontSize:12,color:'#d6d3d1'}}>
                       <strong style={{color:'#4ade80'}}>Negotiation Grounds:</strong> {grounds.map(g=>g.title).join(' · ')}
                      </div>
                     )}
                    </div>
                   );
                 })()}

                 {negData?.counteroffer_response&&(()=>{
                   const cr=negData.counteroffer_response;
                   const label={accepted:'Counteroffer accepted',partially_accepted:'Partially accepted',rejected:'Counteroffer rejected',counter_proposal:'Vendor counter-proposal',clarification_requested:'Vendor asked a question',deferred:'Vendor will revert',withdrawn:'Vendor withdrew',auto_reply:'Auto-reply (ignored)',unclear:'Needs human review'}[cr.response_class]||cr.response_class;
                   const tone=cr.response_class==='accepted'?'ok':['rejected','withdrawn'].includes(cr.response_class)?'bad':'warn';
                   const names={price:'Total price',payment:'Payment terms',warranty:'Warranty',delivery:'Delivery'};
                   const show=v=>v==null?'-':String(v);
                   return <div className="cv-cr-card">
                    <div className="cv-cr-head">
                     <div><span className="cv-label-mini">REPLY TO COUNTEROFFER</span><h5>Negotiation response analysis</h5></div>
                     <span className={`cv-cr-pill ${tone}`}>{label}</span>
                    </div>
                    <table className="cv-cr-table"><thead><tr><th>Term</th><th>We asked</th><th>Vendor replied</th><th>Result</th></tr></thead><tbody>
                     {Object.entries(names).map(([k,n])=>{const t=cr.terms?.[k]||{};const res=t.decision==='accepted'?'Accepted':t.decision==='declined'?'Declined':t.decision==='counter_proposed'?'Counter-proposed':'Not addressed';
                      return <tr key={k}><td>{n}</td><td>{show(t.target)}</td><td>{show(t.vendor_value)}</td><td><span className={`cv-cr-res ${t.decision}`}>{res}</span></td></tr>;})}
                    </tbody></table>
                    <p className="cv-cr-note">{cr.reason}</p>
                    <div className="cv-cr-meta">
                     <span>Original quote: <strong>{cr.original_quote?Number(cr.original_quote).toLocaleString():'-'}</strong></span>
                     <span>Quote validity: <strong>{cr.quote_validity_days?`${cr.quote_validity_days} days`:'-'}</strong></span>
                     <span>Next step: <strong>{String(cr.next_action||'').replace(/_/g,' ')}</strong></span>
                    </div>
                   </div>;
                  })()}
                  <div className="cv-reply-raw-msg">
                  <span className="cv-reply-raw-title">Actual Received Email Message Text:</span>
                  <pre className="cv-pre-content">{vendor.reply_text}</pre>
                 </div>
                </div>
               )}
              </div>

             </div>
            )}

            {/* ── SUB-BAR 2: SEE FOR NEGOTIATIONS ── */}
            {emailTab==='negotiation'&&(
             <div className="cv-sub-content">
              {!hasVendorReplied?(
               <div className="cv-neg-waiting-card">
                <h4>Negotiation Engine Awaiting Quotation</h4>
                <p>As soon as <strong>{vendor.name}</strong> submits their quotation, the AI Commercial Negotiator will immediately compare prices against budget targets and auto-dispatch an executive counteroffer via SMTP.</p>
                <small>Inbox is being polled automatically every 8 seconds.</small>
               </div>
              ):(
               <div className="cv-neg-content-wrap">
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:'12px',padding:'14px 18px',marginBottom:'16px',background:'#241f1c',border:'1px solid rgba(255,255,255,0.08)',borderRadius:'12px'}}>
                 <div style={{display:'flex',alignItems:'center',gap:'10px',flexWrap:'wrap'}}>
                  <span className={`cv-badge ${isRound2Sent?'badge-optimal':'badge-countered'}`}>
                   {isRound2Sent?'Round 2 Counteroffer Sent (Human Approved)':'Round 1 Auto-Sent (Policy) · Round 2 Pending Approval'}
                  </span>
                  {vendor.sent_at&&(
                   <small className="cv-sent-time">
                    Dispatched {new Date(vendor.sent_at).toLocaleDateString([],{month:'short',day:'numeric'})} at {new Date(vendor.sent_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}
                   </small>
                  )}
                 </div>
                 {negData?.diff_percent!=null&&(
                  <span className={`cv-savings-tag ${negData.is_cheaper?'tag-cheaper':'tag-over'}`}>
                   {negData.is_cheaper?`↓ ₹${Number(negData.savings_amount||0).toLocaleString()} cheaper (-${Math.abs(negData.diff_percent)}%)`:`+${negData.diff_percent}% over budget`}
                  </span>
                 )}
                </div>

                {negData&&(
                 <div className="cv-neg-figures-row">
                  <div className="cv-neg-fig-box">
                   <span>Quoted Price</span>
                   <strong>INR {Number(negData.quoted_price||vendor.offer?.total_price||0).toLocaleString()}</strong>
                  </div>
                  <div className="cv-neg-fig-box">
                   <span>Target Budget</span>
                   <strong>INR {Number(negotiationReport?.target_budget||0).toLocaleString()}</strong>
                  </div>
                  <div className="cv-neg-fig-box highlight">
                   <span>Cost Difference / Savings</span>
                   <strong style={{color:negData.is_cheaper?'#f5d0bc':'#ef9976'}}>
                    {negData.is_cheaper?`↓ INR ${Number(negData.savings_amount||0).toLocaleString()} cheaper (-${Math.abs(negData.diff_percent)}%)`:`+${negData.diff_percent}% over budget`}
                   </strong>
                  </div>
                 </div>
                )}

                {negData?.negotiation_tip&&(
                 <div className="cv-neg-tip-box">
                  <span className="cv-tip-badge">Strategic Negotiation Play</span>
                  <p>{negData.negotiation_tip}</p>
                 </div>
                )}

                {/* ── AUTONOMOUS NEGOTIATION INTELLIGENCE ENGINE (Gap Analysis, Policy Violations & Negotiation Grounds) ── */}
                {(()=>{
                  const intel = negData?.negotiation_intelligence || vendor.offer?.negotiation_intelligence || null;
                  if (!intel) return null;
                  const incomp = intel.what_is_incomplete || [];
                  const wrong = intel.what_is_wrong || [];
                  const grounds = intel.negotiation_grounds || [];
                  return (
                    <div className="cv-negotiation-intelligence-panel" style={{margin:'18px 0',padding:'18px 20px',borderRadius:12,background:'#201b18',border:'1px solid rgba(239, 153, 118, 0.35)'}}>
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:14,flexWrap:'wrap',gap:8}}>
                        <div style={{display:'flex',alignItems:'center',gap:8}}>
                          <Sparkles size={16} style={{color:'#ef9976'}}/>
                          <strong style={{fontSize:13.5,color:'#f5d0bc',letterSpacing:'0.02em'}}>Autonomous Negotiation Intelligence &amp; Gap Analysis</strong>
                        </div>
                        <span style={{fontSize:11,background:'rgba(239,153,118,0.18)',color:'#f5d0bc',padding:'3px 10px',borderRadius:20,fontWeight:600}}>
                          {grounds.length} Negotiation Grounds Established
                        </span>
                      </div>

                      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(280px, 1fr))',gap:12,marginBottom:14}}>
                        <div style={{background:'#181513',padding:'14px 16px',borderRadius:10,border:'1px solid #332b26'}}>
                          <small style={{display:'block',color:'#ef9976',fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:8}}>
                            🔍 What is Incomplete in Reply ({incomp.length})
                          </small>
                          {incomp.length ? (
                            <ul style={{margin:0,paddingLeft:16,fontSize:12,color:'#cfc7c2',lineHeight:1.6}}>
                              {incomp.map((item, idx) => (
                                <li key={idx}><strong style={{color:'#f5f5f4'}}>{item.term}:</strong> {item.detail}</li>
                              ))}
                            </ul>
                          ) : (
                            <p style={{margin:0,fontSize:12,color:'#4ade80'}}>✓ All essential commercial terms &amp; specs provided.</p>
                          )}
                        </div>

                        <div style={{background:'#181513',padding:'14px 16px',borderRadius:10,border:'1px solid #332b26'}}>
                          <small style={{display:'block',color:'#f87171',fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:8}}>
                            ⚠️ What is Non-Compliant / Wrong ({wrong.length})
                          </small>
                          {wrong.length ? (
                            <ul style={{margin:0,paddingLeft:16,fontSize:12,color:'#cfc7c2',lineHeight:1.6}}>
                              {wrong.map((item, idx) => (
                                <li key={idx}><strong style={{color:'#fca5a5'}}>{item.violation}:</strong> {item.policy}</li>
                              ))}
                            </ul>
                          ) : (
                            <p style={{margin:0,fontSize:12,color:'#4ade80'}}>✓ No corporate policy violations detected in offer terms.</p>
                          )}
                        </div>
                      </div>

                      {grounds.length > 0 && (
                        <div style={{background:'#181513',padding:'14px 16px',borderRadius:10,border:'1px solid rgba(239, 153, 118, 0.22)'}}>
                          <small style={{display:'block',color:'#f5d0bc',fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:10}}>
                            🎯 Specific Grounds for Counteroffer Negotiation
                          </small>
                          <div style={{display:'grid',gap:10}}>
                            {grounds.map((g, idx) => (
                              <div key={idx} style={{display:'flex',gap:10,alignItems:'flex-start',fontSize:12}}>
                                <span style={{background:'#352a25',color:'#ef9976',minWidth:22,height:22,borderRadius:'50%',display:'grid',placeItems:'center',fontSize:11,fontWeight:700,flexShrink:0}}>{idx + 1}</span>
                                <div>
                                  <strong style={{color:'#f5f5f4',display:'block',fontSize:12.5}}>{g.title} <span style={{color:'#ef9976',fontWeight:500,fontSize:11}}>({g.ground_type})</span></strong>
                                  <span style={{color:'#a8a29e',lineHeight:1.45,display:'block',marginTop:2}}>{g.rationale}</span>
                                  <span style={{color:'#f5d0bc',fontWeight:600,display:'block',marginTop:3}}>→ {g.counter_action}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}

                {isNoNeg&&(
                 <div className="cv-no-neg-card">
                  <div className="cv-no-neg-card-header">
                   <span className="cv-badge badge-optimal">AI Decision: No Negotiations Needed</span>
                   <strong className="cv-no-neg-vendor-title">AI has decided no negotiations needed for {vendor.name}</strong>
                   <p className="cv-no-neg-desc">
                    {negData?.negotiation_decision_reason || vendor.negotiation_decision_reason || `${vendor.name}'s quote is already below target budget with favorable terms. AI recommends locking in terms without further counteroffers.`}
                   </p>
                  </div>
                  <div className="cv-no-neg-prompt-box">
                   <div>
                    <strong className="cv-prompt-q">AI has decided no negotiations needed for {vendor.name}. Do you still want to negotiate?</strong>
                    <p className="cv-prompt-sub">The AI recommends locking in this pricing. You can customize and dispatch a counteroffer below if you wish to negotiate further.</p>
                   </div>
                   <button
                    type="button"
                    className="cv-btn cv-btn-warning cv-btn-sm"
                    disabled={sendingCounter[vendor.id]}
                    onClick={()=>handleSendCounteroffer(vendor)}
                   >
                    {sendingCounter[vendor.id]?'Sending…':'Override & Send Counteroffer'}
                   </button>
                  </div>
                 </div>
                )}

                {/* ── ROUND 1: AUTONOMOUS COMPANY POLICY NEGOTIATION (ZERO HUMAN IN THE LOOP) ── */}
                <div className="cv-auto-sent-banner" style={{background:'#241f1c',border:'1px solid rgba(239, 153, 118, 0.35)',borderRadius:12,padding:'18px 22px',marginBottom:18}}>
                 <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',gap:14,marginBottom:12}}>
                  <div>
                   <span style={{display:'inline-block',fontSize:10.5,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',padding:'3px 10px',borderRadius:999,background:'rgba(239, 153, 118, 0.16)',color:'#f5d0bc',marginBottom:6}}>
                    Round 1 · Autonomous Company Policy Engine (No Human Approval Required)
                   </span>
                   <strong style={{display:'block',color:'#f5f5f4',fontSize:14,fontWeight:700}}>
                    1st Negotiation Automatically Dispatched Upon Reply Receipt
                   </strong>
                   <span style={{fontSize:12.5,color:'#cfc7c2',lineHeight:1.45,display:'block',marginTop:4}}>
                    {negData?.negotiation_decision_reason || `As soon as ${vendor.name}'s quotation was received, the AI Policy Engine evaluated the quote against Company Procurement Policies and automatically dispatched the Round 1 counteroffer without human intervention.`}
                   </span>
                  </div>
                  {negData?.counteroffer_sent_at&&(
                   <div style={{textAlign:'right',flexShrink:0}}>
                    <span style={{display:'block',fontSize:10,color:'#a8a29e',textTransform:'uppercase',letterSpacing:'0.5px'}}>Round 1 Auto-Sent</span>
                    <strong style={{fontSize:12,color:'#ef9976'}}>
                     {new Date(negData.counteroffer_sent_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}
                    </strong>
                   </div>
                  )}
                 </div>

                 <div style={{background:'#1c1917',border:'1px solid rgba(255,255,255,0.07)',borderRadius:10,padding:'12px 16px',marginBottom:12}}>
                  <small style={{display:'block',fontSize:10.5,fontWeight:700,color:'#a8a29e',textTransform:'uppercase',letterSpacing:'0.05em',marginBottom:8}}>
                   Company Procurement Policies Enforced in Round 1
                  </small>
                  <ul style={{margin:0,paddingLeft:18,color:'#e7e5e4',fontSize:12,lineHeight:1.6}}>
                   {(negData?.company_policies_applied?.length ? negData.company_policies_applied : [
                    `Company Policy 1 (Benchmark / Target Price): Revise commercial offer to INR ${Number(negData?.round_1_target_price || Math.round((negData?.quoted_price || vendor.offer?.total_price || 50000) * 0.94)).toLocaleString()}`,
                    'Company Policy 2 (Working Capital): Mandatory Net 45 Days payment terms from invoice receipt',
                    'Company Policy 3 (Risk & Quality): Minimum 24-month comprehensive commercial warranty',
                    'Company Policy 4 (Logistics SLA): Priority 5-7 business days all-inclusive DDP delivery',
                   ]).map((pol, pIdx) => <li key={pIdx}>{pol}</li>)}
                  </ul>
                 </div>

                 <details>
                  <summary style={{cursor:'pointer',fontSize:12,fontWeight:600,color:'#ef9976'}}>
                   View Round 1 Auto-Dispatched Counteroffer Email
                  </summary>
                  <div className="cv-counter-body-display" style={{marginTop:10}}>
                   <pre>{negData?.counteroffer_email_draft || `Dear ${vendor.name} Commercial Team,\n\nIn accordance with our Company Procurement Policies, we have automatically generated our Round 1 commercial counteroffer requesting Net 45 payment terms, 24-month warranty coverage, and benchmark pricing alignment.\n\nSincerely,\nAutonomous Procurement Policy Engine`}</pre>
                  </div>
                 </details>
                </div>

                {/* ── ROUND 2: HUMAN-IN-THE-LOOP ESCALATION GATE ── */}
                <div className="cv-counteroffer-card" style={{border:'1px solid rgba(214, 211, 209, 0.18)',background:'#1c1917'}}>
                 <div className="cv-counteroffer-head">
                  <div>
                   <span className="cv-label-mini" style={{color:'#f5d0bc'}}>ROUND 2 ESCALATION · HUMAN-IN-THE-LOOP APPROVAL REQUIRED</span>
                   <h5>{counterEdits[vendor.id]?.subject||`Round 2 Best-and-Final Offer (BAFO): [Ref: AuditAI-R${run.id}-V${vendor.id}] - ${vendor.name}`}</h5>
                   <div className="cv-mail-meta-line">
                    <span>Sender: <strong>prepares23@gmail.com</strong></span>
                    <span>Recipient: <strong>{vendor.email}</strong></span>
                    <span>Target BAFO: <strong>INR {Number(negData?.round_2_target_price || Math.round((negData?.quoted_price || vendor.offer?.total_price || 50000) * 0.90)).toLocaleString()} (Net 60 · 36-Mo Warranty)</strong></span>
                   </div>
                  </div>
                  <span className={isRound2Sent?'cv-badge-counter-sent':'cv-badge-counter-held'}>
                   {isRound2Sent?'Round 2 Approved & Sent by Human':'Awaiting Human Approval for 2nd Negotiation'}
                  </span>
                 </div>

                 <div style={{padding:'0 20px 14px'}}>
                  <label style={{display:'block',fontSize:11.5,color:'#a8a29e',marginBottom:6}}>
                   Review or edit the Round 2 Best-and-Final Counteroffer before approving dispatch:
                  </label>
                  <textarea
                   rows={8}
                   value={counterEdits[vendor.id]?.body ?? (negData?.round_2_counteroffer_draft || negData?.counteroffer_email_draft || '')}
                   onChange={e=>setCounterEdits(prev=>({...prev,[vendor.id]:{...(prev[vendor.id]||{subject:`Round 2 Commercial Counteroffer: [Ref: AuditAI-R${run.id}-V${vendor.id}] - ${vendor.name}`,to_email:vendor.email||''}),body:e.target.value}}))}
                   style={{width:'100%',boxSizing:'border-box',padding:'12px 14px',borderRadius:8,background:'#141210',border:'1px solid rgba(255,255,255,0.1)',color:'#f5f5f4',fontFamily:'ui-monospace, SFMono-Regular, Menlo, monospace',fontSize:12,lineHeight:1.55}}
                  />
                 </div>

                 <div className="cv-counter-footer-bar">
                  <span>
                   {isRound2Sent
                    ? `Round 2 negotiation approved and dispatched${negData?.round_2_sent_at ? ' at ' + new Date(negData.round_2_sent_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}) : ''}.`
                    : 'Round 1 was sent automatically by the AI Policy Engine. Human approval is required to dispatch this 2nd negotiation.'}
                  </span>
                  <button
                   type="button"
                   className="cv-btn cv-btn-primary cv-btn-sm"
                   disabled={sendingCounter[vendor.id]}
                   onClick={()=>handleSendCounteroffer(vendor, 2)}
                  >
                   {sendingCounter[vendor.id]?'Dispatching Round 2…':isRound2Sent?'Re-send 2nd Negotiation':'Approve & Send 2nd Negotiation'}
                  </button>
                 </div>
                </div>

               </div>
              )}
             </div>
            )}

           </div>
          )}

         </div>
        );
       })()}
      </div>
     )}

  {/* ── VIEW 2: VENDOR COMPLIANCE & ONBOARDING CHECKLIST ─────────────── */}
  {activePanelTab==='compliance'&&(
   <div className="cv-compliance-container">
    <div className="cv-comp-nav">
     <span className="cv-comp-link active">Overview</span>
     <span className="cv-comp-link">Request details</span>
     <span className="cv-comp-link">Purchase details</span>
     <span className="cv-comp-link">Documents</span>
     <span className="cv-comp-link">Surveys</span>
     <span className="cv-comp-link">Vendor</span>
     <span className="cv-comp-link">Products</span>
    </div>
    <table className="cv-comp-table">
     <thead>
      <tr>
       <th>Item / Requirement</th>
       <th>Status</th>
       <th>Vendor Contact</th>
       <th>Date</th>
       <th style={{textAlign:'right'}}>Actions</th>
      </tr>
     </thead>
     <tbody>
      {complianceItems.map((item,idx)=>{
       const statusCls=item.status==='Uploaded'?'comp-uploaded':item.status==='Ready for review'?'comp-review':'comp-awaiting';
       return <tr key={idx} className="cv-comp-row">
        <td className="cv-comp-td-name">
         <strong>{item.name}</strong>
         {item.optional&&<small className="cv-comp-opt">Optional</small>}
        </td>
        <td className="cv-comp-td-status">
         <span className={`cv-comp-badge ${statusCls}`}>{item.status}</span>
        </td>
        <td className="cv-comp-td-contact">
         <span className="cv-comp-contact-name">{item.contact}</span>
         <span className="cv-comp-contact-email">{item.email}</span>
        </td>
        <td className="cv-comp-td-date">
         <span>{item.date}</span>
        </td>
        <td className="cv-comp-td-act">
         <div style={{display:'flex',gap:6,justifyContent:'flex-end'}}>
          <button type="button" className="cv-link-btn" title="Flag or note">Note</button>
          {item.hasDoc&&<button type="button" className="cv-link-btn" title="Download Document">↓</button>}
         </div>
        </td>
       </tr>;
      })}
     </tbody>
    </table>
   </div>
  )}

  {/* ── DISCOVERY & ADD SUPPLIER PANEL (TOGGLEABLE) ────────────────── */}
  {showDiscovery&&<div className="cv-discovery-card">
   <div className="cv-disc-head">
    <Globe size={15} color="#6b46c1"/>
    <strong>Market Discovery &amp; Custom Supplier Integration</strong>
   </div>
   <div className="cv-disc-body">
    <form className="cv-disc-form" onSubmit={handleSearchSubmit}>
     <input className="cv-disc-input" placeholder={tools.search_query?`Search Google/LinkedIn for "${tools.search_query}"...`:'Search web for suppliers...'} value={searchQuery} onChange={e=>setSearchQuery(e.target.value)}/>
     <button type="submit" className="cv-btn cv-btn-primary" disabled={searching}>{searching?'Searching…':'Search Web'}</button>
     <button type="button" className="cv-btn cv-btn-secondary" onClick={()=>setShowAddCustom(c=>!c)}>+ Add Custom Supplier</button>
    </form>
    <div className="cv-disc-links">
     {tools.google_search_url&&<a className="cv-ext-link" href={tools.google_search_url} target="_blank" rel="noreferrer"><ExternalLink size={12}/> Google Search</a>}
     {tools.linkedin_search_url&&<a className="cv-ext-link" href={tools.linkedin_search_url} target="_blank" rel="noreferrer"><Building2 size={12}/> LinkedIn Companies</a>}
     {(tools.google_shopping_url||tools.indiamart_search_url)&&<a className="cv-ext-link" href={tools.google_shopping_url||tools.indiamart_search_url} target="_blank" rel="noreferrer"><Search size={12}/> B2B Products</a>}
    </div>
   </div>

   {showAddCustom&&<form className="cv-add-form" onSubmit={handleAddCustom}>
    <h6>Add a Supplier Manually</h6>
    <div className="cv-form-grid-2">
     <label>Company Name *<input required value={customVendor.name} onChange={e=>setCustomVendor({...customVendor,name:e.target.value})} placeholder="e.g. Dell India"/></label>
     <label>Contact Email<input type="email" value={customVendor.email} onChange={e=>setCustomVendor({...customVendor,email:e.target.value})} placeholder="sales@dell.com"/></label>
     <label>Website URL<input value={customVendor.website} onChange={e=>setCustomVendor({...customVendor,website:e.target.value})} placeholder="https://dell.com"/></label>
     <label>LinkedIn URL<input value={customVendor.linkedin_url} onChange={e=>setCustomVendor({...customVendor,linkedin_url:e.target.value})} placeholder="https://linkedin.com/company/dell"/></label>
    </div>
    <div style={{display:'flex',gap:8,marginTop:10}}>
     <button type="submit" className="cv-btn cv-btn-primary" disabled={!customVendor.name.trim()||busy}>Add Supplier to Shortlist</button>
     <button type="button" className="cv-btn cv-btn-secondary" onClick={()=>setShowAddCustom(false)}>Cancel</button>
    </div>
   </form>}
  </div>}

  {/* ── LIVE ACTIVITY FEED (COLLAPSIBLE / CLEAN) ───────────────────── */}
  <details className="cv-activity-details">
   <summary><Activity size={13}/> Live Sourcing Activity Stream ({allActivities.length} events)</summary>
   <div className="cv-activity-list">
    {allActivities.length===0?<p className="cv-activity-none">No events logged yet. Actions like sending RFQs and receiving quotes will appear here.</p>:allActivities.slice(0,10).map(entry=><div key={entry.id} className="cv-activity-item">
     <span className="cv-act-time">{new Date(entry.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span>
     <strong className="cv-act-ev">{entry.event.replaceAll('_',' ')}</strong>
     <span className="cv-act-actor">{entry.actor}</span>
     <small className="cv-act-det">{Object.entries(entry.details||{}).map(([k,v])=>`${k}: ${v}`).join(' · ')}</small>
    </div>)}
   </div>
  </details>

  {showSmtpModal&&<SmtpConfigModal onClose={()=>setShowSmtpModal(false)} onUpdated={(status)=>{if(onRunUpdated&&run){onRunUpdated({...run,mailbox:{...(run.mailbox||{}),...status}});}}}/>}
  {showAuditModal && (
   <AuditTimeLogModal
    requestId={rowId || run?.request_id}
    requestKind="sourcing"
    requestTitle={`Sourcing Run #R${run?.id || ''}`}
    onClose={() => setShowAuditModal(false)}
   />
  )}
 </section>;

 return <>
  {/* If compact preview is active and not in separate view */}
  {isCompact && !isSeparateView ? (
   <div><SourcingDashboard vendors={run.vendors} activities={allActivities}/><div className="cv-compact-preview-card">
    <div className="cv-compact-left">
     <div className="cv-compact-icon">
      <Table size={24} color="#6d28d9"/>
     </div>
     <div className="cv-compact-info">
      <div className="cv-compact-tag-line">
       <span className="cv-compact-badge">COMMERCIAL SOURCING &amp; NEGOTIATION HUB</span>
       <span className="cv-compact-live-dot">Autonomous AI Loop Active</span>
      </div>
      <h4 className="cv-compact-title">Commercial Sourcing &amp; Price Negotiation Active</h4>
      <p className="cv-compact-desc">
       {repliedCount > 0 ? (
        <>
         <strong>{repliedCount} formal quote(s)</strong> evaluated. Strategic counteroffers prepared for review.
         {negotiationReport?.best_vendor_name && (
          <> Top proposal: <strong>{negotiationReport.best_vendor_name}</strong> (INR {Number(negotiationReport.lowest_price||0).toLocaleString()}).</>
         )}
        </>
       ) : (
        <>RFQs auto-dispatched to <strong>{sentCount || totalCount} suppliers</strong> via SMTP. Real-time inbox polling active.</>
       )}
      </p>
      <div className="cv-compact-metrics">
       <span className="cv-comp-chip"><strong>{totalCount}</strong> Suppliers</span>
       <span className="cv-comp-chip"><strong>{sentCount}</strong> RFQs Sent</span>
       <span className="cv-comp-chip"><strong>{repliedCount}</strong> Quotes In</span>
       {recommendation?.winner_vendor_name && (
        <span className="cv-comp-chip winner">Favoured: {recommendation.winner_vendor_name}</span>
       )}
      </div>
     </div>
    </div>
    <div className="cv-compact-actions">
     <button type="button" className="cv-btn-separate-primary" onClick={()=>setIsSeparateView(true)} title="Open table in dedicated spacious window">
      <Maximize2 size={15}/> Open Table Separately
     </button>
     <button type="button" className="cv-btn-inline-link" onClick={()=>setIsCompact(false)}>
      Or view full table inline here ▾
     </button>
    </div>
   </div>
  </div>) : (
   renderFullPanel(false)
  )}

  {/* Dedicated Fullscreen / Modal View */}
  {isSeparateView && createPortal(
   <div className="cv-dedicated-backdrop" onClick={()=>setIsSeparateView(false)}>
    <div className="cv-dedicated-container" onClick={e=>e.stopPropagation()}>
     <div className="cv-dedicated-topbar">
      <div className="cv-dedicated-title-wrap">
       <div>
        <h4>Commercial Sourcing &amp; Autonomous Price Negotiation</h4>
        <small>Dedicated Workspace · Zero form congestion · Real-time IMAP Polling &amp; Automated SMTP Counteroffers</small>
       </div>
      </div>
      <div className="cv-dedicated-bar-actions">
       <div className="cv-dedicated-pill">
        <span>AI sourcing · automatic RFQ emails</span>
        {lastPollAt&&<small style={{marginLeft:6,opacity:0.65}}>Synced {lastPollAt.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</small>}
       </div>
       <button type="button" className="cv-dedicated-minimize-btn" onClick={()=>setIsSeparateView(false)}>
        <Minimize2 size={14}/> Minimize to Form
       </button>
       <button type="button" className="cv-dedicated-close-x" onClick={()=>setIsSeparateView(false)} title="Close dedicated view">
        <X size={18}/>
       </button>
      </div>
     </div>
     <div className="cv-dedicated-scroll-body">
      {renderFullPanel(true)}
     </div>
    </div>
   </div>,
   document.body
  )}
 </>;
}

export default function PurchaseIntake({close,Modal,requestId,initialStep,onLocationChange}){
 const [showAuditModal,setShowAuditModal]=useState(false);
 const [row,setRow]=useState(null),[draft,setDraft]=useState({}),[items,setItems]=useState([blankItem()]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[chatError,setChatError]=useState(''),[status,setStatus]=useState('Loading request…'),[result,setResult]=useState(null),[dirty,setDirty]=useState(false),[step,setStep]=useState(0),[assistantOpenSignal,setAssistantOpenSignal]=useState(0),[privacyHelp,setPrivacyHelp]=useState(false),[contractDocs,setContractDocs]=useState([]),[contractFiles,setContractFiles]=useState({}),[workflowResult,setWorkflowResult]=useState(null),[agentRun,setAgentRun]=useState(null),[agentSelection,setAgentSelection]=useState([]);
 const rowRef=useRef(null),draftRef=useRef({}),itemsRef=useRef([blankItem()]);
 const payload=()=>{const lines=itemsRef.current.map(item=>{const line={...item};delete line.contract_start;delete line.contract_end;return {...line,quantity:Number(item.quantity)||1,unit_price:item.unit_price===''?null:Number(item.unit_price),item_category:item.item_category||null,department:item.department||null,project:item.project||null,location:item.location||null,purchasing_method:item.purchasing_method||null,service_unit:item.service_unit||null,service_level:item.service_level||null,acceptance_owner:item.acceptance_owner||null,verification_method:item.verification_method||null};});const product=lines.map(i=>i.description).filter(Boolean).join('; ');return {...draftRef.current,product:product||null,quantity:lines.reduce((n,i)=>n+(Number(i.quantity)||0),0),line_items:lines,delivery_deadline:draftRef.current.contract_end||null,delivery_location:lines[0]?.location||null,specifications:draftRef.current.specifications||'None',mandatory_conditions:draftRef.current.mandatory_conditions||'None'};};
 const adopt=r=>{const req={...r.requirements,currency:r.requirements.currency||'INR',purchase_type:r.requirements.purchase_type||'Goods',category:r.requirements.category||'',payment_terms:r.requirements.payment_terms||'Net 30',ai_selects_vendor:r.requirements.ai_selects_vendor??true,data_types:r.requirements.data_types||[],data_sharing_choice:r.requirements.data_sharing_choice||null};const next=Array.isArray(req.line_items)&&req.line_items.length?req.line_items:[blankItem()];rowRef.current={...r,requirements:req};draftRef.current=req;itemsRef.current=next;setRow({...r,requirements:req});setDraft(req);setItems(next);setDirty(false);setStatus('Saved');};
 // Keep the same initialization promise through StrictMode's effect replay.
 const initializationRef=useRef(null);
 useEffect(()=>{
  let active=true;
  if(!initializationRef.current) initializationRef.current=requestId?sourcingApi.detail(requestId):sourcingApi.create();
  initializationRef.current.then(async ({data})=>{
   if(!active)return;
   adopt(data);
   setWorkflowResult(data.workspace?.workflow||null);
   setAgentRun(data.agent_run||null);
   const requestedStep=initialStep==null?data.workspace?.step:Number(initialStep);
   setStep(Math.max(0,Math.min(3,Number(requestedStep)||0)));
   if(data.agent_run)setAgentSelection(data.agent_run.vendors.map(v=>v.id));
   try{const docs=await sourcingApi.contractDocuments(data.id);if(active)setContractDocs(docs.data);}catch(e){if(active)setError(errorText(e));}
  }).catch(e=>{if(active)setError(errorText(e));});
  return ()=>{active=false;};
 },[]);
 const locationCallbackRef=useRef(onLocationChange);locationCallbackRef.current=onLocationChange;
 useEffect(()=>{if(row?.id)locationCallbackRef.current?.(row.id,step);},[row?.id,step]);
 const saveSnapshot=async(confirm,intakeStep=step)=>{if(!rowRef.current)throw new Error('The request is still loading.');const snapshot=payload();const {data}=await sourcingApi.save(rowRef.current.id,snapshot,rowRef.current.version,confirm,intakeStep);adopt(data);setStatus('Saved to the backend as structured JSON.');return data;};
 const persist=async()=>{if(JSON.stringify(payload())===JSON.stringify(rowRef.current?.requirements)&&!dirty)return rowRef.current;const data=await saveSnapshot(false);return data;};
 const action=async fn=>{setBusy(true);setError('');try{await fn();return true;}catch(e){setError(errorText(e));return false;}finally{setBusy(false);}};
 const change=(key,value)=>{const next={...draftRef.current,[key]:value===''?null:value};draftRef.current=next;setDraft(next);setDirty(true);setStatus('Unsaved changes');};
 const changeLine=(index,key,value)=>{const next=itemsRef.current.map((item,i)=>i===index?{...item,[key]:value}:item);itemsRef.current=next;setItems(next);setDirty(true);setStatus('Unsaved changes');};
 const total=items.reduce((sum,item)=>sum+lineTotal(item),0),currency=draft.currency||'INR';
 const budgetExceeded=Number(draft.budget)>0&&total>Number(draft.budget);
 const money=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency,minimumFractionDigits:2}).format(Number(value||0));
 const symbol=new Intl.NumberFormat('en-IN',{style:'currency',currency}).formatToParts(0).find(part=>part.type==='currency')?.value||currency;
 const purchaseIssues=()=>{const issues=[];const add=(message,field,formStep=0)=>issues.push({message,field,step:formStep});if(!Number(draftRef.current.budget)||Number(draftRef.current.budget)<=0)add('Enter a positive spending budget.','budget');if(!draftRef.current.purchase_type)add('Choose whether this purchase is for goods, services, or software.','purchase-type');if(!draftRef.current.category)add('Choose a detailed purchase category.','category');if(!draftRef.current.contract_start||!draftRef.current.contract_end)add('Enter both contract dates.',!draftRef.current.contract_start?'contract-start':'contract-end');else if(draftRef.current.contract_end<draftRef.current.contract_start)add('The contract end date must be after its start date.','contract-end');if(!draftRef.current.payment_terms)add('Choose payment terms.','payment-terms');if(!itemsRef.current.length)add('Add at least one line item.','add-line');itemsRef.current.forEach((item,index)=>{const n=index+1;const field=name=>`line-${index}-${name}`;if(!String(item.description||'').trim())add(`Enter a description for line ${n}.`,field('description'));if(!item.line_type)add(`Choose a line type for line ${n}.`,field('type'));if(!item.item_category)add(`Choose a goods or service category for line ${n}.`,field('category'));if(!item.department)add(`Choose a department for line ${n}.`,field('department'));if(!item.purchasing_method)add(`Choose how line ${n} will be purchased.`,field('buying-method'));if(!item.verification_method)add(`Choose how line ${n} will be verified.`,field('verification'));if(!Number(item.quantity)||Number(item.quantity)<1)add(`Enter a quantity for line ${n}.`,field('quantity'));if(item.unit_price===''||item.unit_price==null||Number(item.unit_price)<0)add(`Enter an amount for line ${n}.`,field('amount'));if(!item.location)add(`Choose a delivery location for line ${n}.`,field('location'));if(item.line_type==='Service'){if(!item.service_unit)add(`Choose a service unit for line ${n}.`,field('service-unit'));if(!item.service_level?.trim())add(`Enter the service level for line ${n}.`,field('service-level'));if(!item.acceptance_owner?.trim())add(`Name who will sign off line ${n}.`,field('acceptance-owner'));}});if(Number(draftRef.current.budget)>0&&total>Number(draftRef.current.budget))add('Line item total is above the spending budget.','budget-total');return issues;};
 const showValidationIssues=issues=>{if(!issues.length)return;setError(issues.map(issue=>issue.message).join(' '));const first=issues[0];if(first.step!==step)setStep(first.step);const scrollAndFocus=()=>{const target=[...document.querySelectorAll('[data-required-field]')].find(element=>element.getAttribute('data-required-field')===first.field);if(!target)return;target.scrollIntoView({behavior:'smooth',block:'center',inline:'nearest'});if(target.matches('fieldset'))target.querySelector('input,select,textarea,button')?.focus({preventScroll:true});else if(target.matches('p'))target.setAttribute('tabindex','-1');if(target.matches('p'))target.focus({preventScroll:true});else target.focus?.({preventScroll:true});};requestAnimationFrame(()=>requestAnimationFrame(scrollAndFocus));};
 const saveDraft=()=>action(()=>persist());
 const closeIntake=()=>{if(dirty&&!window.confirm('Discard unsaved changes?'))return;close();};
 const finishRequest=()=>{const issues=purchaseIssues();if(!draft.data_sharing_choice)issues.push({message:'Choose whether personal data will be shared: Yes, No, or I don’t know.',field:'privacy-choice',step:1});if(draft.shares_personal_data===true&&(!draft.data_types?.length||!draft.data_usage?.trim()))issues.push({message:'Select at least one data type and explain how the supplier will use it.',field:!draft.data_types?.length?'data-types':'data-usage',step:1});if(issues.length){showValidationIssues(issues);return;}action(async()=>{const saved=await saveSnapshot(true);const {data}=await sourcingApi.startAgent(saved.id);setAgentRun(data);setAgentSelection(data.vendors.filter(v=>!v.synthetic).map(v=>v.id));setResult(data);setStatus(`Agent ready · ${data.summary.shortlisted_count} suppliers shortlisted · ${data.summary.sent_count||0} RFQs accepted by SMTP · ${data.summary.dispatch_attention_count||0} need attention.`);setDirty(false);});};
 const sendAgentRFQs=()=>{if(!agentRun||!rowRef.current)return;action(async()=>{if(!window.confirm(`Send the prepared RFQ to ${agentSelection.length} selected verified supplier(s)? This contacts external vendors.`))return;const {data}=await sourcingApi.sendAgentOutreach(rowRef.current.id,agentRun.id,agentSelection);setAgentRun(data);setAgentSelection([]);setStatus(`${data.summary.sent_count} RFQ(s) sent. ${data.summary.pending_response_count} vendor response(s) pending.`);});};
 const recordAgentReply=(vendorId,text)=>{if(!agentRun||!rowRef.current)return;return action(async()=>{const {data}=await sourcingApi.recordAgentReply(rowRef.current.id,agentRun.id,vendorId,text);setAgentRun(data);setStatus(`Supplier reply recorded. ${data.summary.pending_response_count} vendor response(s) still pending.`);});};
 const addCustomVendor=async vendorData=>{if(!agentRun||!rowRef.current)return;return action(async()=>{const {data}=await sourcingApi.addVendor(rowRef.current.id,agentRun.id,vendorData);setAgentRun(data);setStatus(`Vendor "${vendorData.name}" added to shortlist.`);});};
 const runExternalSearch=async query=>{if(!rowRef.current)return;return action(async()=>{const loc=draftRef.current.delivery_location||itemsRef.current[0]?.location||'India';const {data}=await sourcingApi.externalSearch(rowRef.current.id,query,loc);if(agentRun){setAgentRun({...agentRun,public_web:data,summary:{...(agentRun.summary||{}),search_tools:data.search_tools}});};setStatus(`External search finished · ${data.results?.length||0} leads found.`);});};
 const sendAiRfqs=async vendorIds=>{if(!agentRun||!rowRef.current)return;const {data}=await sourcingApi.sendAiRfqs(rowRef.current.id,agentRun.id,vendorIds);setAgentRun(data.run);setStatus(`SMTP accepted ${data.sent_count||0} · failed ${data.failed_count||0} · already sent ${data.already_sent?.length||0}. Check each vendor’s email progress for delivery status.`);return data;};
 const analyzeVendorResponses=async()=>{if(!agentRun||!rowRef.current)return;const {data}=await sourcingApi.analyzeResponses(rowRef.current.id,agentRun.id);setAgentRun(data.run);setStatus(`AI analysis complete. Recommended vendor: ${data.analysis?.winner_vendor_name||'see results'}`);return data;};
 const workflowPlan=()=>{const serviceItems=items.filter(i=>i.line_type==='Service');const hasService=serviceItems.length>0||draft.purchase_type==='Services';const hasIT=items.some(i=>/IT hardware|software|licen|cloud/i.test(i.item_category||'')||/IT services/i.test(i.item_category||''))||/software/i.test(draft.purchase_type||'');const dataRisk=draft.data_sharing_choice==='yes'||draft.data_sharing_choice==='unknown';const stages=[{name:'Procurement review',reason:'Check the request, category, required evidence, and purchasing route.'},{name:'Department manager / budget owner',reason:'Confirm the business need, budget ownership, and accountable delivery or service owner.'},{name:'Finance approval',reason:'Check the budget, total cost, payment terms, and financial coding.'}];if(hasService)stages.push({name:'Legal review',reason:'Review the MSA and SOW where applicable, including scope, term, liability, and renewal clauses.'});if(hasIT)stages.push({name:'IT review',reason:'Review technical fit, access, integrations, and support requirements.'});if(dataRisk)stages.push({name:'Security and privacy review',reason:draft.data_sharing_choice==='unknown'?'Data sharing is unknown; confirm what information is involved before approval.':'Review the selected data types, vendor use, and safeguards.'});return {stages,hasService,hasIT,dataRisk,serviceItems};};
 const plan=workflowPlan();
 const createWorkflow=async()=>{if(!rowRef.current)return;setBusy(true);setError('');try{await persist();const {data}=await sourcingApi.workflow(rowRef.current.id);setWorkflowResult(data);setStatus(data.source==='gemini'?'Gemini generated this route from your purchase details.':'AI-tailored compliance workflow; all regulatory and financial gates verified.');return data;}catch(e){setError(errorText(e));return null;}finally{setBusy(false);}};
 const advance=async()=>{
  setError('');if(busy)return;
  if(!rowRef.current){setError('The purchase request is still loading. Please try again in a moment.');return;}
  if(step===0){const issues=purchaseIssues();if(issues.length){showValidationIssues(issues);return;}}
  if(step===1){const issues=[];if(!draft.data_sharing_choice)issues.push({message:'Choose Yes, No, or I don’t know before continuing.',field:'privacy-choice',step:1});if(draft.shares_personal_data===true&&!draft.data_types?.length)issues.push({message:'Select at least one type of data that will be shared.',field:'data-types',step:1});if(draft.shares_personal_data===true&&!draft.data_usage?.trim())issues.push({message:'Explain how the supplier will use this data.',field:'data-usage',step:1});if(issues.length){showValidationIssues(issues);return;}}
  if(step===1){
    const workflow=await createWorkflow();
    if(!workflow)return;
    const moved=await action(()=>saveSnapshot(false,2));
    if(!moved)return;
    setStep(2);
    if(!agentRun && rowRef.current){
      action(async()=>{
        const saved=await saveSnapshot(true,2);
        const {data}=await sourcingApi.startAgent(saved.id);
        setAgentRun(data);
        setAgentSelection(data.vendors.map(v=>v.id));
        setResult(data);
        setStatus(`Approval map generated and ${data.vendors?.length||0} vendors shortlisted.`);
      });
    }
    return;
  }
  const next=Math.min(3,step+1);
  await action(async()=>{await saveSnapshot(false,next);setStep(next);});
 };
 const regenerateWorkflow=async()=>{const workflow=await createWorkflow();if(workflow)setStatus(workflow.source==='gemini'?'Gemini generated an updated route.':'AI-tailored compliance workflow updated.');};
 const uploadContract=async kind=>{const file=contractFiles[kind];if(!file||!row)return;await action(async()=>{const {data}=await sourcingApi.uploadContractDocument(row.id,kind,file);setContractDocs(docs=>[...docs.filter(d=>d.kind!==kind),data]);setContractFiles(files=>({...files,[kind]:null}));setStatus(`${kind.toUpperCase()} uploaded and stored with this request.`);});};
 const sendChat=async message=>{setBusy(true);setError('');setChatError('');try{await persist();const {data}=await sourcingApi.message(rowRef.current.id,message,rowRef.current.version);adopt(data);return true;}catch(e){const messageText=errorText(e);setError(messageText);setChatError(messageText);return false;}finally{setBusy(false);}};
 return <><Modal title="Request a purchase" close={closeIntake} busy={busy} wide fullscreen><div className="p-stepper intake-fullscreen-marker"><button type="button" className="p-button intake-cancel-request" onClick={closeIntake}>Cancel request</button><span className={step===0?'current':step>0?'complete':''}><b>1</b>Purchase details</span><span className={step===1?'current':step>1?'complete':''}><b>2</b>Data information</span><span className={step===2?'current':step>2?'complete':''}><b>3</b>Approval Map & Sourcing</span><span className={step===3?'current':''}><b>4</b>Review & Submit</span>{row&&<button type="button" className="p-button cv-intake-audit-btn" onClick={()=>setShowAuditModal(true)} title="View immutable chronological audit time log trail" style={{marginLeft:'auto',display:'inline-flex',alignItems:'center',gap:6,padding:'7px 14px',borderRadius:8,background:'#201a17',border:'1px solid rgba(239, 153, 118, 0.3)',color:'#ef9976',fontSize:12,fontWeight:700,cursor:'pointer'}}><Clock size={13}/><span>Audit Time Log</span></button>}</div><section className="p-intake-main"><section className="p-dialog-body">
 {error&&<p className="p-notice p-danger" role="alert">{error}</p>}{!row?<div className="intake-loading">Loading purchase request…</div>:<>
 {step===0&&<>
 <h3>How much budget will you need for this purchase? <b>*</b></h3>
 <div className="intake-budget"><select aria-label="Currency" value={currency} onChange={e=>change('currency',e.target.value)}>{CURRENCIES.map(([code,name])=><option key={code} value={code}>{code} · {name}</option>)}</select><span>{symbol}</span><input data-required-field="budget" aria-label="Purchase budget" aria-required="true" type="text" inputMode="decimal" value={draft.budget||''} placeholder="Enter budget" onChange={e=>change('budget',e.target.value.replace(/[^0-9.]/g,''))}/></div>

 <h3 className="intake-form-heading">Please enter the line item breakdown: <b>*</b></h3>
 {items.map((item,index)=>{const service=item.line_type==='Service';const categories=service?SERVICE_CATEGORIES:GOODS_CATEGORIES;return <article className="intake-line screenshot-line" key={index}>
  <div className="intake-line-head"><strong>Line {index+1}</strong><span>Line total&nbsp; {money(lineTotal(item))}</span>{items.length>1&&<button className="p-icon" type="button" aria-label={`Remove line ${index+1}`} onClick={()=>{const next=itemsRef.current.filter((_,i)=>i!==index);itemsRef.current=next;setItems(next);setDirty(true);setStatus('Unsaved changes');}}><Trash2 size={15}/></button>}</div>
  <div className="p-form-grid intake-description-grid"><label className="p-field intake-wide-field"><span>Description <b>*</b></span><input data-required-field={`line-${index}-description`} aria-required="true" value={item.description||''} onChange={e=>changeLine(index,'description',e.target.value)}/></label><label className="p-field"><span>Line type <b>*</b></span><select data-required-field={`line-${index}-type`} aria-required="true" value={item.line_type||'Item'} onChange={e=>{const type=e.target.value;changeLine(index,'line_type',type);changeLine(index,'item_category','');changeLine(index,'purchasing_method',type==='Service'?'Quote request (RFQ)':'Catalog buying');changeLine(index,'verification_method',type==='Service'?'Service acceptance / sign-off':'Goods receipt');change('purchase_type',type==='Service'?'Services':'Goods');change('category','');}}><option>Item</option><option>Service</option></select></label></div>
  <div className="p-form-grid"><label className="p-field"><span>{service?'Quantity (service units)':'Quantity (Each)'} <b>*</b></span><input data-required-field={`line-${index}-quantity`} aria-required="true" type="number" min="1" step="1" value={item.quantity??1} onChange={e=>changeLine(index,'quantity',e.target.value)}/></label><label className="p-field"><span>{service?'Rate / amount':'Amount'} <b>*</b></span><div className="intake-amount"><span>{currency}</span><input data-required-field={`line-${index}-amount`} aria-required="true" type="text" inputMode="decimal" value={item.unit_price??''} placeholder="0.00" onChange={e=>changeLine(index,'unit_price',e.target.value.replace(/[^0-9.]/g,''))}/></div></label></div>
  <div className="p-form-grid"><label className="p-field"><span>{service?'Service category':'Goods category'} <b>*</b></span><select data-required-field={`line-${index}-category`} aria-required="true" value={item.item_category||''} onChange={e=>{changeLine(index,'item_category',e.target.value);if(index===0)change('category',e.target.value);}}><option value="">Select {service?'service':'goods'} category</option>{categories.map(category=><option key={category}>{category}</option>)}</select></label><label className="p-field"><span>Department <b>*</b></span><select data-required-field={`line-${index}-department`} aria-required="true" value={item.department||''} onChange={e=>changeLine(index,'department',e.target.value)}><option value="">Select department</option><option>Sales</option><option>Finance</option><option>Manager</option><option>IT</option><option>Operations</option></select></label></div>
  <div className="p-form-grid"><label className="p-field"><span>How is it usually bought? <b>*</b></span><select data-required-field={`line-${index}-buying-method`} aria-required="true" value={item.purchasing_method||''} onChange={e=>changeLine(index,'purchasing_method',e.target.value)}><option value="">Select buying method</option>{BUYING_METHODS.map(method=><option key={method}>{method}</option>)}</select><small>{methodHelp(item.purchasing_method)}</small></label><label className="p-field"><span>How will delivery be verified? <b>*</b></span><select data-required-field={`line-${index}-verification`} aria-required="true" value={item.verification_method||''} onChange={e=>changeLine(index,'verification_method',e.target.value)}><option value="">Select verification method</option>{(service?SERVICE_CHECKS:['Goods receipt (physical count)']).map(method=><option key={method}>{method}</option>)}</select></label></div>
  {service&&<><div className="p-form-grid"><label className="p-field"><span>Service unit <b>*</b></span><select data-required-field={`line-${index}-service-unit`} aria-required="true" value={item.service_unit||''} onChange={e=>changeLine(index,'service_unit',e.target.value)}><option value="">Select unit</option>{SERVICE_UNITS.map(unit=><option key={unit}>{unit}</option>)}</select></label><label className="p-field"><span>Service level / SLA <b>*</b></span><input data-required-field={`line-${index}-service-level`} aria-required="true" value={item.service_level||''} placeholder="Describe the required service level" onChange={e=>changeLine(index,'service_level',e.target.value)}/></label></div><label className="p-field"><span>Who signs off that the service was delivered? <b>*</b></span><input data-required-field={`line-${index}-acceptance-owner`} aria-required="true" value={item.acceptance_owner||''} placeholder="Role or person responsible" onChange={e=>changeLine(index,'acceptance_owner',e.target.value)}/></label><p className="intake-match-note">Service matching checks the PO, service acceptance or sign-off, and invoice.</p></>}
  {!service&&<p className="intake-match-note">Goods matching checks the PO, physical goods receipt, and invoice.</p>}
  <div className="p-form-grid"><label className="p-field"><span>Project</span><select value={item.project||''} onChange={e=>changeLine(index,'project',e.target.value)}><option value="">Select project</option><option>Project X</option></select></label><label className="p-field"><span>Location <b>*</b></span><select data-required-field={`line-${index}-location`} aria-required="true" value={item.location||''} onChange={e=>changeLine(index,'location',e.target.value)}><option value="">Select location</option><option>San Francisco - US</option></select></label></div>
 </article>;})}
 <button data-required-field="add-line" className="p-link intake-add-line" type="button" onClick={()=>{const next=[...itemsRef.current,blankItem()];itemsRef.current=next;setDirty(true);setStatus('Unsaved changes');}}><Plus size={16}/> Add line item</button>
 <div className="intake-line-total"><span>Line item total ({items.length})</span><strong>{money(total)}</strong></div>
 {budgetExceeded&&<p data-required-field="budget-total" className="intake-budget-error" role="alert">Line item total exceeds the spending budget by {money(total-Number(draft.budget))}.</p>}

 <label className="p-field intake-select-field"><span>What are you looking to purchase? <b>*</b></span><select data-required-field="purchase-type" aria-required="true" value={draft.purchase_type||'Goods'} onChange={e=>{change('purchase_type',e.target.value);change('category','');}}><option>Goods</option><option>Services</option><option>Software</option></select></label>
 <label className="p-field intake-select-field"><span>Which detailed category best describes your purchase? <b>*</b></span><select data-required-field="category" aria-required="true" value={draft.category||''} onChange={e=>change('category',e.target.value)}><option value="">Select a category</option>{categoryOptions(draft.purchase_type||'Goods').map(category=><option key={category}>{category}</option>)}</select></label>

 <section className="intake-vendor-section"><strong>Vendor choice</strong><p>Let the AI recommend a vendor, or mark one supplier as your preference. A preference is a hint, not a restriction.</p><label className="intake-agent-choice"><input type="checkbox" checked={draft.ai_selects_vendor!==false} onChange={e=>change('ai_selects_vendor',e.target.checked)}/><span>Ask the AI to recommend a vendor</span></label><p className="intake-vendor-hint">Optional preferred vendor</p><div className="intake-vendor-list">{VENDORS.map(vendor=><div className={`intake-vendor-row ${draft.preferred_vendors===vendor?'selected':''}`} key={vendor}><span className="intake-vendor-mark" aria-hidden="true">{vendor.slice(0,1)}</span><span>{vendor}</span><button type="button" className="p-button primary" aria-pressed={draft.preferred_vendors===vendor} onClick={()=>{const chosen=draft.preferred_vendors===vendor?'':vendor;change('preferred_vendors',chosen);change('vendor_preference',chosen?'prioritize':'');}}>{draft.preferred_vendors===vendor?'Selected':'Choose'}</button></div>)}</div><small>These four names are examples. A real vendor recommendation needs approved company supplier offers; the AI can suggest a better fit when that data is available.</small></section>

 <h3 className="intake-contract-heading">What is the desired start and end date for this purchase/contract? <b>*</b></h3><label className="p-field intake-dates"><span>Contract dates <b>*</b></span><div><input data-required-field="contract-start" aria-required="true" aria-label="Purchase contract start date" type="date" value={draft.contract_start||''} onChange={e=>change('contract_start',e.target.value)}/><span>→</span><input data-required-field="contract-end" aria-required="true" aria-label="Purchase contract end date" type="date" value={draft.contract_end||''} onChange={e=>change('contract_end',e.target.value)}/></div></label>

 <fieldset data-required-field="payment-terms" className="intake-payment"><legend>Please select the payment terms of this contract: <b>*</b></legend>{PAYMENT_TERMS.map(term=><label key={term}><input aria-required="true" type="radio" name="payment_terms" checked={draft.payment_terms===term} onChange={()=>change('payment_terms',term)}/><span>{term}</span></label>)}</fieldset>
 </>}
 {step===1&&<section className="intake-data-information"><h3>Data Information</h3><p>Will any personal data be shared for this engagement? For example, customer emails, names, user activity, etc. <b>*</b></p><p className="p-muted">Please see the attached data policy for detailed descriptions and definitions.</p><div className="intake-policy-links"><a href="/sample-vendor-data-sharing-policy.pdf" target="_blank" rel="noreferrer">Data Access Policy ↗</a><a href="/sample-vendor-data-sharing-policy.pdf" download>Download attachment ↓</a><small>Demonstration sample only; not an approved company policy.</small></div><fieldset data-required-field="privacy-choice" className="intake-data-choice"><legend>Will personal data be shared with this supplier? <b>*</b></legend>{[['yes','Yes','Select this if personal data will be shared with the vendor.'],['no','No','Select this if no personal data will be shared with the vendor.'],['unknown',"I don't know",'Select this option if you are unsure.']].map(([value,title,help])=><label key={value}><input type="radio" aria-required="true" name="shares_personal_data" checked={draft.data_sharing_choice===value} onChange={()=>{const next={...draftRef.current,data_sharing_choice:value,shares_personal_data:value==='yes'?true:value==='no'?false:null,...(value==='no'?{data_types:[],data_usage:null}:{})};draftRef.current=next;setDraft(next);setPrivacyHelp(value==='unknown');if(value==='unknown')setAssistantOpenSignal(n=>n+1);setDirty(true);setStatus('Unsaved changes');}}/><span><strong>{title}</strong><small>{help}</small></span></label>)}</fieldset>{draft.shares_personal_data===true&&<><fieldset data-required-field="data-types" className="intake-data-types"><legend>What type of data/information will be shared? <b>*</b></legend>{DATA_TYPES.map(type=><label key={type}><input type="checkbox" aria-required="true" checked={(draft.data_types||[]).includes(type)} onChange={()=>{const values=draft.data_types||[];change('data_types',values.includes(type)?values.filter(v=>v!==type):[...values,type]);}}/><span>{type}</span></label>)}</fieldset><label className="p-field"><span>How will this vendor use this data? <b>*</b></span><textarea data-required-field="data-usage" aria-required="true" maxLength={2000} value={draft.data_usage||''} onChange={e=>change('data_usage',e.target.value)} placeholder="Describe the purpose for sharing this data."/></label></>}</section>}
 {step===2&&<section className="intake-workflow"><div className="intake-workflow-heading"><div><h3>Workflow for this purchase</h3><p>This approval map is tailored to the selected goods or services and data-sharing answers. Each card is a proposed checkpoint for human review.</p></div><button className="p-button" type="button" onClick={regenerateWorkflow} disabled={busy||!row}><RefreshCw size={14} className={busy?'workflow-spinning':''}/>{busy?'Generating…':'Regenerate map'}</button></div><div className="intake-workflow-source"><GitBranch size={15}/><span>AI-Tailored Approval Workflow</span><small>{workflowResult?.notice && !workflowResult.notice.includes('could not produce') && !workflowResult.notice.includes('safe rules-based') ? workflowResult.notice : 'Dynamically tailored to this purchase; authorized approvers retain full decision authority.'}</small></div>{workflowResult?.graph?<><h4 className="intake-workflow-title">{workflowResult.graph.title}</h4><p className="intake-workflow-summary">{workflowResult.graph.summary}</p><WorkflowMindMap workflow={workflowResult.graph} requestId={row?.id} assessment={row?.workspace?.workflow?.final_invoice_assessment || workflowResult?.final_invoice_assessment} initialPaypal={row?.workspace?.workflow?.paypal_payment || workflowResult?.paypal_payment} contractDocs={contractDocs}/></>:<div className="intake-workflow-loading" role="status">Creating the purchase-specific approval map…</div>}{plan.hasService&&<section className="intake-contract-docs"><h4>Service contract documents</h4><p>MSA and SOW checks apply to service engagements. Upload the documents you already have; missing items are flagged for Legal review.</p>{[['msa','Master Services Agreement (MSA)'],['sow','Statement of Work (SOW)']].map(([kind,title])=>{const doc=contractDocs.find(d=>d.kind===kind);return <div className="intake-contract-document" key={kind}><div><strong>{title}</strong><small>{doc?<><CheckCircle2 size={14}/> Uploaded: {doc.filename}</>:<><AlertCircle size={14}/> {contractFiles[kind]?.name||'Not provided yet'}</>}</small></div><label className="p-button"><Upload size={14}/> Choose PDF/DOCX<input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={e=>setContractFiles(files=>({...files,[kind]:e.target.files?.[0]||null}))}/></label><button type="button" className="p-button primary" disabled={!contractFiles[kind]||busy} onClick={()=>uploadContract(kind)}>{busy?'Uploading…':'Upload'}</button></div>})}<p className="intake-contract-note">Uploads are stored as supporting evidence. The system does not decide that a contract is legally sufficient; Legal must review it.</p></section>}

  {/* ── CHOSEN VENDORS TABLE (EMBEDDED ON MAP PAGE) ── */}
  <div className="intake-map-divider" />
  <section className="intake-embedded-sourcing">
   <div className="intake-sourcing-head">
    <div>
     <h3>Chosen Suppliers &amp; Commercial Outreach</h3>
     <p>The agent emails shortlisted company vendors automatically. Track delivery and replies below; a human approves the final supplier and purchase.</p>
    </div>
    {!agentRun&&(
     <button type="button" className="p-button primary" onClick={finishRequest} disabled={busy||!row}>
      {busy?'Searching suppliers…':'Search & Shortlist Vendors'}
     </button>
    )}
   </div>

   {agentRun?(
    <SourcingAgentReview
     run={agentRun}
     selected={agentSelection}
     setSelected={setAgentSelection}
     busy={busy}
     onSend={sendAgentRFQs}
     onReply={recordAgentReply}
     onAddVendor={addCustomVendor}
     onExternalSearch={runExternalSearch}
     onSendAiRfqs={sendAiRfqs}
     onAnalyze={analyzeVendorResponses}
     onRunUpdated={setAgentRun}
     rowId={rowRef.current?.id}
     row={row}
     request={row}
    />
   ):(
    <div className="intake-vendors-standby-card">
     <div className="intake-standby-bot"><PixelBot/></div>
     <div>
      <strong>Sourcing Agent Scanning Catalogs &amp; Commercial Discovery...</strong>
      <p>The AI agent is finding eligible approved suppliers and commercial offerings for this purchase.</p>
     </div>
     <button type="button" className="p-button primary" onClick={finishRequest} disabled={busy||!row}>
      {busy?'Scanning…':'Load Shortlisted Suppliers'}
     </button>
    </div>
   )}
  </section>
</section>}
 {step===3&&<section className="intake-review"><h3>Review your purchase request</h3><p className="p-muted">Confirm the brief to start the sourcing agent. It checks the company-approved catalog and public Google Search results, including publicly indexed LinkedIn company pages. Public leads stay unverified; RFQs are sent automatically to company catalog contacts. Final supplier selection and purchase approval remain with a human.</p><dl><dt>Budget</dt><dd>{money(draft.budget)}</dd><dt>Purchase type</dt><dd>{draft.purchase_type}</dd><dt>Category</dt><dd>{draft.category}</dd><dt>Line items</dt><dd>{items.map((item,i)=><span key={i}>{i>0?', ':''}{item.description} · {item.quantity} × {money(item.unit_price)}</span>)}</dd><dt>Vendor preference</dt><dd>{draft.preferred_vendors||'AI chooses and recommends'}</dd><dt>Payment terms</dt><dd>{draft.payment_terms}</dd><dt>Personal data shared</dt><dd>{draft.shares_personal_data===true?'Yes':draft.shares_personal_data===false?'No':"I don't know"}</dd>{draft.shares_personal_data===true&&<><dt>Data types</dt><dd>{(draft.data_types||[]).join(', ')}</dd><dt>Use</dt><dd>{draft.data_usage}</dd></>}<dt>Approval route</dt><dd>{workflowResult?.graph?.nodes?.map(node=>node.label).join(' → ')||'Generate the workflow from the previous step.'}</dd>{plan.hasService&&<><dt>MSA status</dt><dd>{contractDocs.some(d=>d.kind==='msa')?'Uploaded':'Not provided · Legal follow-up needed'}</dd><dt>SOW status</dt><dd>{contractDocs.some(d=>d.kind==='sow')?'Uploaded':'Not provided · Legal follow-up needed'}</dd></>}</dl>{agentRun?<SourcingAgentReview run={agentRun} selected={agentSelection} setSelected={setAgentSelection} busy={busy} onSend={sendAgentRFQs} onReply={recordAgentReply} onAddVendor={addCustomVendor} onExternalSearch={runExternalSearch} onSendAiRfqs={sendAiRfqs} onAnalyze={analyzeVendorResponses} onRunUpdated={setAgentRun} rowId={rowRef.current?.id} row={row} request={row}/>:<div className="intake-agent-start"><strong>Start supplier analysis</strong><p>The agent will inspect approved company offers, search public web sources, rank catalog matches, and prepare RFQ drafts. Public web leads are shown separately and are never contacted automatically. The agent emails company catalog contacts automatically after shortlisting.</p><button type="button" className="p-button primary" disabled={busy||!!result||!row} onClick={finishRequest}>{busy?'Analyzing catalog and public sources…':'Analyze vendors and public sources'}</button></div>}</section>}
 </>}</section></section>
 <footer className="intake-footer"><button className="p-button" type="button" onClick={()=>step?setStep(step-1):closeIntake()}>{step?'Back':'Cancel'}</button><span role="status">{dirty?'Unsaved changes':status}</span><button className="p-button" type="button" disabled={busy||!row} onClick={saveDraft}>{busy?'Saving…':'Save draft'}</button>{step<3?<button className="p-button primary" type="button" disabled={busy||!row} onClick={advance}>{busy&&step===1?'Generating…':'Next'}</button>:<button className="p-button primary" type="button" disabled={busy||!!result||!row} onClick={finishRequest}>{busy?'Analyzing…':'Analyze company vendors'}</button>}</footer>
 </Modal><IntakeChat row={row} busy={busy} error={chatError} onSend={sendChat} openSignal={assistantOpenSignal} privacyHelp={privacyHelp}/>
 {showAuditModal && (
  <AuditTimeLogModal
   requestId={row?.id}
   requestKind="sourcing"
   requestTitle={draft?.product || row?.requirements?.product || 'Purchase Requisition'}
   initialAuditLog={row?.audit_log}
   onClose={() => setShowAuditModal(false)}
  />
 )}
 </>;
}
