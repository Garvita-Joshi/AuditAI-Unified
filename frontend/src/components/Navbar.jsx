import React, { useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { ShieldCheck, Upload, LayoutDashboard, FileText, Activity, LogOut, Settings, Building2 } from 'lucide-react';
import { isReviewer, useAuth } from '../auth/AuthContext';
import { useAuditProfile } from '../context/AuditProfileContext';
import WorkspaceSettingsModal from './WorkspaceSettingsModal';
import './Navbar.css';

export default function Navbar() {
  const { user, logout } = useAuth();
  const { companyName, profile } = useAuditProfile();
  const location = useLocation();
  const navigate = useNavigate();
  const reviewer = isReviewer(user);
  const isAdmin = user?.roles?.includes('admin') || user?.role === 'admin';
  const [settingsOpen, setSettingsOpen] = useState(false);

  if (location.pathname.startsWith('/procurement/request')) {
    return null;
  }

  const handleNavClick = (to) => (e) => {
    // Only intercept normal left-clicks so user stays in the same tab
    if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey && e.button === 0) {
      e.preventDefault();
      navigate(to);
    }
  };

  const displayName = companyName && companyName !== 'Acme Global Corp' ? companyName : 'Demo Industries Inc';

  return (
    <nav className="navbar glass-card" aria-label="Main navigation">
      <div className="navbar-content">
        <div className="navbar-brand" onClick={handleNavClick('/procurement')} style={{ cursor: 'pointer' }}>
          <img className="brand-logo" src="/auditai-logo.png" alt="AuditAI mascot" />
          <span className="brand-text">AuditAI</span>
        </div>

        <div className="navbar-links">
          <NavLink
            to="/procurement"
            target="_self"
            onClick={handleNavClick('/procurement')}
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
          >
            <FileText size={16} />
            <span>Procurement</span>
          </NavLink>

          {reviewer && (
            <NavLink
              to="/dashboard"
              target="_self"
              onClick={handleNavClick('/dashboard')}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              <LayoutDashboard size={16} />
              <span>Dashboard</span>
            </NavLink>
          )}

          <NavLink
            to="/upload"
            target="_self"
            onClick={handleNavClick('/upload')}
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
          >
            <Upload size={16} />
            <span>Upload</span>
          </NavLink>

          <NavLink
            to="/claims"
            target="_self"
            onClick={handleNavClick('/claims')}
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
          >
            <FileText size={16} />
            <span>Claims</span>
          </NavLink>

          {reviewer && (
            <NavLink
              to="/audit-screens"
              target="_self"
              onClick={handleNavClick('/audit-screens')}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              <Activity size={16} />
              <span>Audit Screens</span>
            </NavLink>
          )}

          {reviewer && (
            <NavLink
              to="/review-queue"
              target="_self"
              onClick={handleNavClick('/review-queue')}
              aria-label="Review Queue"
              title="Review Queue"
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              <ShieldCheck size={16} />
              <span>Review Queue</span>
            </NavLink>
          )}

          {/* Company & Workspace Identity Badge */}
          <div
            className="navbar-workspace-badge"
            title={`${displayName} · ${profile.name}`}
            onClick={() => isAdmin && setSettingsOpen(true)}
            style={{ cursor: isAdmin ? 'pointer' : 'default' }}
          >
            <Building2 size={13} style={{ color: profile.color, flexShrink: 0 }} />
            <span className="navbar-workspace-name">{displayName}</span>
            <span
              className="navbar-workspace-edition"
              style={{ background: `${profile.color}20`, color: profile.color }}
            >
              {profile.shortName}
            </span>
          </div>

          <div className="navbar-user" title={user?.roles?.join(', ')}>
            <strong>{user?.display_name || user?.email}</strong>
            <small>{(user?.roles?.includes('admin') || user?.role === 'admin') ? 'Administrator' : (user?.role || 'Employee')}</small>
          </div>

          {isAdmin && (
            <button
              type="button"
              className="nav-link navbar-settings-btn"
              onClick={() => setSettingsOpen(true)}
              title="Workspace & Organization Settings (Admin)"
              aria-label="Workspace Settings"
            >
              <Settings size={16} />
            </button>
          )}

          <button className="nav-link navbar-signout" onClick={logout} title="Sign out" aria-label="Sign out">
            <LogOut size={15} />
            <span className="navbar-signout-text">Sign out</span>
          </button>
        </div>
      </div>

      <WorkspaceSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </nav>
  );
}
