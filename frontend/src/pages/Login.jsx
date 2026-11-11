import React, { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { authApi } from '../api/client';
import './Login.css';

export default function Login({ onAuthenticated }) {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [stage, setStage] = useState('email');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const requestCode = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const { data } = await authApi.requestOtp({ email });
      setStage('code');
      setMessage(data.development_code ? `Development code: ${data.development_code}` : 'Check your registered delivery channel for the code.');
    } catch (err) { setError(err.response?.data?.detail || 'Could not issue a one-time code.'); }
    finally { setBusy(false); }
  };

  const verifyCode = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try { const { data } = await authApi.verifyOtp({ email, code }); onAuthenticated(data); }
    catch (err) { setError(err.response?.data?.detail || 'Could not verify the code.'); }
    finally { setBusy(false); }
  };

  return <main className="login-page"><section className="login-card glass-card">
    <ShieldCheck className="login-icon" size={44} /><h1>Welcome to AuditAI</h1>
    <p>Use a one-time code to access the audit workspace.</p>
    {stage === 'email' ? <form onSubmit={requestCode}>
      <label htmlFor="email">Work email</label><input id="email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
      <button className="btn btn-primary login-submit" disabled={busy}>{busy ? 'Sending…' : 'Send code'}</button>
    </form> : <form onSubmit={verifyCode}>
      <label htmlFor="code">Six-digit code</label><input id="code" className="input otp-input" inputMode="numeric" pattern="[0-9]{6}" maxLength="6" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} required autoFocus />
      <button className="btn btn-primary login-submit" disabled={busy}>{busy ? 'Verifying…' : 'Sign in'}</button>
      <button type="button" className="login-link" onClick={() => setStage('email')}>Use a different email</button>
    </form>}
    {message && <p className="login-message">{message}</p>}{error && <p className="login-error">{error}</p>}
  </section></main>;
}
