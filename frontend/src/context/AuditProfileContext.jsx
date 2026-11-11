import React, { createContext, useContext, useState } from 'react';

export const AUDIT_PROFILES = {
  corporate: {
    id: 'corporate',
    name: 'Corporate Enterprise Edition',
    badge: 'AP & Internal Audit',
    shortName: 'Corporate AP',
    description: 'Internal expense claims, vendor master collusion, payroll anomalies, and segregation of duties (SoD).',
    dataNotice: '',
    hasCircularPayments: false,
    recommendedTabs: ['benford', 'related', 'sod', 'reconciliation', 'policies', 'vendor', 'payroll'],
    recommendedDatasets: ['expense-claims', 'receipts', 'vendor-master', 'employee-roster', 'payroll-payments'],
    icon: 'Building2',
    color: '#3b82f6',
  },
  forensic: {
    id: 'forensic',
    name: 'Forensic & Regulatory Edition',
    badge: 'Tax / Subpoena / Consortia',
    shortName: 'Forensic Investigation',
    description: 'Shell company networks, circular carousel loops, kickbacks, round-tripping of funds, and contractor consortia.',
    dataNotice: 'Multi-party bank files, tax authority records, and contractor audit trails.',
    hasCircularPayments: true,
    recommendedTabs: ['circular', 'related', 'benford', 'vendor', 'reconciliation'],
    recommendedDatasets: ['bank-transfers', 'vendor-master', 'expense-claims'],
    icon: 'Search',
    color: '#f59e0b',
  },
  banking: {
    id: 'banking',
    name: 'Bank & FinTech AML Edition',
    badge: 'AML & Transaction Monitoring',
    shortName: 'Banking / AML',
    description: 'Anti-Money Laundering (AML), fund layering, smurfing / structuring patterns, and inter-account rapid circulation.',
    dataNotice: 'Core banking inter-account transaction feeds, SWIFT/wire transfers, and transaction batches.',
    hasCircularPayments: true,
    recommendedTabs: ['circular', 'reconciliation', 'benford'],
    recommendedDatasets: ['bank-transfers'],
    icon: 'Landmark',
    color: '#10b981',
  },
};

const AuditProfileContext = createContext(null);

export function AuditProfileProvider({ children }) {
  const [profileId, setProfileId] = useState(() => {
    try {
      return localStorage.getItem('auditai_workspace_edition') || 'corporate';
    } catch {
      return 'corporate';
    }
  });

  const [companyName, setCompanyName] = useState(() => {
    try {
      const saved = localStorage.getItem('auditai_workspace_company');
      if (!saved || saved === 'Acme Global Corp') return 'Demo Industries Inc';
      return saved;
    } catch {
      return 'Demo Industries Inc';
    }
  });

  const [currency, setCurrency] = useState(() => {
    try {
      return localStorage.getItem('auditai_workspace_currency') || 'INR (₹)';
    } catch {
      return 'INR (₹)';
    }
  });

  const updateWorkspaceSettings = ({ companyName: newCompany, profileId: newProfile, currency: newCurrency }) => {
    if (newProfile && AUDIT_PROFILES[newProfile]) {
      setProfileId(newProfile);
      try { localStorage.setItem('auditai_workspace_edition', newProfile); } catch (_) {}
    }
    if (newCompany) {
      setCompanyName(newCompany);
      try { localStorage.setItem('auditai_workspace_company', newCompany); } catch (_) {}
    }
    if (newCurrency) {
      setCurrency(newCurrency);
      try { localStorage.setItem('auditai_workspace_currency', newCurrency); } catch (_) {}
    }
  };

  const setProfile = (newId) => {
    updateWorkspaceSettings({ profileId: newId });
  };

  const profile = AUDIT_PROFILES[profileId] || AUDIT_PROFILES.corporate;

  return (
    <AuditProfileContext.Provider value={{
      profileId,
      setProfile,
      companyName,
      currency,
      updateWorkspaceSettings,
      profile,
      profiles: AUDIT_PROFILES
    }}>
      {children}
    </AuditProfileContext.Provider>
  );
}

export function useAuditProfile() {
  const ctx = useContext(AuditProfileContext);
  if (!ctx) {
    return {
      profileId: 'corporate',
      setProfile: () => {},
      companyName: 'Acme Global Corp',
      currency: 'INR (₹)',
      updateWorkspaceSettings: () => {},
      profile: AUDIT_PROFILES.corporate,
      profiles: AUDIT_PROFILES,
    };
  }
  return ctx;
}
