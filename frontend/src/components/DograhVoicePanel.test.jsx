import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DograhVoicePanel from './DograhVoicePanel';
import { dograhApi } from '../api/client';

vi.mock('../api/client', () => ({
  dograhApi: {
    config: vi.fn(),
    startCall: vi.fn(),
    getStatus: vi.fn(),
    postWebhook: vi.fn(),
  },
}));

describe('DograhVoicePanel — Dry Run Testing', () => {
  const mockVendor = {
    id: 1,
    name: 'Demo Electronics',
    email: 'contact@demoelectronics.example',
    offer: { phone: '+919876543210' },
  };

  const mockRun = { id: 1, request_id: 10 };
  const mockRequest = {
    id: 10,
    requirements: {
      product: 'DataSafe Standard',
      delivery_location: 'India',
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    dograhApi.config.mockResolvedValue({
      data: {
        provider: 'dograh',
        agent_name: 'AuditAI Vendor RFQ Follow-up',
        telephony_provider: 'exotel',
        trigger_path_configured: true,
        dry_run_active: true,
        api_key_configured: true,
        webhook_secret_configured: true,
        exotel: {
          configured: true,
          caller_id: '+918047123456',
        },
        safeguards: {
          telephony_calls_prevented: true,
          zero_dollar_spend_guaranteed: true,
        },
      },
    });

    dograhApi.getStatus.mockResolvedValue({
      data: {
        call_id: 'sim_call_abcdef789',
        status: 'completed',
        duration_seconds: 120,
        quotation: {
          status: 'complete',
          fields: {
            unit_price: { value: '48000' },
            total_amount: { value: '48000' },
          },
        },
        transcript: [
          { speaker: 'assistant', message: 'Hello from AuditAI' },
          { speaker: 'vendor', message: 'We can offer 48000 INR' },
        ],
      },
    });
  });

  it('renders prominent dry-run safety banner and pre-populates vendor RFQ info', async () => {
    render(
      <DograhVoicePanel
        vendor={mockVendor}
        run={mockRun}
        request={mockRequest}
      />
    );

    expect(
      screen.getByText(/DRY RUN — Simulated call only\. No actual phone call was placed\./i)
    ).toBeTruthy();

    expect(
      screen.getByText(/Zero-dollar spend guaranteed/i)
    ).toBeTruthy();

    expect(screen.getByDisplayValue('Demo Electronics')).toBeTruthy();
    expect(screen.getByDisplayValue('AuditAI-R1-V1')).toBeTruthy();
    expect(screen.getByDisplayValue('+919876543210')).toBeTruthy();
  });

  it('submits simulated voice call and renders all required telemetry fields', async () => {
    dograhApi.startCall.mockResolvedValue({
      data: {
        status: 'dry_run_success',
        workflow_run_id: 'sim_dgr_test123456',
        call_id: 'sim_call_abcdef789',
        tracking_reference: 'AuditAI-R1-V1',
        phone_number: '+919876543210',
        message: 'Dry-run simulation mode active: Payload validated, zero telephony sessions or dials initiated.',
        dry_run: true,
        endpoint_used: 'https://api.dograh.com/api/v1/public/agent/fe74624e-3928-482b-821e-9be6416df7c8',
        prepared_payload: {
          phone_number: '+919876543210',
          initial_context: {
            vendor_name: 'Demo Electronics',
            vendor_contact_number: '+919876543210',
            rfq_reference: 'AuditAI-R1-V1',
            product_name: 'DataSafe Standard',
            quantity: 1,
            currency: 'INR',
            delivery_location: 'India',
            target_date: '2026-12-04',
          },
        },
      },
    });

    render(
      <DograhVoicePanel
        vendor={mockVendor}
        run={mockRun}
        request={mockRequest}
      />
    );

    const triggerBtn = screen.getByRole('button', { name: /Run Simulated Voice Call/i });
    fireEvent.click(triggerBtn);

    await waitFor(() => {
      expect(dograhApi.startCall).toHaveBeenCalledTimes(1);
    });

    expect(
      await screen.findByText('Dry-Run Interception Succeeded')
    ).toBeTruthy();

    expect(screen.getByText('sim_dgr_test123456')).toBeTruthy();
    expect(screen.getByText('sim_call_abcdef789')).toBeTruthy();
    expect(screen.getByText('+919876543210')).toBeTruthy();
  });

  it('simulates inbound post-call quote webhook correctly', async () => {
    dograhApi.startCall.mockResolvedValue({
      data: {
        status: 'dry_run_success',
        workflow_run_id: 'sim_dgr_test123456',
        call_id: 'sim_call_abcdef789',
        tracking_reference: 'AuditAI-R1-V1',
        phone_number: '+919876543210',
        message: 'Dry-run simulation mode active',
        dry_run: true,
      },
    });

    dograhApi.postWebhook.mockResolvedValue({
      data: {
        status: 'processed',
        call_id: 'sim_call_abcdef789',
        message: 'Quotation and transcript saved successfully.',
      },
    });

    render(
      <DograhVoicePanel
        vendor={mockVendor}
        run={mockRun}
        request={mockRequest}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /Run Simulated Voice Call/i }));

    const webhookBtn = await screen.findByRole('button', { name: /Simulate Return Webhook/i });
    fireEvent.click(webhookBtn);

    await waitFor(() => {
      expect(dograhApi.postWebhook).toHaveBeenCalledTimes(1);
    });

    expect(
      await screen.findByText(/Webhook ingested successfully/i)
    ).toBeTruthy();
  });
});
