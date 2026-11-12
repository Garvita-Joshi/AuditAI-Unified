import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import GlobalCopilot from './GlobalCopilot';
import { assistantApi } from '../api/client';

vi.mock('../api/client', () => ({
  assistantApi: {
    context: vi.fn(),
    chat: vi.fn(),
  },
}));

describe('GlobalCopilot Mascot & Assistant', () => {
  beforeEach(() => {
    localStorage.clear();
    assistantApi.context.mockResolvedValue({
      data: {
        procurement: { total_requests: 12 },
        fraud_detection: { total_claims: 20, flagged_claims_count: 2 },
        review_queue: { open_cases_count: 3 },
      },
    });
    assistantApi.chat.mockResolvedValue({
      data: {
        reply: 'AuditAI live status: 12 requests active and 2 flagged claims.',
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders the movable mascot launcher with coffee drinking animation and left alignment', () => {
    render(<GlobalCopilot />);
    const launcher = screen.getByRole('button', { name: /Open AuditAI Copilot/i });
    expect(launcher).toBeTruthy();
    expect(launcher.style.left).toBe('28px');

    const mascotImg = screen.getByAltText('AuditAI Mascot');
    expect(mascotImg).toBeTruthy();
    expect(mascotImg.getAttribute('src')).toBe('/auditai-mascot.png');
  });

  it('toggles open the copilot window on click and displays live context ribbon', async () => {
    render(<GlobalCopilot />);
    const launcher = screen.getByRole('button', { name: /Open AuditAI Copilot/i });
    fireEvent.click(launcher);

    expect(await screen.findByText('AuditAI Copilot')).toBeTruthy();
    expect(await screen.findByText('12')).toBeTruthy();
    expect(await screen.findByText('3 open')).toBeTruthy();
    expect(screen.getByText(/Status of requests/i)).toBeTruthy();
  });

  it('sends a chat message and renders the assistant live database reply', async () => {
    render(<GlobalCopilot />);
    const launcher = screen.getByRole('button', { name: /Open AuditAI Copilot/i });
    fireEvent.click(launcher);

    const input = await screen.findByPlaceholderText(/Ask anything about requests/i);
    fireEvent.change(input, { target: { value: 'What is the status?' } });

    const sendBtn = screen.getByRole('button', { name: /Send query/i });
    fireEvent.click(sendBtn);

    expect(await screen.findByText(/AuditAI live status: 12 requests active/i)).toBeTruthy();
  });
});
