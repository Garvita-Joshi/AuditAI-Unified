import React from 'react';
import {afterEach,expect,it} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import ProcurementOverview,{workspaceRecords,overviewStats} from './ProcurementOverview';

afterEach(cleanup);
const purchase=(overrides={})=>({id:1,title:'Laptops',status:'approved',terms:{currency:'INR'},total:'80000',created_at:'2026-11-03T10:00:00',...overrides});
it('includes saved sourcing briefs with distinct IDs and does not fabricate blank drafts',()=>{
  const records=workspaceRecords({purchases:[purchase()],sourcing:[
    {id:1,version:3,status:'draft',created_at:'2026-11-04',requirements:{product:'Headsets',currency:'INR',line_items:[{quantity:5,unit_price:'1000',department:'Finance'}]},workspace:{step:2}},
    {id:2,version:1,requirements:{}},
  ]});
  expect(records).toHaveLength(2);
  expect(records.map(r=>r.record_key)).toEqual(['sourcing-1','purchase-1']);
  expect(records[0]).toMatchObject({total:5000,intake_step:2,details:{department:'Finance'}});
});
it('shows four charts backed by records and keeps USD out of the INR commitment',()=>{
  const records=workspaceRecords({purchases:[purchase(),purchase({id:2,total:'500',terms:{currency:'USD'}}),purchase({id:3,status:'submitted'}),purchase({id:4,status:'needs_info'})]});
  expect(overviewStats(records).commitments).toBe(80000);
  render(<ProcurementOverview records={records} now={new Date('2026-11-07T10:00:00Z')}/>);
  expect(screen.getByText('₹80,000.00')).toBeTruthy();
  expect(screen.getByText('USD approvals excluded; no FX conversion')).toBeTruthy();
  expect(screen.getAllByRole('article')).toHaveLength(4);
  expect(screen.getAllByRole('img')).toHaveLength(4);
  expect(screen.getByRole('img',{name:/Awaiting approval: 1 of 4 requests, 25%/})).toBeTruthy();
});
it('shows honest zero states with INR and no simulated trends',()=>{
  render(<ProcurementOverview records={[]}/>);
  expect(screen.getByText('₹0.00')).toBeTruthy();
  expect(screen.getByText('0%')).toBeTruthy();
  expect(screen.getByRole('img',{name:/Sourcing: 0, In review: 0, Approved: 0, Other: 0/})).toBeTruthy();
  expect(screen.queryByText(/Simulated procurement/)).toBeNull();
});
