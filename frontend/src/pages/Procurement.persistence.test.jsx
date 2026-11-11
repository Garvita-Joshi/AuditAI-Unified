import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';
import Procurement from './Procurement';
import {procurementApi,sourcingApi} from '../api/client';

vi.mock('../api/client',()=>({
  procurementApi:{workspace:vi.fn(),paymentConfig:vi.fn(),notifications:vi.fn()},
  sourcingApi:{detail:vi.fn(),contractDocuments:vi.fn(),create:vi.fn()},
}));
vi.mock('../components/VendorCRM',()=>({SourcingDashboard:()=>null,VendorRecord:()=>null}));
afterEach(cleanup);
it('opens the saved intake from the dashboard and closes without recreating or reopening it',async()=>{
  const user=userEvent.setup();
  const row={id:43,version:3,status:'draft',created_at:'2026-11-07T10:00:00',
    requirements:{product:'Saved headsets',budget:'12000',currency:'INR',line_items:[{description:'Saved headsets',quantity:4,unit_price:'2000'}]},
    workspace:{step:0},messages:[]};
  procurementApi.workspace.mockResolvedValue({data:{purchases:[],sourcing:[row]}});
  procurementApi.paymentConfig.mockResolvedValue({data:{configured:false}});
  procurementApi.notifications.mockResolvedValue({data:{items:[]}});
  sourcingApi.detail.mockResolvedValue({data:row});
  sourcingApi.contractDocuments.mockResolvedValue({data:[]});
  render(<MemoryRouter initialEntries={['/procurement']}><Procurement user={{id:1,role:'employee'}}/></MemoryRouter>);
  await user.click(await screen.findByRole('button',{name:'Open Saved headsets'}));
  await waitFor(()=>expect(screen.getByRole('textbox',{name:'Purchase budget'}).value).toBe('12000'));
  await user.click(screen.getByRole('button',{name:'Close dialog'}));
  await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
  expect(sourcingApi.detail).toHaveBeenCalledWith('43');
  expect(sourcingApi.create).not.toHaveBeenCalled();
  expect(screen.queryByText('Every purchase. A clear path forward.')).toBeNull();
  expect(screen.queryByRole('region',{name:'Simulated procurement walkthrough'})).toBeNull();
});
