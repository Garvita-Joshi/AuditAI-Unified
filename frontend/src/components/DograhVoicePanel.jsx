import React, { useState, useEffect } from 'react';
import {
  Phone,
  PhoneCall,
  ShieldCheck,
  CheckCircle2,
  Clock,
  FileText,
  AlertTriangle,
  RotateCw,
  Send,
  Headphones,
  Check,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { dograhApi } from '../api/client';
import './DograhVoicePanel.css';

export function DograhVoicePanel({
  vendor,
  run,
  request,
  onRefresh,
  onBack,
}) {
  const rfqRef = `AuditAI-R${run?.id || 1}-V${vendor?.id || 1}`;
  const defaultPhone =
    vendor?.offer?.phone ||
    vendor?.offer?.contact_phone ||
    vendor?.phone ||
    '+919876543210';

  const [phone, setPhone] = useState(defaultPhone);
  const [productName, setProductName] = useState(
    request?.requirements?.product || 'Procurement Goods and Services'
  );
  const [quantity, setQuantity] = useState(1);
  const [currency, setCurrency] = useState('INR');
  const [location, setLocation] = useState(
    request?.requirements?.delivery_location || 'India'
  );
  const [targetDate, setTargetDate] = useState('2026-12-04');

  const [calling, setCalling] = useState(false);
  const [callResult, setCallResult] = useState(null);
  const [error, setError] = useState(null);
  const [config, setConfig] = useState(null);
  const [showPayload, setShowPayload] = useState(false);

  const [webhookSubmitting, setWebhookSubmitting] = useState(false);
  const [webhookSuccess, setWebhookSuccess] = useState(null);
  const [liveStatus, setLiveStatus] = useState(null);
  const [refreshingStatus, setRefreshingStatus] = useState(false);

  // Validate Indian phone number format (+91 followed by 10 digits)
  const cleanedPhone = phone?.replace(/[\s\-\(\)\.]/g, '') || '';
  const isIndianPhoneValid = /^\+91[1-9]\d{9}$/.test(cleanedPhone);

  // Fetch integration configuration on load
  useEffect(() => {
    let isMounted = true;
    dograhApi
      .config()
      .then((res) => {
        if (isMounted) setConfig(res.data);
      })
      .catch((err) => {
        console.warn('Could not load Dograh configuration:', err);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const refreshStatus = async (workflowRunId) => {
    const targetId = workflowRunId || callResult?.workflow_run_id || callResult?.call_id;
    if (!targetId || !dograhApi?.getStatus) return;
    setRefreshingStatus(true);
    try {
      const res = await dograhApi.getStatus(targetId);
      if (res?.data) {
        setLiveStatus(res.data);
      }
    } catch (err) {
      console.warn('Could not fetch call status:', err);
    } finally {
      setRefreshingStatus(false);
    }
  };

  const handleStartCall = async (e) => {
    e?.preventDefault();
    setCalling(true);
    setError(null);
    setWebhookSuccess(null);
    setLiveStatus(null);

    try {
      const payload = {
        request_id: request?.id || run?.request_id || 1,
        agent_vendor_id: vendor?.id || 1,
        vendor_name: vendor?.name || 'Demo Vendor',
        phone_number: phone,
        rfq_reference: rfqRef,
        product_name: productName,
        quantity: Number(quantity) || 1,
        currency: currency,
        delivery_location: location,
        target_date: targetDate,
        test_mode: false,
      };

      const res = await dograhApi.startCall(payload);
      setCallResult(res.data);
      if (onRefresh) onRefresh();

      // Poll status for the newly initiated call
      if (res.data?.workflow_run_id) {
        refreshStatus(res.data.workflow_run_id);
      }
    } catch (err) {
      console.error('Dograh start-call error:', err);
      setError(
        err.response?.data?.detail ||
          err.message ||
          'Failed to initiate simulated voice call.'
      );
    } finally {
      setCalling(false);
    }
  };

  const handleStartTwilioCall = async (forceLive = false) => {
    setCalling(true);
    setError(null);
    setWebhookSuccess(null);
    setLiveStatus(null);

    try {
      const payload = {
        request_id: request?.id || run?.request_id || 1,
        agent_vendor_id: vendor?.id || 1,
        vendor_name: vendor?.name || 'Demo Vendor',
        phone_number: phone,
        rfq_reference: rfqRef,
        product_name: productName,
        quantity: Number(quantity) || 1,
        currency: currency,
        delivery_location: location,
        target_date: targetDate,
      };

      const res = await dograhApi.startTwilioCall(payload, forceLive);
      setCallResult({
        ...res.data,
        workflow_run_id: res.data.call_sid,
        message: res.data.message,
        tracking_reference: res.data.tracking_reference || rfqRef,
        phone_number: res.data.to || phone,
      });
      if (onRefresh) onRefresh();
    } catch (err) {
      console.error('Twilio start-call error:', err);
      setError(
        err.response?.data?.detail ||
          err.message ||
          'Failed to dispatch Twilio voice call.'
      );
    } finally {
      setCalling(false);
    }
  };

  const handleSimulateWebhook = async () => {
    if (!callResult) return;
    setWebhookSubmitting(true);
    setWebhookSuccess(null);
    setError(null);

    try {
      const webhookPayload = {
        workflow_run_id: callResult.workflow_run_id,
        call_id: callResult.call_id,
        status: 'completed',
        disposition: 'completed',
        duration_seconds: 145,
        summary: `Vendor ${vendor.name} confirmed commercial quotation on standard terms.`,
        initial_context: {
          rfq_reference: rfqRef,
          vendor_name: vendor.name,
        },
        collected_data: {
          unit_price: 18500,
          total_amount: 185000,
          currency: currency,
          shipping_charges: 2500,
          taxes: 33300,
          delivery_lead_time_days: 7,
          warranty: '1 Year Comprehensive',
          payment_terms: 'Net 30 Days',
        },
        transcript: [
          {
            speaker: 'assistant',
            text: `Hello, calling from AuditAI regarding RFQ ${rfqRef} for ${productName}.`,
          },
          {
            speaker: 'vendor',
            text: `Hello! Yes, we can supply this for 185,000 ${currency} total on Net 30 payment terms.`,
          },
          {
            speaker: 'assistant',
            text: 'Thank you! Can you confirm warranty coverage and shipping timeline?',
          },
          {
            speaker: 'vendor',
            text: 'We provide a 1-year comprehensive warranty and dispatch within 7 business days.',
          },
          {
            speaker: 'assistant',
            text: 'Perfect. I have recorded these commercial details for our procurement team. Thank you!',
          },
        ],
      };

      const res = await dograhApi.postWebhook(webhookPayload);
      setWebhookSuccess(
        `Webhook ingested successfully: ${res.data?.message || 'Quotation and transcript saved.'}`
      );
      if (onRefresh) onRefresh();

      // Refresh live status to display extracted quotation & transcript
      if (callResult?.workflow_run_id) {
        refreshStatus(callResult.workflow_run_id);
      }
    } catch (err) {
      console.error('Webhook simulation error:', err);
      setError(
        err.response?.data?.detail ||
          err.message ||
          'Failed to send synthetic webhook.'
      );
    } finally {
      setWebhookSubmitting(false);
    }
  };

  return (
    <div className="dograh-voice-panel">
      {/* ── SAFETY BANNER ── */}
      <div className="dv-dry-run-banner" role="alert">
        <div className="dv-banner-left">
          <ShieldCheck size={20} className="dv-shield-icon" />
          <div>
            <strong>DRY RUN — Simulated call only. No actual phone call was placed.</strong>
            <p>
              Zero-dollar spend guaranteed. Outbound telephony and carrier dialing are intercepted safely in AuditAI.
            </p>
          </div>
        </div>
        <span className="dv-dry-run-tag">DOGRAH_DRY_RUN=TRUE</span>
      </div>

      <div className="dv-content-layout">
        {/* ── LEFT COLUMN: CALL SETUP ── */}
        <div className="dv-form-card">
          <div className="dv-card-header">
            <div className="dv-badge-pill">
              <Headphones size={13} />
              <span>Voice AI Procurement Follow-up</span>
            </div>
            <h3>Initiate Voice Outreach</h3>
            <p>
              Trigger the published Dograh agent <strong>"AuditAI Vendor RFQ Follow-up"</strong> for {vendor.name}.
            </p>
          </div>

          <form onSubmit={handleStartCall} className="dv-form">
            <div className="dv-field">
              <label>Target Phone Number (Placeholder)</label>
              <div className="dv-input-with-icon">
                <Phone size={15} />
                <input
                  type="text"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+919876543210"
                  required
                />
              </div>
              <div className="dv-phone-meta">
                {isIndianPhoneValid ? (
                  <span className="dv-valid-phone">✓ Valid Indian Number (+91)</span>
                ) : (
                  <span className="dv-invalid-phone">⚠ Enter valid 10-digit Indian number (+91...)</span>
                )}
                {config?.safety_controls?.allowlist_active && (
                  <span className="dv-allowlist-tag">Allowlist Active</span>
                )}
              </div>
              <small className="dv-hint">
                Phone dialing is strictly prevented in dry-run mode. Safe for synthetic tests.
              </small>
            </div>

            <div className="dv-grid-2">
              <div className="dv-field">
                <label>RFQ Reference</label>
                <input type="text" value={rfqRef} readOnly className="dv-readonly" />
              </div>
              <div className="dv-field">
                <label>Vendor Name</label>
                <input type="text" value={vendor.name} readOnly className="dv-readonly" />
              </div>
            </div>

            <div className="dv-field">
              <label>Product / Service</label>
              <input
                type="text"
                value={productName}
                onChange={(e) => setProductName(e.target.value)}
                required
              />
            </div>

            <div className="dv-grid-3">
              <div className="dv-field">
                <label>Quantity</label>
                <input
                  type="number"
                  min="1"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  required
                />
              </div>
              <div className="dv-field">
                <label>Currency</label>
                <input
                  type="text"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                  required
                />
              </div>
              <div className="dv-field">
                <label>Target Delivery Date</label>
                <input
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="dv-field">
              <label>Delivery Location</label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                required
              />
            </div>

            {error && (
              <div className="dv-alert error">
                <AlertTriangle size={15} />
                <span>{error}</span>
              </div>
            )}

            <div className="dv-action-row">
              <button
                type="submit"
                className="dv-primary-btn"
                disabled={calling}
              >
                {calling ? (
                  <>
                    <RotateCw size={15} className="dv-spinning" />
                    <span>Preparing Simulation…</span>
                  </>
                ) : (
                  <>
                    <PhoneCall size={15} />
                    <span>Run Simulated Voice Call</span>
                  </>
                )}
              </button>

              {config?.twilio?.configured && (
                <button
                  type="button"
                  className="dv-twilio-btn"
                  onClick={() => handleStartTwilioCall(false)}
                  disabled={calling}
                  title="Test Twilio Telephony flow via configured Twilio carrier"
                >
                  <Phone size={14} />
                  <span>Twilio Call ({config.twilio.phone_number})</span>
                </button>
              )}

              {onBack && (
                <button type="button" className="dv-secondary-btn" onClick={onBack}>
                  Return to Overview
                </button>
              )}
            </div>
          </form>
        </div>

        {/* ── RIGHT COLUMN: SIMULATED RESULTS ── */}
        <div className="dv-results-card">
          <div className="dv-card-header">
            <span className="dv-status-label">Voice Execution Pipeline</span>
            <h3>Call Telemetry &amp; Diagnostics</h3>
          </div>

          {!callResult ? (
            <div className="dv-empty-state">
              <PhoneCall size={34} className="dv-empty-icon" />
              <h4>No Call Dispatched Yet</h4>
              <p>
                Click <strong>"Run Simulated Voice Call"</strong> to validate payload formatting, context variables, and dry-run interception.
              </p>
              {config && (
                <div className="dv-config-pill-box">
                  <div>
                    <small>Dograh Provider</small>
                    <strong>{config.provider}</strong>
                  </div>
                  <div>
                    <small>Telephony Carrier</small>
                    <strong style={{ textTransform: 'capitalize' }}>
                      {config.twilio?.configured ? 'Twilio (Ready)' : config.twilio?.account_sid_configured ? 'Twilio' : (config.telephony_provider || 'Twilio')}
                    </strong>
                  </div>
                  <div>
                    <small>Trigger Path</small>
                    <span className="dv-mono">{config.trigger_path ? 'Configured' : 'Missing'}</span>
                  </div>
                  <div>
                    <small>Safeguards</small>
                    <span className="dv-safe-badge">Zero Spend Guaranteed</span>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="dv-result-content">
              <div className="dv-success-badge-card">
                <div className="dv-success-header">
                  <CheckCircle2 size={18} className="dv-check-icon" />
                  <div>
                    <strong>Dry-Run Interception Succeeded</strong>
                    <p>{callResult.message}</p>
                  </div>
                </div>
              </div>

              <div className="dv-telemetry-grid">
                <div className="dv-telemetry-item">
                  <small>Tracking Reference</small>
                  <strong>{callResult.tracking_reference}</strong>
                </div>
                <div className="dv-telemetry-item">
                  <small>Workflow Run ID</small>
                  <strong className="dv-mono">{callResult.workflow_run_id}</strong>
                </div>
                <div className="dv-telemetry-item">
                  <small>Simulated Call ID</small>
                  <strong className="dv-mono">{callResult.call_id || 'N/A'}</strong>
                </div>
                <div className="dv-telemetry-item">
                  <small>Dial Target</small>
                  <strong>{callResult.phone_number}</strong>
                </div>
                <div className="dv-telemetry-item full">
                  <small>Simulated Trigger Endpoint</small>
                  <span className="dv-mono-sm">{callResult.endpoint_used}</span>
                </div>
              </div>

              {/* Collapsible Prepared Payload */}
              <div className="dv-payload-box">
                <button
                  type="button"
                  className="dv-payload-toggle"
                  onClick={() => setShowPayload(!showPayload)}
                >
                  <FileText size={14} />
                  <span>Prepared Dograh API Trigger Payload</span>
                  {showPayload ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                {showPayload && (
                  <pre className="dv-json-preview">
                    {JSON.stringify(callResult.prepared_payload, null, 2)}
                  </pre>
                )}
              </div>

              {/* ── PHASE 4: SIMULATE INBOUND WEBHOOK ── */}
              <div className="dv-webhook-sim-box">
                <div className="dv-webhook-sim-heading">
                  <div>
                    <h4>Test Inbound Quotation Webhook</h4>
                    <p>Simulate Dograh's post-call webhook to verify quotation extraction and transcript storage.</p>
                  </div>
                  <button
                    type="button"
                    className="dv-webhook-btn"
                    onClick={handleSimulateWebhook}
                    disabled={webhookSubmitting}
                  >
                    {webhookSubmitting ? (
                      <>
                        <RotateCw size={13} className="dv-spinning" />
                        <span>Ingesting Webhook…</span>
                      </>
                    ) : (
                      <>
                        <Send size={13} />
                        <span>Simulate Return Webhook</span>
                      </>
                    )}
                  </button>
                </div>

                {webhookSuccess && (
                  <div className="dv-alert success">
                    <Check size={14} />
                    <span>{webhookSuccess}</span>
                  </div>
                )}
              </div>

              {/* ── LIVE STATUS, QUOTATION & TRANSCRIPT DISPLAY ── */}
              <div className="dv-live-status-box">
                <div className="dv-live-status-header">
                  <div>
                    <h4>Call Lifecycle &amp; Quotation Results</h4>
                    <small className="dv-muted">Query database for latest call status, quotation fields, and transcripts.</small>
                  </div>
                  <button
                    type="button"
                    className="dv-refresh-status-btn"
                    onClick={() => refreshStatus(callResult.workflow_run_id)}
                    disabled={refreshingStatus}
                  >
                    <RotateCw size={13} className={refreshingStatus ? "dv-spinning" : ""} />
                    <span>{refreshingStatus ? "Refreshing…" : "Refresh Call Status"}</span>
                  </button>
                </div>

                {liveStatus && (
                  <div className="dv-live-details">
                    <div className="dv-status-pills-row">
                      <span className={`dv-status-pill ${liveStatus.status}`}>
                        Status: <strong>{liveStatus.status}</strong>
                      </span>
                      {liveStatus.duration_seconds && (
                        <span className="dv-duration-pill">
                          Duration: {Math.round(liveStatus.duration_seconds)}s
                        </span>
                      )}
                      {liveStatus.quotation?.status && (
                        <span className="dv-quote-status-pill">
                          Quote: {liveStatus.quotation.status}
                        </span>
                      )}
                    </div>

                    {/* Extracted Quotation Fields */}
                    {liveStatus.quotation?.fields && Object.keys(liveStatus.quotation.fields).length > 0 && (
                      <div className="dv-quote-table-box">
                        <h5>Extracted Commercial Quotation</h5>
                        <div className="dv-quote-grid">
                          {Object.entries(liveStatus.quotation.fields).map(([name, f]) => (
                            <div key={name} className="dv-quote-item">
                              <small>{name.replace(/_/g, ' ')}</small>
                              <strong>{f.value}</strong>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Transcript Turns */}
                    {liveStatus.transcript && liveStatus.transcript.length > 0 && (
                      <div className="dv-transcript-box">
                        <h5>Conversation Transcript ({liveStatus.transcript.length} turns)</h5>
                        <div className="dv-transcript-feed">
                          {liveStatus.transcript.map((turn, idx) => (
                            <div key={idx} className={`dv-chat-turn ${turn.speaker}`}>
                              <span className="dv-speaker-badge">
                                {turn.speaker === 'assistant' ? 'AI Agent' : 'Vendor'}
                              </span>
                              <p>{turn.message}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
export default DograhVoicePanel;

