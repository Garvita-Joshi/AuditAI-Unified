// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuditProfileProvider, useAuditProfile, AUDIT_PROFILES } from './AuditProfileContext';
import WorkspaceSettingsModal from '../components/WorkspaceSettingsModal';

vi.mock('../auth/AuthContext', () => ({
  useAuth: vi.fn(),
  isReviewer: () => true,
}));

import { useAuth } from '../auth/AuthContext';

function TestConsumer() {
  const { profileId, companyName, currency, updateWorkspaceSettings, profile } = useAuditProfile();
  return (
    <div>
      <span data-testid="profile-id">{profileId}</span>
      <span data-testid="profile-name">{profile.name}</span>
      <span data-testid="company-name">{companyName}</span>
      <span data-testid="currency">{currency}</span>
      <button
        onClick={() =>
          updateWorkspaceSettings({
            companyName: 'Stark Industries',
            profileId: 'forensic',
            currency: 'USD ($)',
          })
        }
      >
        Update Workspace Settings
      </button>
    </div>
  );
}

describe('AuditProfileContext & Workspace Settings', () => {
  beforeEach(() => {
    localStorage.clear();
    useAuth.mockReturnValue({
      user: { display_name: 'Admin User', roles: ['admin'] },
      logout: vi.fn(),
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('defaults to corporate profile and Demo Industries Inc without circular payments', () => {
    render(
      <AuditProfileProvider>
        <TestConsumer />
      </AuditProfileProvider>
    );

    expect(screen.getByTestId('profile-id').textContent).toBe('corporate');
    expect(screen.getByTestId('profile-name').textContent).toBe('Corporate Enterprise Edition');
    expect(screen.getByTestId('company-name').textContent).toBe('Demo Industries Inc');
    expect(screen.getByTestId('currency').textContent).toBe('INR (₹)');
  });

  it('configures circular payments flags correctly per edition', () => {
    expect(AUDIT_PROFILES.corporate.hasCircularPayments).toBe(false);
    expect(AUDIT_PROFILES.forensic.hasCircularPayments).toBe(true);
    expect(AUDIT_PROFILES.banking.hasCircularPayments).toBe(true);
  });

  it('updates workspace settings and persists them to localStorage', async () => {
    const user = userEvent.setup();
    render(
      <AuditProfileProvider>
        <TestConsumer />
      </AuditProfileProvider>
    );

    await user.click(screen.getByRole('button', { name: 'Update Workspace Settings' }));
    expect(screen.getByTestId('company-name').textContent).toBe('Stark Industries');
    expect(screen.getByTestId('profile-id').textContent).toBe('forensic');
    expect(screen.getByTestId('currency').textContent).toBe('USD ($)');

    expect(localStorage.getItem('auditai_workspace_company')).toBe('Stark Industries');
    expect(localStorage.getItem('auditai_workspace_edition')).toBe('forensic');
    expect(localStorage.getItem('auditai_workspace_currency')).toBe('USD ($)');
  });

  it('allows Admin to configure company name and edition in WorkspaceSettingsModal', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <AuditProfileProvider>
        <TestConsumer />
        <WorkspaceSettingsModal isOpen={true} onClose={onClose} />
      </AuditProfileProvider>
    );

    expect(screen.getByText('Workspace Settings')).toBeTruthy();
    expect(screen.getByLabelText(/Company \/ Organization Name/i)).toBeTruthy();

    // Change company name
    const companyInput = screen.getByLabelText(/Company \/ Organization Name/i);
    await user.clear(companyInput);
    await user.type(companyInput, 'Wayne Enterprises');

    // Select Banking Edition
    const editionSelect = screen.getByLabelText(/System Edition/i);
    await user.selectOptions(editionSelect, 'banking');

    // Save
    await user.click(screen.getByRole('button', { name: /Save Settings/i }));

    expect(screen.getByTestId('company-name').textContent).toBe('Wayne Enterprises');
    expect(screen.getByTestId('profile-id').textContent).toBe('banking');
  });

  it('shows permission barrier in WorkspaceSettingsModal for non-admin users', () => {
    useAuth.mockReturnValue({
      user: { display_name: 'Checker User', roles: ['checker'] },
      logout: vi.fn(),
    });

    render(
      <AuditProfileProvider>
        <WorkspaceSettingsModal isOpen={true} onClose={vi.fn()} />
      </AuditProfileProvider>
    );

    expect(screen.getByText('Administrator Privilege Required')).toBeTruthy();
    expect(screen.queryByLabelText(/Company \/ Organization Name/i)).toBeNull();
  });
});
