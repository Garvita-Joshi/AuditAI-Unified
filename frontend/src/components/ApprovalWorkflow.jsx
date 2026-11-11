import React, { useMemo, useState } from 'react';
import { ArrowRight, CalendarDays, Check, Circle, Clock3, MoreHorizontal, Pencil, ShieldCheck, X } from 'lucide-react';

const pretty = value => String(value || '').replaceAll('_', ' ');
const dateValue = value => value ? new Date(value).toLocaleDateString() : 'Not set';
const spentDays = step => step.started_at ? Math.max(0, Math.floor((Date.now() - new Date(step.started_at).getTime()) / 86400000)) : 0;

export function StepCard({ step, current, onOpen, onApprove, canApprove }) {
  const complete = step.status === 'approved';
  const overdue = !complete && new Date(step.due_date) < new Date();
  const activeDays = spentDays(step);
  const ready = ['ready', 'in_progress'].includes(step.status);
  const requiredDone = step.subtasks.filter(item => item.required).every(item => ['done', 'not_needed'].includes(item.status));
  return <article className={`approval-step-card ${current ? 'is-current' : ''} ${step.status}`}>
    <button type="button" className="approval-step-open" onClick={() => onOpen(step.id)} aria-label={`Open ${step.name} details`}>
      <span className={`approval-step-icon ${complete ? 'done' : ready ? 'ready' : ''}`}>{complete ? <Check size={15}/> : ready ? <Clock3 size={15}/> : <Circle size={14}/>}</span>
      <span className={`approval-step-status ${step.status}`}>{pretty(step.status)}</span>
      <strong>{step.name}</strong>
      <span className="approval-step-assignee"><Pencil size={12}/>{step.assignee?.name || `Unassigned · ${step.role}`}</span>
      {step.department_head && <span className="approval-step-department-head">Department head · {step.department_head.name}</span>}
      <span className={`approval-step-due ${overdue ? 'overdue' : ''}`}><CalendarDays size={13}/>{`Due ${dateValue(step.due_date)} · ${activeDays}d active`}</span>
    </button>
    <div className="approval-step-actions">
      <button type="button" className="p-button primary" onClick={() => onApprove(step)} disabled={!ready || !canApprove || !requiredDone}>Approve</button>
      <button type="button" className="p-button" onClick={() => onOpen(step.id)} aria-label={`More actions for ${step.name}`}><MoreHorizontal size={17}/></button>
    </div>
  </article>;
}

export function WorkflowView({ steps = [], user, requesterId, requester, departmentHead, onOpen, onApprove }) {
  const current = steps.find(step => !['approved', 'rejected'].includes(step.status));
  const canApprove = step => !!user && (user.role === 'admin' || user.email === 'prepares23@gmail.com' || (user.id !== requesterId &&
    (user.role === step.role && (!step.assignee || step.assignee.id === user.id))));
  return <section className="approval-workflow" aria-label="Approval workflow">
    <div className="approval-workflow-heading"><div><h2>Approval workflow</h2><p className="p-muted">AI may prepare recommendations. Each approval decision belongs to an authorized human.</p></div><span className="p-muted">{steps.filter(step => step.status === 'approved').length} / {steps.length} approved</span></div>
    {(requester?.name || departmentHead?.name) && <div className="approval-workflow-people">
      {requester?.name && <span><small>Requested by</small><strong>{requester.name}</strong>{requester.email && <small>{requester.email}</small>}</span>}
      {departmentHead?.name && <span><small>Department head</small><strong>{departmentHead.name}</strong>{departmentHead.is_backup && <small>Acting backup · {departmentHead.department}</small>}</span>}
    </div>}
    <div className="approval-workflow-cards">{steps.map((step, index) => <React.Fragment key={step.id}>
      {index > 0 && <ArrowRight className="approval-flow-arrow" size={18} aria-hidden="true"/>}
      <StepCard step={step} current={current?.id === step.id} onOpen={onOpen} onApprove={onApprove} canApprove={canApprove(step)}/>
    </React.Fragment>)}</div>
    {!steps.length && <p className="p-muted">Approval steps will be initialized when the request is opened.</p>}
  </section>;
}

