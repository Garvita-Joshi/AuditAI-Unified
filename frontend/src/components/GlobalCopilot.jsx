import React, { useState, useEffect, useRef } from 'react';
import { Send, X, RefreshCw, Sparkles, Shield, ShoppingCart, AlertCircle, CreditCard, Bot, Minus } from 'lucide-react';
import { assistantApi } from '../api/client';
import './GlobalCopilot.css';

// Formats simple markdown (*bold*, `code`, bullet points) into clean React elements
function FormatMessage({ text }) {
  if (!text) return null;
  const lines = text.split('\n');

  return (
    <div className="formatted-chat-message">
      {lines.map((line, lIdx) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return <div key={lIdx} style={{ height: '6px' }} />;
        }

        // Format bullet point
        const isBullet = trimmed.startsWith('•') || trimmed.startsWith('-');
        const cleanContent = isBullet ? trimmed.replace(/^[•\-]\s*/, '') : trimmed;

        // Parse **bold** and `code` spans
        const parts = [];
        let curr = cleanContent;
        let pKey = 0;

        // Regular expression for **bold** or `code`
        const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
        let match;
        let lastIdx = 0;

        while ((match = regex.exec(curr)) !== null) {
          if (match.index > lastIdx) {
            parts.push(<span key={pKey++}>{curr.substring(lastIdx, match.index)}</span>);
          }
          const token = match[0];
          if (token.startsWith('**') && token.endsWith('**')) {
            parts.push(<strong key={pKey++}>{token.slice(2, -2)}</strong>);
          } else if (token.startsWith('`') && token.endsWith('`')) {
            parts.push(<code key={pKey++}>{token.slice(1, -1)}</code>);
          }
          lastIdx = regex.lastIndex;
        }
        if (lastIdx < curr.length) {
          parts.push(<span key={pKey++}>{curr.substring(lastIdx)}</span>);
        }

        if (isBullet) {
          return (
            <div key={lIdx} style={{ display: 'flex', gap: '6px', margin: '3px 0' }}>
              <span style={{ color: '#ef9976', flex: 'none' }}>•</span>
              <span style={{ flex: 1 }}>{parts}</span>
            </div>
          );
        }

        return <p key={lIdx} style={{ margin: '3px 0' }}>{parts}</p>;
      })}
    </div>
  );
}

