import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Shield, Check, Settings } from 'lucide-react';
import { useAuditProfile, AUDIT_PROFILES } from '../context/AuditProfileContext';
import { useAuth } from '../auth/AuthContext';
import './WorkspaceSettingsModal.css';

export default function WorkspaceSettingsModal({ isOpen, onClose }) {
  const { profileId, companyName, currency, updateWorkspaceSettings } = useAuditProfile();
  const { user } = useAuth();
  const isAdmin = user?.roles?.includes('admin');

  const [formCompany, setFormCompany] = useState(companyName);
  const [formProfile, setFormProfile] = useState(profileId);
  const [formCurrency, setFormCurrency] = useState(currency);
  const [savedNotice, setSavedNotice] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setFormCompany(companyName);
      setFormProfile(profileId);
      setFormCurrency(currency);
      setSavedNotice(false);
    }
  }, [isOpen, companyName, profileId, currency]);

  if (!isOpen) return null;

  const handleSave = (e) => {
    e.preventDefault();
    updateWorkspaceSettings({
      companyName: formCompany.trim() || 'My Organization',
      profileId: formProfile,
      currency: formCurrency,
    });
    setSavedNotice(true);
    setTimeout(() => {
      setSavedNotice(false);
      onClose();
    }, 700);
  };

  const modalNode = (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="glass-card modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between pb-3 border-b border-glass mb-4">
          <div className="flex items-center gap-2">
            <Settings size={18} className="text-accent-primary" />
            <h2 className="text-base font-bold text-primary">Workspace Settings</h2>
          </div>
          <button type="button" className="text-muted hover:text-primary p-1" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {!isAdmin ? (
          <div className="p-4 rounded-lg bg-bg-surface border border-border-light text-sm text-secondary">
            <Shield size={22} className="text-status-warning mb-2" />
            <p className="font-semibold text-primary">Administrator Privilege Required</p>
            <p className="mt-1 text-xs text-muted">
              Only organization administrators can modify company-wide workspace settings.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSave}>
            <div className="mb-5">
              <label htmlFor="company-name-input">
                Company / Organization Name
              </label>
              <input
                id="company-name-input"
                type="text"
                className="input"
                value={formCompany}
                onChange={(e) => setFormCompany(e.target.value)}
                placeholder="e.g. Acme Global Corp"
                required
              />
            </div>

            <div className="mb-5">
              <label htmlFor="workspace-edition-select">
                System Edition
              </label>
              <select
                id="workspace-edition-select"
                className="input"
                value={formProfile}
                onChange={(e) => setFormProfile(e.target.value)}
              >
                {Object.values(AUDIT_PROFILES).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-6">
              <label htmlFor="workspace-currency-select">
                Primary Reporting Currency
              </label>
              <select
                id="workspace-currency-select"
                className="input"
                value={formCurrency}
                onChange={(e) => setFormCurrency(e.target.value)}
              >
                <option value="INR (₹)">INR (₹) - Indian Rupee</option>
                <option value="USD ($)">USD ($) - US Dollar</option>
                <option value="EUR (€)">EUR (€) - Euro</option>
                <option value="GBP (£)">GBP (£) - British Pound</option>
              </select>
            </div>

            <div className="flex items-center justify-end gap-3 pt-4 border-t border-glass">
              <button type="button" className="btn btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary flex items-center gap-2">
                <Check size={16} />
                <span>{savedNotice ? 'Saved!' : 'Save Settings'}</span>
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );

  return typeof document !== 'undefined' ? createPortal(modalNode, document.body) : modalNode;
}
