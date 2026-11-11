import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Filter, Search } from 'lucide-react';
import { claimsApi } from '../api/client';
import DataTable from '../components/DataTable';
import ScoreBadge from '../components/ScoreBadge';

const ALLOWED_STATUSES = new Set(['pending', 'processing', 'scored', 'flagged', 'approved', 'rejected']);
const ALLOWED_SORTS = new Set(['claim_id', 'employee_name', 'vendor_name', 'claimed_amount', 'claimed_date', 'submitted_at', 'status', 'fraud_score']);
const ALLOWED_SCORE_BANDS = new Set(['low', 'review', 'high']);

export default function ClaimsTable() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);

  // Filters & Pagination
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [searchParams, setSearchParams] = useSearchParams();
  const statusParam = searchParams.get('status');
  const statusFilter = ALLOWED_STATUSES.has(statusParam) ? statusParam : '';
  const scoreBandParam = searchParams.get('score_band');
  const scoreBand = ALLOWED_SCORE_BANDS.has(scoreBandParam) ? scoreBandParam : '';
  const sortParam = searchParams.get('sort_by');
  const sortBy = ALLOWED_SORTS.has(sortParam) ? sortParam : 'submitted_at';
  const sortOrder = searchParams.get('sort_order') === 'asc' ? 'asc' : 'desc';
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  const navigate = useNavigate();
  const location = useLocation();

  const handleStatusChange = (status) => {
    const nextParams = new URLSearchParams(searchParams);
    if (status) nextParams.set('status', status);
    else nextParams.delete('status');
    setSearchParams(nextParams);
    setPage(1);
  };

  const handleScoreBandChange = (band) => {
    const nextParams = new URLSearchParams(searchParams);
    if (band) nextParams.set('score_band', band);
    else nextParams.delete('score_band');
    setSearchParams(nextParams);
    setPage(1);
  };

  const updateSort = (key, order) => {
    const nextParams = new URLSearchParams(searchParams);
    if (key === 'submitted_at' && order === 'desc') {
      nextParams.delete('sort_by');
      nextParams.delete('sort_order');
    } else {
      nextParams.set('sort_by', key);
      nextParams.set('sort_order', order);
    }
    setSearchParams(nextParams);
    setPage(1);
  };

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 300);

    return () => clearTimeout(handler);
  }, [search]);

  const fetchClaims = async () => {
    setLoading(true);
    try {
      const params = {
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      if (statusFilter) params.status = statusFilter;
      if (scoreBand) params.score_band = scoreBand;
      if (debouncedSearch) params.search = debouncedSearch;

      const response = await claimsApi.list(params);
      setData(response.data.claims);
      setTotal(response.data.total);
    } catch (error) {
      console.error("Failed to fetch claims:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClaims();
  }, [page, statusFilter, scoreBand, sortBy, sortOrder, debouncedSearch]);

  const handleSort = (key) => {
    updateSort(key, sortBy === key && sortOrder === 'desc' ? 'asc' : 'desc');
  };

  const columns = [
    {
      key: 'claim_id',
      label: 'Claim ID',
      sortable: true,
      render: (val) => (
        <div className="flex items-center gap-2">
          <span className="font-medium text-accent-primary">{val}</span>
          {String(val || '').startsWith('INV-') && (
            <span className="badge badge-blue text-xs" style={{ fontSize: '0.65rem', padding: '1px 6px' }}>
              Procurement ML
            </span>
          )}
        </div>
      ),
    },
    { key: 'employee_name', label: 'Employee', sortable: true },
    {
      key: 'vendor_name',
      label: 'Vendor',
      sortable: true,
      render: (val, row) => (
        <div className="flex items-center gap-2">
          <span>{val}</span>
          {row.closest_vendor_match && (
            <span
              className="badge badge-amber text-xs flex items-center gap-1 cursor-help"
              title={`Possible vendor name typo: ${Math.round(row.vendor_similarity_score * 100)}% similarity to '${row.closest_vendor_match}'`}
            >
              Typo
            </span>
          )}
        </div>
      )
    },
    { key: 'claimed_date', label: 'Date', sortable: true },
    {
      key: 'claimed_amount',
      label: 'Amount',
      sortable: true,
      render: (val, row) => `${row?.currency === 'USD' ? '$' : '₹'}${Number(val || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
    },
    {
      key: 'status', label: 'Status', sortable: true, render: (val) => (
        <span className={`badge ${val === 'approved' ? 'badge-green' :
            val === 'flagged' || val === 'rejected' ? 'badge-red' :
              val === 'scored' ? 'badge-blue' : 'badge-amber'
          }`}>{val}</span>
      )
    },
    { key: 'fraud_score', label: 'Anomaly Score', sortable: true, render: (val) => <ScoreBadge score={val} /> },
  ];

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="main-content">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl">Expense Claims</h1>
      </div>

      <div className="glass-card mb-6">
        <div className="claims-toolbar flex justify-between items-center mb-4">
          <div className="claims-filter-controls flex gap-4 items-center">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted" size={16} />
              <input
                type="text"
                className="input pl-10"
                placeholder="Search claims..."
                style={{ width: 250 }}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="claims-status-filter flex items-center gap-2">
              <Filter className="text-muted" size={16} />
              <select
                className="input py-2"
                value={statusFilter}
                onChange={(e) => handleStatusChange(e.target.value)}
                style={{ width: 160 }}
              >
                <option value="">All Statuses</option>
                <option value="pending">Pending</option>
                <option value="processing">Processing</option>
                <option value="scored">Scored</option>
                <option value="flagged">Flagged</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>
            <select
              className="input py-2"
              aria-label="Filter by anomaly score"
              value={scoreBand}
              onChange={(e) => handleScoreBandChange(e.target.value)}
              style={{ width: 165 }}
            >
              <option value="">All Scores</option>
              <option value="low">0–49 / 100</option>
              <option value="review">50–64 / 100</option>
              <option value="high">65–100 / 100</option>
            </select>
            <select
              className="input py-2"
              aria-label="Sort claims by score"
              value={sortBy === 'fraud_score' ? sortOrder : ''}
              onChange={(e) => updateSort(e.target.value ? 'fraud_score' : 'submitted_at', e.target.value || 'desc')}
              style={{ width: 190 }}
            >
              <option value="">Sort by score</option>
              <option value="desc">Highest anomaly first</option>
              <option value="asc">Lowest anomaly first</option>
            </select>
          </div>

          <div className="text-sm text-secondary">
            Showing {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)} of {total} claims
          </div>
        </div>

        <DataTable
          columns={columns}
          data={data}
          onRowClick={(row) => navigate(`/claims/${row.claim_id}`, {
            state: { claimsReturnTo: `${location.pathname}${location.search}` },
          })}
          sortBy={sortBy}
          sortOrder={sortOrder}
          onSort={handleSort}
          loading={loading}
        />

        {/* Pagination */}
        {!loading && totalPages > 1 && (
          <div className="flex justify-center gap-2 mt-6">
            <button
              className="btn btn-secondary"
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
            >
              Previous
            </button>
            <span className="flex items-center px-4 text-sm text-secondary">
              Page {page} of {totalPages}
            </span>
            <button
              className="btn btn-secondary"
              disabled={page === totalPages}
              onClick={() => setPage(p => p + 1)}
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
