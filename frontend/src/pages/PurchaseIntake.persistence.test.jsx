import React,{StrictMode} from 'react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PurchaseIntake from './PurchaseIntake';
import {sourcingApi} from '../api/client';

vi.mock('../api/client',()=>({sourcingApi:{create:vi.fn(),detail:vi.fn(),save:vi.fn(),contractDocuments:vi.fn(),startAgent:vi.fn()}}));
vi.mock('../components/VendorCRM',()=>({SourcingDashboard:()=>null,VendorRecord:()=>null}));
const Modal=({children})=><div>{children}</div>;
const saved=()=>({id:43,version:4,status:'draft',requirements:{product:'Headsets',budget:'12000',currency:'INR',
  line_items:[{description:'Headsets',quantity:4,unit_price:'2000',department:'IT'}],
  data_sharing_choice:'yes',shares_personal_data:true,data_types:['Marketing Data'],data_usage:'Campaign support'},
  messages:[],workspace:{step:1,workflow:null},agent_run:null});
beforeEach(()=>{
  vi.clearAllMocks();
  sourcingApi.detail.mockImplementation(async()=>({data:saved()}));
  sourcingApi.create.mockImplementation(async()=>({data:saved()}));
  sourcingApi.contractDocuments.mockResolvedValue({data:[]});
  sourcingApi.save.mockImplementation(async(id,requirements,version,confirm,intakeStep)=>({data:{...saved(),requirements,version:version+1,workspace:{step:intakeStep}}}));
});
afterEach(cleanup);
it('reopens saved data on its saved page, reloads without creating another record, and saves only on command',async()=>{
  const user=userEvent.setup();const onLocationChange=vi.fn();
  const props={Modal,close:vi.fn(),requestId:'43',onLocationChange};
  const first=render(<PurchaseIntake {...props}/>);
  await waitFor(()=>expect(screen.getByRole('heading',{name:'Data Information'})).toBeTruthy());
  const usage=screen.getByRole('textbox',{name:/How will this vendor use this data/});
  await user.type(usage,' and reporting');
  expect(sourcingApi.save).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Save draft'}));
  await waitFor(()=>expect(sourcingApi.save).toHaveBeenCalledTimes(1));
  const args=sourcingApi.save.mock.calls[0];
  expect(args[0]).toBe(43);expect(args[1].data_usage).toBe('Campaign support and reporting');expect(args[4]).toBe(1);
  expect(onLocationChange).toHaveBeenCalledWith(43,1);
  const parentRerender=vi.fn();
  first.rerender(<PurchaseIntake {...props} onLocationChange={parentRerender}/>);
  expect(parentRerender).not.toHaveBeenCalled();
  first.unmount();
  render(<PurchaseIntake {...props}/>);
  await waitFor(()=>expect(sourcingApi.detail).toHaveBeenCalledTimes(2));
  expect(sourcingApi.create).not.toHaveBeenCalled();
  expect(sourcingApi.startAgent).not.toHaveBeenCalled();
});
it('creates only once during StrictMode effect replay',async()=>{
  render(<StrictMode><PurchaseIntake Modal={Modal} close={vi.fn()}/></StrictMode>);
  await waitFor(()=>expect(screen.getByRole('heading',{name:'Data Information'})).toBeTruthy());
  expect(sourcingApi.create).toHaveBeenCalledTimes(1);
});
