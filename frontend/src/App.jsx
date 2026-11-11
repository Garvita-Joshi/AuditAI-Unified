import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom';
import { AuthProvider, isReviewer, useAuth } from './auth/AuthContext';
import { AuditProfileProvider } from './context/AuditProfileContext';
import Navbar from './components/Navbar';
import Dashboard from './pages/Dashboard';
import Upload from './pages/Upload';
import ClaimsTable from './pages/ClaimsTable';
import ClaimDetail from './pages/ClaimDetail';
import AuditScreens from './pages/AuditScreens';
import Login from './pages/Login';
import Procurement from './pages/Procurement';
import './pages/UnifiedTheme.css';
function ProcurementWorkspace(){const {user}=useAuth();return <Procurement user={user}/>;}
function OtpLogin(){const {user,authenticate}=useAuth();return user?<Navigate to="/" replace/>:<Login onAuthenticated={authenticate}/>;}

import ReviewQueue from './pages/ReviewQueue';
import CaseDetail from './pages/CaseDetail';
import RecordDetail from './pages/RecordDetail';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, errorInfo) {
    console.error('AuditAI ErrorBoundary caught an error:', error, errorInfo);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '40px 20px', maxWidth: '600px', margin: '40px auto', textAlign: 'center', background: 'rgba(255,255,255,0.05)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.1)' }}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '12px', color: '#f87171' }}>Something went wrong loading this view</h2>
          <p style={{ color: '#94a3b8', fontSize: '0.875rem', marginBottom: '20px' }}>
            {this.state.error?.message || 'An unexpected rendering error occurred.'}
          </p>
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
            <button
              onClick={() => { this.setState({ hasError: false, error: null }); window.location.href = '/'; }}
              style={{ padding: '8px 16px', borderRadius: '6px', background: '#3b82f6', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 500 }}
            >
              Go to Dashboard
            </button>
            <button
              onClick={() => window.location.reload()}
              style={{ padding: '8px 16px', borderRadius: '6px', background: 'rgba(255,255,255,0.1)', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 500 }}
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function ProtectedLayout() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="auth-loading">Checking your session…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <div className="app-container"><Navbar /><ErrorBoundary><Outlet /></ErrorBoundary></div>;
}

function ReviewerOnly({ children }) {
  const { user } = useAuth();
  return isReviewer(user) ? children : <Navigate to="/claims" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AuditProfileProvider>
          <Routes>
            <Route path="/login" element={<OtpLogin />} />
            <Route element={<ProtectedLayout />}>
              <Route path="/" element={<ReviewerOnly><Dashboard /></ReviewerOnly>} />
              <Route path="/procurement/*" element={<ProcurementWorkspace/>} />
              <Route path="/upload" element={<Upload />} />
              <Route path="/claims" element={<ClaimsTable />} />
              <Route path="/claims/:id" element={<ClaimDetail />} />
              <Route path="/audit-screens" element={<ReviewerOnly><AuditScreens /></ReviewerOnly>} />
              <Route path="/review/cases/:caseId" element={<ReviewerOnly><CaseDetail /></ReviewerOnly>} />
              <Route path="/records/:kind/:recordId" element={<ReviewerOnly><RecordDetail /></ReviewerOnly>} />
              <Route path="/review-queue" element={<ReviewerOnly><ReviewQueue /></ReviewerOnly>} />
              <Route path="/circular-payments" element={<Navigate to="/audit-screens?tab=circular" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuditProfileProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
