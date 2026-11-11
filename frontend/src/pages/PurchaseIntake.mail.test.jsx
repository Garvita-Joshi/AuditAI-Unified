import React, {useState} from 'react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {SourcingAgentReview} from './PurchaseIntake';
import {sourcingApi} from '../api/client';

vi.mock('../components/VendorCRM', () => ({SourcingDashboard: () => null, VendorRecord: () => null}));
vi.mock('../api/client', () => ({sourcingApi: {reviewRfq: vi.fn(), checkInbox: vi.fn()}}));

const supplier = {id:11, name:'Company supplier', email:'supplier@business.com',
  status:'needs_vendor_confirmation', rfq_approved:false, sent_at:null,
  rfq_subject:'Headsets quotation', rfq_body:'Please quote for ten headsets.', offer:{}};
const makeRun = (overrides={}) => ({id:7, vendors:[{...supplier,...overrides}],
  summary:{}, timeline:[], mailbox:{configured:true}});

function Workspace({initialRun=makeRun(), send}) {
  const [run,setRun] = useState(initialRun);
  return <SourcingAgentReview run={run} rowId={28} selected={[]} setSelected={()=>{}}
    onRunUpdated={setRun} onSendAiRfqs={send}/>;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.location.hash = '#sourcing/7/vendor/11/email/progress';
  vi.spyOn(window,'confirm').mockReturnValue(true);
  sourcingApi.checkInbox.mockResolvedValue({data:{}});
});
afterEach(() => {cleanup();vi.restoreAllMocks();window.location.hash='';});

it('syncs pending RFQs automatically and shows the server send status without approval', async () => {
  sourcingApi.checkInbox.mockResolvedValue({data:{run:makeRun({status:'rfq_sent',sent_at:'2026-11-06T11:00:00Z'})}});
  render(<Workspace send={vi.fn()}/>);
  await waitFor(() => expect(screen.getByText('✓ SMTP accepted · delivery unconfirmed')).toBeTruthy());
  expect(sourcingApi.checkInbox).toHaveBeenCalledWith(28,7);
  expect(screen.queryByRole('button',{name:'Approve email'})).toBeNull();
  expect(sourcingApi.reviewRfq).not.toHaveBeenCalled();
  expect(window.confirm).not.toHaveBeenCalled();
});

it('saves edited drafts and retries directly without an approval or confirmation step', async () => {
  const user=userEvent.setup();
  sourcingApi.reviewRfq.mockResolvedValue({data:makeRun({status:'draft_ready'})});
  const send=vi.fn().mockResolvedValue({sent_count:1,failed_count:0,results:[],
    run:makeRun({status:'rfq_sent',sent_at:'2026-11-06T11:00:00Z'})});
  render(<Workspace initialRun={makeRun({status:'send_failed'})} send={send}/>);
  await user.type(screen.getByRole('textbox',{name:'RFQ message'}),' Updated quantity.');
  await user.click(screen.getByRole('button',{name:'Retry email'}));
  expect(sourcingApi.reviewRfq).toHaveBeenCalledWith(28,7,11,{
    subject:supplier.rfq_subject,body:supplier.rfq_body+' Updated quantity.',recipient_email:supplier.email});
  expect(send).toHaveBeenCalledWith([11]);
  expect(window.confirm).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.queryByRole('button',{name:'Retry email'})).toBeNull());
});

it('shows a failed send and keeps the draft available for retry', async () => {
  const user=userEvent.setup();
  const send=vi.fn().mockRejectedValue({response:{data:{detail:'SMTP certificate verification failed'}}});
  render(<Workspace initialRun={makeRun({status:'send_failed'})} send={send}/>);
  await user.click(screen.getByRole('button',{name:'Retry email'}));
  await waitFor(() => expect(screen.getAllByRole('alert')[0].textContent).toContain('SMTP certificate verification failed'));
  expect(screen.getByRole('button',{name:'Retry email'}).disabled).toBe(false);
  expect(screen.queryByText('✓ SMTP accepted · delivery unconfirmed')).toBeNull();
});
