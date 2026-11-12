import React, { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { FileText, AlertTriangle, Percent, Activity, Clock, ShieldAlert, CheckSquare } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { fraudApi } from '../api/client';
import StatCard from '../components/StatCard';
import ScoreBadge from '../components/ScoreBadge';
import LoadingSkeleton from '../components/LoadingSkeleton';
import ExplainabilityPanel from '../components/ExplainabilityPanel';
import { useAuditProfile } from '../context/AuditProfileContext';

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const { profile, companyName, currency } = useAuditProfile();

  // Table Filters
  const [statusFilter, setStatusFilter] = useState('all');
  const [scoreFilter, setScoreFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  const navigate = useNavigate();

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fraudApi.summary();

        // Transform histogram object to array for Recharts
        const distData = Object.entries(response.data.score_distribution || {}).map(([range, count]) => ({
          range,
          count
        }));

        setData({ ...response.data, scoreDistData: distData });
      } catch (error) {
        console.error("Failed to fetch dashboard data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="main-content">
        <div className="grid-cols-4 mb-6">
          <LoadingSkeleton type="card" count={4} />
        </div>
        <div className="grid-cols-2">
          <LoadingSkeleton type="detail" count={2} />
        </div>
      </div>
    );
  }

  if (!data) return null;

  // Filtered flagged claims
  const filteredClaims = data.recent_flagged.filter(claim => {
    // Search Query Filter
    const matchesSearch =
      claim.claim_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      claim.employee_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      claim.vendor_name.toLowerCase().includes(searchQuery.toLowerCase());

    // Case Status Filter
    const matchesStatus =
      statusFilter === 'all' ||
      claim.case_status === statusFilter;

    // Score Filter
    const scoreVal = claim.fraud_score;
    let matchesScore = true;
    if (scoreFilter === 'high') matchesScore = scoreVal >= 0.85;
    else if (scoreFilter === 'medium') matchesScore = scoreVal >= 0.70 && scoreVal < 0.85;
    else if (scoreFilter === 'low') matchesScore = scoreVal >= 0.50 && scoreVal < 0.70;

    return matchesSearch && matchesStatus && matchesScore;
  });

  return (
    <div className="main-content">
      {/* Entity Context Breadcrumbs */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm text-muted">
          <span>Global Auditing</span>
          <span>/</span>
          <span className="text-secondary font-medium">{companyName} · {currency}</span>
        </div>
        <span
          className="badge text-xs"
          style={{ background: `${profile.color}20`, color: profile.color, border: `1px solid ${profile.color}40` }}
        >
          {profile.name}
        </span>
      </div>

      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Audit Dashboard</h1>
      </div>

      <h2>Expense model and policy results</h2>
      {/* Case Cycle KPI Row */}
      <div className="grid-cols-3 mb-6">
        <div className="glass-card flex items-center gap-4" style={{ padding: '16px 24px' }}>
          <div style={{ color: 'var(--accent-primary)', background: 'rgba(59, 130, 246, 0.1)', padding: '10px', borderRadius: '10px' }}>
            <Clock size={20} />
          </div>
          <div>
            <div className="text-xs text-muted uppercase font-semibold">Avg Time to Disposition</div>
            <div className="text-lg font-bold">
              {data.kpis?.avg_time_to_disposition_seconds > 0
                ? `${(data.kpis.avg_time_to_disposition_seconds / 60).toFixed(1)} mins`
                : 'N/A'}
            </div>
          </div>
        </div>

        <div className="glass-card flex items-center gap-4" style={{ padding: '16px 24px' }}>
          <div style={{ color: 'var(--status-warning)', background: 'rgba(245, 158, 11, 0.1)', padding: '10px', borderRadius: '10px' }}>
            <ShieldAlert size={20} />
          </div>
          <div>
            <div className="text-xs text-muted uppercase font-semibold">False Positive Rate</div>
            <div className="text-lg font-bold">{data.kpis?.false_positive_rate ?? 0}%</div>
          </div>
        </div>

        <div className="glass-card flex items-center gap-4" style={{ padding: '16px 24px' }}>
          <div style={{ color: 'var(--status-success)', background: 'rgba(16, 185, 129, 0.1)', padding: '10px', borderRadius: '10px' }}>
            <CheckSquare size={20} />
          </div>
          <div>
            <div className="text-xs text-muted uppercase font-semibold">Total Disposed Cases</div>
            <div className="text-lg font-bold">{data.kpis?.total_disposed_cases ?? 0} cases</div>
          </div>
        </div>
      </div>

      {/* Main Core Stat Cards */}
      <div className="grid-cols-4 mb-6">
        <StatCard
          title="Total Claims"
          value={data.total_claims.toLocaleString()}
          icon={FileText}
          color="blue"
        />
        <StatCard
          title="Flagged Anomalies"
          value={data.flagged_count.toLocaleString()}
          icon={AlertTriangle}
          color="red"
        />
        <StatCard
          title="Flagged Claim Rate"
          value={`${data.flagged_rate ?? data.fraud_rate}%`}
          icon={Percent}
          color={(data.flagged_rate ?? data.fraud_rate) > 10 ? 'red' : 'amber'}
        />
        <StatCard
          title="Average Anomaly Index"
          value={(data.average_score * 100).toFixed(1) + '/100'}
          icon={Activity}
          color="amber"
        />
      </div>

      <ExplainabilityPanel
        claims={data.recent_flagged}
        reasonBreakdown={data.explainability?.reason_breakdown || []}
        threshold={null}
      />

      <div className="grid-cols-2 mb-6">
        {/* Flagged Counts Monthly Bar Chart */}
        <div className="glass-card">
          <h3 className="text-lg font-semibold mb-6">Anomalous Claims Count (Monthly)</h3>
          <div style={{ height: 300, width: '100%' }}>
            <ResponsiveContainer>
              <BarChart data={data.fraud_over_time}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" />
                <YAxis allowDecimals={false} />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                <Bar dataKey="flagged_count" name="Flagged Claims" fill="var(--status-danger)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Score Distribution */}
        <div className="glass-card">
          <h3 className="text-lg font-semibold mb-6">Anomaly Score Distribution</h3>
          <div style={{ height: 300, width: '100%' }}>
            <ResponsiveContainer>
              <BarChart data={data.scoreDistData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="range" />
                <YAxis />
                <Tooltip cursor={{ fill: 'rgba(255, 255, 255, 0.05)' }} />
                <Bar dataKey="count" name="Claims" fill="var(--accent-primary)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Flagged Claims list */}
      <div className="glass-card">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-lg font-semibold">High-Risk Claims Queue</h3>

          {/* Dashboard-level filters */}
          <div className="dashboard-filters flex gap-3 items-center">
            <input
              type="text"
              className="input py-1 text-sm"
              placeholder="Search..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ width: 180 }}
            />

            <select
              className="input py-1 text-sm"
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              style={{ width: 140 }}
            >
              <option value="all">All Cases</option>
              <option value="open">Open</option>
              <option value="maker_recommended_approve">Maker Approved</option>
              <option value="maker_recommended_reject">Maker Rejected</option>
              <option value="closed_approved">Closed Approved</option>
              <option value="closed_rejected">Closed Rejected</option>
            </select>

            <select
              className="input py-1 text-sm"
              value={scoreFilter}
              onChange={e => setScoreFilter(e.target.value)}
              style={{ width: 140 }}
            >
              <option value="all">All Scores</option>
              <option value="high">Critical (85%+)</option>
              <option value="medium">Warning (70-85%)</option>
              <option value="low">Anomalous (50-70%)</option>
            </select>
          </div>
        </div>

        {filteredClaims.length === 0 ? (
          <p className="text-secondary text-center py-6">No matching claims found in queue.</p>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Claim ID</th>
                  <th>Employee</th>
                  <th>Vendor</th>
                  <th>Amount</th>
                  <th>Case Status</th>
                  <th>Risk Level</th>
                </tr>
              </thead>
              <tbody>
                {filteredClaims.map(claim => (
                  <tr
                    key={claim.id}
                    onClick={() => navigate(`/claims/${claim.claim_id}`)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td className="font-medium text-accent-primary">{claim.claim_id}</td>
                    <td>{claim.employee_name}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <span>{claim.vendor_name}</span>
                        {claim.closest_vendor_match && (
                          <span
                            className="badge badge-amber text-xs flex items-center gap-1 cursor-help"
                            title={`Possible vendor name typo: ${Math.round(claim.vendor_similarity_score * 100)}% similarity to '${claim.closest_vendor_match}'`}
                            onClick={e => e.stopPropagation()}
                          >
                            Typo
                          </span>
                        )}
                      </div>
                    </td>
                    <td>₹{claim.claimed_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td>
                      <span className={`badge ${claim.case_status?.startsWith('closed_approved') ? 'badge-green' :
                          claim.case_status?.startsWith('closed_rejected') ? 'badge-red' :
                            claim.case_status?.startsWith('maker') ? 'badge-blue' : 'badge-amber'
                        }`}>
                        {claim.case_status?.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td><ScoreBadge score={claim.fraud_score} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