export function StepDetailPanel({ step, request, reviewers = [], events = [], onClose, onSave, onSubtask, onDecision, busy, user }) {
  const [reason, setReason] = useState('');
  const [assigneeId, setAssigneeId] = useState(step?.assignee?.id ? String(step.assignee.id) : '');
  const [dueDate, setDueDate] = useState(step?.due_date?.slice(0, 10) || '');
  const [status, setStatus] = useState(step?.status || 'not_started');
  const current = request.approval_steps?.find(item => !['approved', 'rejected'].includes(item.status));
  const isCurrent = current?.id === step?.id;
  const canAct = !!user && (user.role === 'admin' || user.email === 'prepares23@gmail.com' || (user.id !== request.requester_id &&
    (user.role === step.role && (!step.assignee || step.assignee.id === user.id))));
  const requiredComplete = step.subtasks.filter(item => item.required).every(item => ['done', 'not_needed'].includes(item.status));
  const hasStepChanges = (assigneeId ? Number(assigneeId) : null) !== (step.assignee?.id || null) ||
    dueDate !== (step.due_date?.slice(0, 10) || '') || status !== step.status;
  const elapsed = spentDays(step);
  const overdue = !['approved', 'rejected'].includes(step.status) && new Date(step.due_date) < new Date();
  const stepEvents = useMemo(() => events.filter(item => item.details?.step_id === step.id).slice(0, 8), [events, step.id]);
  if (!step) return null;
  const submitChanges = () => {
    const changes = { reason };
    const nextAssignee = assigneeId ? Number(assigneeId) : null;
    if (nextAssignee !== (step.assignee?.id || null)) changes.assignee_id = nextAssignee;
    if (dueDate !== (step.due_date?.slice(0, 10) || '')) changes.due_date = dueDate ? new Date(`${dueDate}T23:59:59`).toISOString() : null;
    if (status !== step.status) changes.status = status;
    onSave(step, changes);
  };
  return <div className="approval-panel-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="approval-detail-panel" role="dialog" aria-modal="true" aria-label={`${step.name} details`}>
      <header><div><small>APPROVAL STEP {step.order}</small><h2>{step.name}</h2></div><button type="button" className="p-icon" aria-label="Close step details" onClick={onClose}><X size={19}/></button></header>
      <div className="approval-panel-scroll">
        <div className="approval-panel-status-row"><span className={`approval-step-status ${step.status}`}>{pretty(step.status)}</span><span className={`approval-sla ${overdue ? 'overdue' : ''}`}>{elapsed}/{step.sla_days} SLA days used</span></div>
        <label className="p-field"><span>Assignee</span><select value={assigneeId} onChange={event => setAssigneeId(event.target.value)} disabled={step.status === 'approved' || user?.role !== 'admin'}><option value="">Unassigned</option>{reviewers.map(person => <option key={person.id} value={person.id}>{person.name} · {person.role}</option>)}</select></label>
        <div className="p-form-grid approval-edit-grid"><label className="p-field"><span>Due date</span><input type="date" value={dueDate} onChange={event => setDueDate(event.target.value)} disabled={step.status === 'approved' || user?.role !== 'admin'}/></label><label className="p-field"><span>Status</span><select value={status} onChange={event => setStatus(event.target.value)} disabled={user?.role !== 'admin' || ['approved','rejected'].includes(step.status)}><option value="not_started">Not started</option><option value="ready">Ready</option><option value="in_progress">In progress</option></select></label></div>
        <label className="p-field"><span>Change reason <small>(optional for edits)</small></span><input value={reason} onChange={event => setReason(event.target.value)} maxLength={3000} placeholder="Add context for reassignment or due-date changes"/></label>
        {user?.role === 'admin' && step.status !== 'approved' && <button className="p-button" type="button" disabled={busy || !hasStepChanges} onClick={submitChanges}><Pencil size={14}/> Save step details</button>}
        <div className="approval-subtasks"><div className="p-row"><h3>{step.subtasks.length} subtasks</h3><span className="p-muted">Required tasks must be completed before approval.</span></div>
          {step.subtasks.map(item => <article className="approval-subtask" key={item.id}><div className="p-row"><strong>{item.title}{item.required ? ' · Required' : ' · Optional'}</strong><span className={`approval-subtask-status ${item.status}`}>{pretty(item.status)}</span></div><p>{item.instructions}</p><small>Owner: {item.assignee?.name || `Unassigned · ${step.role}`}</small>
            <div className="approval-subtask-actions"><button className="p-button" type="button" disabled={busy || !canAct || item.status === 'done'} onClick={() => onSubtask(step, item, 'done')}>Mark done</button><button className="p-button" type="button" disabled={busy || !canAct || item.status === 'not_needed'} onClick={() => onSubtask(step, item, 'not_needed')}>Not needed</button></div></article>)}
        </div>
        <section className="approval-decision-box"><h3>Human decision</h3><p className="p-muted">The AI does not approve requests. Rejecting or sending back requires a reason.</p><label className="p-field"><span>Decision reason</span><textarea value={reason} onChange={event => setReason(event.target.value)} maxLength={3000} placeholder="Enter a reason for rejection or send-back"/></label><div className="approval-decision-actions"><button className="p-button primary" disabled={busy || !canAct || !isCurrent || !requiredComplete || !['ready','in_progress'].includes(step.status)} onClick={() => onDecision(step, 'approve', reason)}>Approve</button><button className="p-button danger" disabled={busy || !canAct || !isCurrent || !reason.trim()} onClick={() => onDecision(step, 'reject', reason)}>Reject</button><button className="p-button" disabled={busy || !canAct || !isCurrent || !reason.trim()} onClick={() => onDecision(step, 'send_back', reason)}>Send back</button></div></section>
        <section className="approval-audit"><h3>Step activity</h3>{stepEvents.length ? stepEvents.map(event => <div className="approval-audit-event" key={event.id}><span/><div><strong>{pretty(event.action)}</strong><small>{new Date(event.created_at).toLocaleString()} · {event.actor || event.actor_name || (event.actor_id ? `User #${event.actor_id}` : 'System')}</small>{event.details?.reason && <p>{event.details.reason}</p>}</div></div>) : <p className="p-muted">No actions recorded for this step yet.</p>}</section>
      </div>
    </aside>
  </div>;
}
