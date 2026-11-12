import React, { useState, useEffect } from 'react';
import { Users, Percent, UserCheck, Layers, ShieldAlert, ArrowLeftRight, FileCheck, Building2, DollarSign, CheckCircle2 } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { analyticsApi } from '../api/client';
import ScoreBadge from '../components/ScoreBadge';
import RecordLink from '../components/RecordLink';
import { useSearchParams } from 'react-router-dom';
import { useAuditProfile } from '../context/AuditProfileContext';
import CircularPayments from './CircularPayments';
import PaymentReconciliation from './PaymentReconciliation';
import PolicyChecks from './PolicyChecks';
import MasterChecks from './MasterChecks';

export default function AuditScreens() {
  const [params, setParams] = useSearchParams();
  const activeTab = params.get('tab') || 'benford';
  const setActiveTab = tab => setParams({ tab });
  const { profile, companyName, currency } = useAuditProfile();
  const [benfordData, setBenfordData] = useState([]);
  const [relatedParties, setRelatedParties] = useState([]);
  const [sodViolations, setSodViolations] = useState([]);
  const [loading, setLoading] = useState(true);

  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const loaders = {
      benford: [analyticsApi.benford, setBenfordData],
      related: [analyticsApi.relatedParties, setRelatedParties],
      sod: [analyticsApi.sodViolations, setSodViolations],
    };
    const selected = loaders[activeTab];
    if (!selected) return;
    let active = true;
    setLoading(true);
    setError('');
    selected[0]().then(response => {
      if (active) selected[1](response.data);
    }).catch(() => {
      if (active) setError('This audit check could not load. Please retry.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [activeTab, retry]);

  useEffect(() => {
    if (activeTab === 'circular' && !profile.hasCircularPayments) {
      setActiveTab('benford');
    }
  }, [activeTab, profile.hasCircularPayments]);

  const allTabs = [
    { id: 'benford', label: "Benford's Law", icon: Percent },
    { id: 'related', label: "Related-Party Screening", icon: Users },
    { id: 'sod', label: "Segregation of Duties (SoD)", icon: UserCheck },
    ...(profile.hasCircularPayments ? [{ id: 'circular', label: "Circular Payments", icon: Layers, isInvestigative: true }] : []),
    { id: 'reconciliation', label: "Payment Reconciliation", icon: ArrowLeftRight },
    { id: 'policies', label: "Company Policy", icon: FileCheck },
    { id: 'vendor', label: "Vendor Master Checks", icon: Building2 },
    { id: 'payroll', label: "Payroll Checks", icon: DollarSign },
  ];

  return (
    <div className="main-content">
      {/* Header Context */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm text-muted">
          <span>Global Auditing</span>
          <span>/</span>
          <span className="text-secondary font-medium">{companyName} · {currency}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="badge text-xs"
            style={{ background: `${profile.color}20`, color: profile.color, border: `1px solid ${profile.color}40` }}
          >
            {profile.name}
          </span>
        </div>
      </div>

      <div className="flex justify-between items-center mb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Compliance & Screening</h1>
          <p className="text-xs text-secondary mt-1">
            Automated integrity algorithms, duty segregation rules, and enterprise policy verification.
          </p>
        </div>
      </div>

      {/* Tabs Row */}
      <div
        className="flex gap-2 mb-6 border-b border-glass pb-3"
        style={{
          overflowX: 'auto',
          whiteSpace: 'nowrap',
          scrollbarWidth: 'none',
          paddingBottom: '8px',
          alignItems: 'center',
        }}
      >
        {allTabs.map(tab => {
          const Icon = tab.icon;
          const isSelected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              className={`btn ${isSelected ? 'btn-primary' : 'btn-secondary'} flex items-center gap-2`}
              style={{
                padding: '8px 15px',
                fontSize: '13px',
                fontWeight: isSelected ? 700 : 500,
                borderRadius: '9px',
                flexShrink: 0,
                whiteSpace: 'nowrap',
              }}
              onClick={() => setActiveTab(tab.id)}
            >
              {Icon && <Icon size={15} />}
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>
      {activeTab === 'circular' && profile.hasCircularPayments && <CircularPayments />}
      {activeTab === 'reconciliation' && <PaymentReconciliation />}
      {activeTab === 'policies' && <PolicyChecks />}
      {['benford', 'related', 'sod'].includes(activeTab) && loading && <div className="glass-card" role="status">Loading selected audit check...</div>}
      {['benford', 'related', 'sod'].includes(activeTab) && error && <div className="glass-card" role="alert">{error} <button className="btn btn-secondary" onClick={() => setRetry(value => value + 1)}>Retry</button></div>}
      {activeTab === 'vendor' && <MasterChecks dataset="vendor"/>}
      {activeTab === 'payroll' && <MasterChecks dataset="payroll"/>}
      {/* Tab Contents */}
      {activeTab === 'benford' && !loading && !error && (
        <div className="glass-card">
          <div className="mb-6">
            <h3 className="text-lg font-semibold flex items-center gap-2 mb-2">
              <Percent className="text-accent-primary" />
              Benford's Law Screen
            </h3>
            <p className="text-sm text-secondary">
              Analyzes the frequency of leading digits (1-9) of all transaction amounts.
              Naturally occurring transaction amounts follow a logarithmic curve. Anomalous spikes may indicate manual fraud or artificial expense splitting.
            </p>
          </div>

          <div style={{ height: 350, width: '100%' }}>
            <ResponsiveContainer>
              <BarChart data={benfordData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="digit" />
                <YAxis unit="%" />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                <Legend />
                <Bar dataKey="actual" name="Actual Distribution" fill="var(--accent-primary)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="expected" name="Expected Log Distribution" fill="rgba(255,255,255,0.15)" stroke="var(--border-light)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {activeTab === 'related' && !loading && !error && (
        <div className="glass-card">
          <div className="mb-6">
            <h3 className="text-lg font-semibold flex items-center gap-2 mb-2">
              <Users className="text-accent-primary" />
              Related-Party Detection
            </h3>
            <p className="text-sm text-secondary">
              Identifies claims where the employee's name matches or is highly similar to the vendor's name (e.g. employee "Sharma" claiming expenses against "Sharma consulting").
            </p>
          </div>

          {relatedParties.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-12 h-12 rounded-full flex items-center justify-center mb-3" style={{ background: 'rgba(16, 185, 129, 0.1)', color: 'var(--status-success)' }}>
                <CheckCircle2 size={24} />
              </div>
              <h4 className="text-base font-semibold text-primary mb-1">No Related-Party Collusion Detected</h4>
              <p className="text-xs text-secondary max-w-md">
                Cross-referencing employee roster and vendor profiles found no suspicious name, email, or tax ID overlaps.
              </p>
            </div>
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Claim ID</th>
                    <th>Employee Name</th>
                    <th>Vendor Name</th>
                    <th>Amount</th>
                    <th>Matched Terms</th>
                    <th>Anomaly Index</th>
                  </tr>
                </thead>
                <tbody>
                  {relatedParties.map((rp, idx) => (
                    <tr key={idx}>
                      <td className="font-semibold text-accent-primary"><RecordLink kind="claim" id={rp.claim_id} knownExists={rp.claim_exists}/></td>
                      <td>{rp.employee_name}</td>
                      <td>{rp.vendor_name}</td>
                      <td>₹{rp.claimed_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                      <td>
                        {rp.matched_terms.map((term, i) => (
                          <span key={i} className="badge badge-amber text-xs mr-1">{term}</span>
                        ))}
                      </td>
                      <td><ScoreBadge score={rp.fraud_score} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'sod' && !loading && !error && (
        <div className="glass-card">
          <div className="mb-6">
            <h3 className="text-lg font-semibold flex items-center gap-2 mb-2">
              <ShieldAlert className="text-status-danger" />
              Segregation of Duties Violations
            </h3>
            <p className="text-sm text-secondary">
              Logs critical audit violations where duty segregation was bypassed (e.g. claimant acting as Maker/Checker or same user performing Maker and Checker actions).
            </p>
          </div>

          {sodViolations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-12 h-12 rounded-full flex items-center justify-center mb-3" style={{ background: 'rgba(16, 185, 129, 0.1)', color: 'var(--status-success)' }}>
                <CheckCircle2 size={24} />
              </div>
              <h4 className="text-base font-semibold text-primary mb-1">All Duty Segregations Intact</h4>
              <p className="text-xs text-secondary max-w-md">
                No segregation-of-duties violations logged. Maker, checker, and employee roles have remained strictly segregated across all approvals.
              </p>
            </div>
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Claim ID</th>
                    <th>Employee Name</th>
                    <th>Violation Type</th>
                    <th>User Involved</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {sodViolations.map((sod, idx) => (
                    <tr key={idx}>
                      <td className="font-semibold text-accent-primary"><RecordLink kind="claim" id={sod.claim_id} knownExists={sod.claim_exists}/></td>
                      <td>{sod.employee_name}</td>
                      <td>
                        <span className="badge badge-red text-xs">{sod.type}</span>
                      </td>
                      <td className="font-medium">{sod.user_involved}</td>
                      <td className="text-secondary text-xs">{sod.details}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