export default function GlobalCopilot() {
  const [open, setOpen] = useState(false);
  const [context, setContext] = useState(null);
  const [loadingContext, setLoadingContext] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);

  // Movable Launcher Position (Defaults strictly to left side: left: 28px, bottom: 24px)
  const [launcherPos, setLauncherPos] = useState(() => {
    try {
      const saved = localStorage.getItem('auditai_mascot_launcher_pos');
      if (saved) return JSON.parse(saved);
    } catch {}
    return { left: 28, bottom: 24, top: null, right: null };
  });

  const [launcherDragging, setLauncherDragging] = useState(false);
  const launcherDragRef = useRef(null);
  const launcherMovedRef = useRef(false);
  const launcherBtnRef = useRef(null);

  // Movable Window Position
  const [windowPos, setWindowPos] = useState(() => {
    try {
      const saved = localStorage.getItem('auditai_copilot_window_pos');
      if (saved) return JSON.parse(saved);
    } catch {}
    return null; // Will position adjacent to launcher
  });
  const [windowDragging, setWindowDragging] = useState(false);
  const windowDragRef = useRef(null);
  const windowRef = useRef(null);
  const chatBodyRef = useRef(null);

  // Fetch live context from database
  const refreshContext = async () => {
    try {
      setLoadingContext(true);
      const res = await assistantApi.context();
      setContext(res.data);
    } catch (err) {
      console.warn('Could not fetch assistant live context:', err);
    } finally {
      setLoadingContext(false);
    }
  };

  useEffect(() => {
    refreshContext();
  }, []);

  useEffect(() => {
    if (open) {
      refreshContext();
    }
  }, [open]);

  // Scroll to bottom on new message
  useEffect(() => {
    if (chatBodyRef.current) {
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
    }
  }, [messages, busy]);

  // Launcher Drag Handlers
  const onLauncherPointerDown = (e) => {
    if (e.button !== 0) return;
    const rect = launcherBtnRef.current?.getBoundingClientRect();
    if (!rect) return;
    e.preventDefault();
    launcherDragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origLeft: rect.left,
      origTop: rect.top,
    };
    launcherMovedRef.current = false;
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onLauncherPointerMove = (e) => {
    if (!launcherDragRef.current) return;
    const dx = e.clientX - launcherDragRef.current.startX;
    const dy = e.clientY - launcherDragRef.current.startY;
    if (!launcherMovedRef.current && Math.hypot(dx, dy) > 4) {
      launcherMovedRef.current = true;
      setLauncherDragging(true);
    }
    if (launcherMovedRef.current) {
      const w = 90, h = 72;
      const newLeft = Math.max(10, Math.min(window.innerWidth - w - 10, launcherDragRef.current.origLeft + dx));
      const newTop = Math.max(10, Math.min(window.innerHeight - h - 10, launcherDragRef.current.origTop + dy));
      const newPos = { left: newLeft, top: newTop, bottom: null, right: null };
      setLauncherPos(newPos);
    }
  };

  const onLauncherPointerUp = (e) => {
    if (!launcherDragRef.current) return;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {}
    const wasMoved = launcherMovedRef.current;
    launcherDragRef.current = null;
    setLauncherDragging(false);

    if (wasMoved && launcherPos) {
      try {
        localStorage.setItem('auditai_mascot_launcher_pos', JSON.stringify(launcherPos));
      } catch {}
    }
  };

  const onLauncherClick = () => {
    if (!launcherMovedRef.current) {
      setOpen((prev) => !prev);
    }
  };

  // Window Drag Handlers
  const onWindowPointerDown = (e) => {
    if (e.button !== 0 || e.target.closest('button')) return;
    const rect = windowRef.current?.getBoundingClientRect();
    if (!rect) return;
    e.preventDefault();
    windowDragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origLeft: rect.left,
      origTop: rect.top,
    };
    setWindowDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onWindowPointerMove = (e) => {
    if (!windowDragRef.current) return;
    const dx = e.clientX - windowDragRef.current.startX;
    const dy = e.clientY - windowDragRef.current.startY;
    const w = 440, h = 580;
    const newLeft = Math.max(10, Math.min(window.innerWidth - w - 10, windowDragRef.current.origLeft + dx));
    const newTop = Math.max(10, Math.min(window.innerHeight - h - 10, windowDragRef.current.origTop + dy));
    setWindowPos({ left: newLeft, top: newTop, bottom: null, right: null });
  };

  const onWindowPointerUp = (e) => {
    if (!windowDragRef.current) return;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {}
    windowDragRef.current = null;
    setWindowDragging(false);
    if (windowPos) {
      try {
        localStorage.setItem('auditai_copilot_window_pos', JSON.stringify(windowPos));
      } catch {}
    }
  };

  // Chat message submission
  const sendMessage = async (textToSend) => {
    const text = (textToSend || input).trim();
    if (!text || busy) return;

    setInput('');
    const userMsg = { role: 'user', text };
    const updatedHistory = [...messages, userMsg];
    setMessages(updatedHistory);
    setBusy(true);

    try {
      const res = await assistantApi.chat(text, updatedHistory.slice(-6));
      const reply = res.data.reply || 'Request processed.';
      if (res.data.context) {
        setContext(res.data.context);
      }
      setMessages((prev) => [...prev, { role: 'assistant', text: reply }]);
    } catch (err) {
      console.error('Chat error:', err);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: 'Unable to reach assistant engine. Please verify the backend server is running.',
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const quickSend = (prompt) => {
    sendMessage(prompt);
  };

  // Position style calculations
  const launcherStyle = {
    left: launcherPos.left !== null ? `${launcherPos.left}px` : '28px',
    top: launcherPos.top !== null ? `${launcherPos.top}px` : 'auto',
    bottom: launcherPos.bottom !== null ? `${launcherPos.bottom}px` : '24px',
    right: 'auto',
  };

  const windowStyle = windowPos
    ? {
        left: `${windowPos.left}px`,
        top: `${windowPos.top}px`,
        bottom: 'auto',
        right: 'auto',
      }
    : {
        left: launcherPos.left !== null ? `${Math.min(launcherPos.left, window.innerWidth - 450)}px` : '28px',
        bottom: '96px',
        right: 'auto',
        top: 'auto',
      };

  return (
    <div className="global-copilot-root">
      {/* 1. MOVABLE / ANIMATED MASCOT LAUNCHER (Left-side default) */}
      <button
        ref={launcherBtnRef}
        className={`global-mascot-launcher ${launcherDragging ? 'is-dragging' : ''}`}
        style={launcherStyle}
        onPointerDown={onLauncherPointerDown}
        onPointerMove={onLauncherPointerMove}
        onPointerUp={onLauncherPointerUp}
        onPointerCancel={onLauncherPointerUp}
        onClick={onLauncherClick}
        type="button"
        aria-label="Open AuditAI Copilot"
        title="AuditAI mascot · Draggable · Click to chat"
      >
        <div className="mascot-avatar-container">
          <img
            src="/auditai-mascot.png"
            alt="AuditAI Mascot"
            className="mascot-pixel-img"
            draggable={false}
          />
          {/* Animated Steam rising from coffee cup */}
          <div className="mascot-coffee-steam" aria-hidden="true">
            <span className="steam-puff p1" />
            <span className="steam-puff p2" />
            <span className="steam-puff p3" />
          </div>
          {/* Ground contact shadow */}
          <span className="mascot-ground-shadow" aria-hidden="true" />
          {/* Live indicator dot */}
          <div className="mascot-live-ping" aria-hidden="true">
            <span className="ping-dot" />
            <span>AI</span>
          </div>
        </div>
      </button>

      {/* 2. COPILOT CHAT WINDOW (Dark theme, crisp white text, real-time memory) */}
      {open && (
        <section
          ref={windowRef}
          className={`global-copilot-window ${windowDragging ? 'is-dragging' : ''}`}
          style={windowStyle}
          aria-label="AuditAI Copilot Dialog"
        >
          {/* Draggable Window Header */}
          <header
            className="copilot-header"
            onPointerDown={onWindowPointerDown}
            onPointerMove={onWindowPointerMove}
            onPointerUp={onWindowPointerUp}
            onPointerCancel={onWindowPointerUp}
          >
            <div className="copilot-header-brand">
              <img
                src="/auditai-mascot.png"
                alt="AuditAI mascot"
                className="copilot-mascot-thumbnail"
              />
              <div className="copilot-title-group">
                <h3>
                  <span>AuditAI Copilot</span>
                  <Sparkles size={13} style={{ color: '#ef9976' }} />
                </h3>
                <p>
                  <span className="ping-dot" style={{ width: 5, height: 5 }} />
                  <span>Live Platform Memory · Drag to Move</span>
                </p>
              </div>
            </div>

            <div className="copilot-header-actions">
              <button
                type="button"
                className="copilot-btn-icon"
                onClick={refreshContext}
                disabled={loadingContext}
                title="Sync latest database state"
                aria-label="Refresh database context"
              >
                <RefreshCw size={14} className={loadingContext ? 'spin' : ''} />
              </button>
              <button
                type="button"
                className="copilot-btn-icon"
                onClick={() => setOpen(false)}
                title="Minimize assistant"
                aria-label="Minimize assistant"
              >
                <Minus size={15} />
              </button>
            </div>
          </header>

          {/* Real-time Status Ribbon */}
          <div className="copilot-status-ribbon">
            <span className="ribbon-pill">
              <ShoppingCart size={11} style={{ color: '#ef9976' }} />
              <span>Requests:</span>
              <strong>{context?.procurement?.total_requests ?? '...'}</strong>
            </span>
            <span className="ribbon-pill">
              <Shield size={11} style={{ color: '#ef9976' }} />
              <span>Claims:</span>
              <strong>
                {context?.fraud_detection?.total_claims ?? '0'}{' '}
                {context?.fraud_detection?.flagged_claims_count > 0 ? (
                  <span style={{ color: '#f87171' }}>
                    ({context.fraud_detection.flagged_claims_count} flagged)
                  </span>
                ) : (
                  <span style={{ color: '#4ade80' }}>(clean)</span>
                )}
              </strong>
            </span>
            <span className="ribbon-pill">
              <AlertCircle size={11} style={{ color: '#ef9976' }} />
              <span>Review:</span>
              <strong>{context?.review_queue?.open_cases_count ?? '0'} open</strong>
            </span>
            <span className="ribbon-pill">
              <CreditCard size={11} style={{ color: '#ef9976' }} />
              <span>PayPal:</span>
              <strong style={{ color: '#38bdf8' }}>Sandbox</strong>
            </span>
          </div>

          {/* Chat Messages Body */}
          <div ref={chatBodyRef} className="copilot-body" aria-live="polite">
            {messages.length === 0 ? (
              <div className="copilot-welcome">
                <img
                  src="/auditai-mascot.png"
                  alt="AuditAI Mascot Drinking Coffee"
                  className="copilot-welcome-mascot"
                />
                <h4>Always-On AuditAI Assistant</h4>
                <p>
                  I'm connected directly to the database and background agents. Ask me anything
                  about your purchase requests, vendor negotiations, PayPal settlements, or fraud signals!
                </p>

                <div className="copilot-quick-prompts">
                  <button
                    type="button"
                    className="quick-chip"
                    onClick={() => quickSend('What is the current status of all running requests?')}
                  >
                    🔍 Status of requests
                  </button>
                  <button
                    type="button"
                    className="quick-chip"
                    onClick={() => quickSend('Are there any flagged fraud claims or policy anomalies?')}
                  >
                    ⚠️ Flagged anomalies
                  </button>
                  <button
                    type="button"
                    className="quick-chip"
                    onClick={() => quickSend('What is the PayPal Sandbox payment status?')}
                  >
                    💳 PayPal payment status
                  </button>
                  <button
                    type="button"
                    className="quick-chip"
                    onClick={() => quickSend('What cases are pending in the review queue?')}
                  >
                    ⚖️ Pending review queue
                  </button>
                </div>
              </div>
            ) : (
              messages.map((msg, index) => (
                <div key={index} className={`chat-message-row ${msg.role}`}>
                  <span className="chat-sender-label">
                    {msg.role === 'user' ? 'You' : 'AuditAI Copilot'}
                  </span>
                  <div className="chat-bubble">
                    <FormatMessage text={msg.text} />
                  </div>
                </div>
              ))
            )}

            {busy && (
              <div className="chat-loading-indicator">
                <div className="pulse-spinner" />
                <span>Analyzing live database context…</span>
              </div>
            )}
          </div>

          {/* Input Composer */}
          <form
            className="copilot-composer"
            onSubmit={(e) => {
              e.preventDefault();
              sendMessage();
            }}
          >
            <input
              className="copilot-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything about requests, vendors, payments..."
              disabled={busy}
              maxLength={2000}
              aria-label="Ask AuditAI Copilot"
            />
            <button
              className="copilot-send-btn"
              type="submit"
              disabled={busy || !input.trim()}
              aria-label="Send query"
            >
              <Send size={15} />
            </button>
          </form>
        </section>
      )}
    </div>
  );
}
