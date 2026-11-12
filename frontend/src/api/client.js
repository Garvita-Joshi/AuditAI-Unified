import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

let accessToken = null;
let refreshPromise = null;
export const setAccessToken = (token) => { accessToken = token; };

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const isAuthRequest = original?.url?.startsWith('/auth/');
    if (error.response?.status !== 401 || original?._retried || isAuthRequest) return Promise.reject(error);
    original._retried = true;
    try {
      refreshPromise ??= api.post('/auth/refresh').then(({ data }) => {
        setAccessToken(data.access_token); return data.access_token;
      }).finally(() => { refreshPromise = null; });
      const token = await refreshPromise;
      original.headers.Authorization = `Bearer ${token}`;
      return api(original);
    } catch (refreshError) {
      setAccessToken(null); window.dispatchEvent(new Event('auditai:session-expired'));
      return Promise.reject(refreshError);
    }
  },
);

export const authApi = {
  requestOtp: (payload) => api.post('/auth/request-otp', payload),
  verifyOtp: (payload) => api.post('/auth/verify-otp', payload),
  refresh: () => api.post('/auth/refresh'),
  logout: () => api.post('/auth/logout'),
  me: () => api.get('/auth/me'),
};

export const transfersApi = {
  cycles: (params) => api.get('/transfers/cycles', { params }),
  reconciliation: () => api.get('/transfers/reconciliation'),
  reviews: () => api.get('/transfer-reviews'),
  sendToReview: (body) => api.post('/transfer-reviews', body),
  decide: (id, stage, body) => api.post(`/transfer-reviews/${id}/${stage}`, body),
  upload: (formData) => api.post('/transfers/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
};

export const policiesApi = {
  list: (params) => api.get('/policies', { params }),
  run: () => api.post('/policies/run'),
  reviewers: () => api.get('/policies/reviewers'),
  authority: (id, limit) => api.put(`/policies/authorities/${id}`, { limit }),
  inputs: (id, body) => api.put(`/policies/claims/${encodeURIComponent(id)}`, body),
};

export const reviewQueueApi = {
  sync: () => api.post('/review-queue/sync'),
  list: (params) => api.get('/review-queue', { params }),
  detail: (id) => api.get(`/review-queue/${id}`),
  decide: (id, stage, body) => api.post(`/review-queue/${id}/${stage}`, body),
  comment: (id, notes) => api.post(`/review-queue/${id}/comments`, { notes }),
  reconcile: (claimId) => api.post(`/review-queue/reconciliation/${encodeURIComponent(claimId)}`),
  expense: (claimId) => api.post(`/review-queue/expense/${encodeURIComponent(claimId)}`),
};




export const claimsApi = {
  list: (params) => api.get('/claims', { params }),
  getDetail: (claimId) => api.get(`/claims/${claimId}`),
  upload: (formData) => api.post('/claims/upload', formData, { 
    headers: { 'Content-Type': 'multipart/form-data' } 
  }),
  uploadReceipt: (claimId, formData) => api.post(`/receipts/upload?claim_id=${claimId}`, formData, { 
    headers: { 'Content-Type': 'multipart/form-data' } 
  }),
};

export const receiptsApi = {
  get: (receiptId) => api.get(`/receipts/${receiptId}`),
};

export const fraudApi = {
  summary: () => api.get('/fraud/summary'),
  score: () => api.post('/fraud/score'),
  train: () => api.post('/fraud/train'),
};

export const reportsApi = {
  generate: (claimId) => api.post(`/reports/generate/${claimId}`),
  generateAll: () => api.post('/reports/generate-all'),
};

export const casesApi = {
  list: (params) => api.get('/cases', { params }),
  makerRecommend: (claimId, action, notes) =>
    api.post(`/cases/${claimId}/maker-recommend`, null, { params: { action, notes } }),
  checkerSignoff: (claimId, action, notes) =>
    api.post(`/cases/${claimId}/checker-signoff`, null, { params: { action, notes } }),
  getTrail: (claimId) => api.get(`/cases/${claimId}/trail`),
};

export const analyticsApi = {
  benford: () => api.get('/analytics/benford', { timeout: 20000 }),
  relatedParties: () => api.get('/analytics/related-parties', { timeout: 20000 }),
  sodViolations: () => api.get('/analytics/sod-violations', { timeout: 20000 }),
  caseMetrics: () => api.get('/analytics/case-metrics'),
};



export const recordsApi = { lookup: (records) => api.post('/review-records/lookup', { records }), detail: (kind, id) => api.get(`/review-records/${kind}/${encodeURIComponent(id)}`) };

export const masterDataApi = {
  status: () => api.get('/master-data/status'),
  upload: (dataset, file) => {const body=new FormData();body.append('file',file);return api.post(`/master-data/${dataset}/import`,body,{headers:{'Content-Type':'multipart/form-data'}});},
  run: (dataset) => api.post(`/master-checks/${dataset}/run`),
  findings: (dataset) => api.get(`/master-checks/${dataset}`),
  send: (id) => api.post(`/master-checks/findings/${id}/send-to-review`),
};

export const detectionApi={ overview:()=>api.get('/detection/overview'), recheck:()=>api.post('/detection/recheck') };

export const procurementApi = {
  workspace: async (deleted=false) => {
    const options = deleted ? {params:{deleted:true}} : undefined;
    const [purchases, sourcing] = await Promise.all([api.get('/procurement/requests',options), api.get('/sourcing',options)]);
    return { data: { purchases: purchases.data, sourcing: sourcing.data } };
  },
  extractQuote: (file) => { const data = new FormData(); data.append('file', file); return api.post('/procurement/extract-quote', data, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 }); },
  list: () => api.get('/procurement/requests'),
  detail: (id) => api.get(`/procurement/requests/${id}`),
  create: (payload) => api.post('/procurement/requests', payload),
  update: (id,payload) => api.put(`/procurement/requests/${id}`,payload),
  remove: id => api.delete(`/procurement/requests/${id}`),
  restore: id => api.post(`/procurement/requests/${id}/restore`),
  decision: (id, payload) => api.post(`/procurement/requests/${id}/decision`, payload),
  updateStep: (requestId, stepId, payload) => api.patch(`/procurement/requests/${requestId}/steps/${stepId}`, payload),
  decideStep: (requestId, stepId, payload) => api.post(`/procurement/requests/${requestId}/steps/${stepId}/decision`, payload),
  updateSubtask: (requestId, stepId, subtaskId, payload) => api.patch(`/procurement/requests/${requestId}/steps/${stepId}/subtasks/${subtaskId}`, payload),
  reviewers: () => api.get('/procurement/reviewers'),
  notifications: () => api.get('/procurement/notifications'),
  readNotification: (id) => api.post(`/procurement/notifications/${id}/read`),
  comment: (id, note) => api.post(`/procurement/requests/${id}/comments`, { note }),
  resubmit: (id, note) => api.post(`/procurement/requests/${id}/resubmit`, { note }),
  invoice: (id, payload) => api.post(`/procurement/orders/${id}/invoices`, payload),
  correct: (id, payload) => api.post(`/procurement/invoices/${id}/correct`, payload),
  correction: (id) => api.post(`/procurement/invoices/${id}/request-correction`),
  review: (id, note) => api.post(`/procurement/invoices/${id}/review`, { note }),
  revisions: (id) => api.get(`/procurement/invoices/${id}/revisions`),
  upload: (id, file, kind = 'supporting') => { const data = new FormData(); data.append('file', file); return api.post(`/procurement/requests/${id}/documents?kind=${kind}`, data, { headers: { 'Content-Type': 'multipart/form-data' } }); },
  download: (id) => api.get(`/procurement/documents/${id}`, { responseType: 'blob' }),
  paymentConfig: () => api.get('/procurement/payment-config'),
  checkout: (id) => api.post(`/procurement/invoices/${id}/checkout`),
  capture: (id) => api.post(`/procurement/invoices/${id}/capture`),
  directSettle: (id) => api.post(`/procurement/invoices/${id}/direct-settle`),
  paymentStatus: (id) => api.post(`/procurement/invoices/${id}/payment-status`),
  auditLog: (id) => api.get(`/procurement/requests/${id}/audit-log`),
  uploadInvoice: (file, requestId, mode) => { const data = new FormData(); data.append('file', file); if (requestId) data.append('request_id', String(requestId)); data.append('mode', mode || 'attach'); return api.post('/procurement/upload-invoice', data, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 90000 }); },
  requestsIndex: () => api.get('/procurement/requests-index'),
};

export const sourcingApi = {
  remove: id => api.delete(`/sourcing/${id}`),
  restore: id => api.post(`/sourcing/${id}/restore`),
  detail: id => api.get(`/sourcing/${id}`),
  auditLog: id => api.get(`/sourcing/${id}/audit-log`),
  evaluateFinalInvoice: (id, payload) => api.post(`/sourcing/${id}/evaluate-final-invoice`, payload || {}),
  paypalCheckout: id => api.post(`/sourcing/${id}/paypal/checkout`),
  paypalCapture: id => api.post(`/sourcing/${id}/paypal/capture`),
  paypalDirectSettle: id => api.post(`/sourcing/${id}/paypal/direct-settle`),
  workflow: id => api.post(`/sourcing/${id}/workflow`, {}, {timeout:60000}),
  search: (id,version) => api.post(`/sourcing/${id}/search`,{version}),
  searches: id => api.get(`/sourcing/${id}/searches`),
  document: (id,file,version) => {const body=new FormData();body.append('file',file);body.append('version',version);return api.post(`/sourcing/${id}/instruction-document`,body,{headers:{'Content-Type':'multipart/form-data'},timeout:60000});},
  contractDocuments: id => api.get(`/sourcing/${id}/contract-documents`),
  uploadContractDocument: (id,kind,file) => {const body=new FormData();body.append('kind',kind);body.append('file',file);return api.post(`/sourcing/${id}/contract-documents`,body,{headers:{'Content-Type':'multipart/form-data'}});},
  config: () => api.get('/sourcing/config'),
  list: () => api.get('/sourcing'),
  create: () => api.post('/sourcing'),
  message: (id, text, version) => api.post(`/sourcing/${id}/messages`, {text, version}, {timeout:60000}),
  save: (id, requirements, version, confirm=false, intakeStep) => api.put(`/sourcing/${id}`, {requirements, version, confirm, ...(intakeStep == null ? {} : {intake_step:intakeStep})}),
  startAgent: id => api.post(`/sourcing/${id}/agent/runs`, {}, {timeout:120000}),
  latestAgentRun: id => api.get(`/sourcing/${id}/agent/runs/latest`),
  agentConfig: () => api.get('/sourcing/agent/config'),
  sendAgentOutreach: (id,runId,vendorIds) => api.post(`/sourcing/${id}/agent/runs/${runId}/outreach`, {vendor_ids:vendorIds,confirm_send:true}, {timeout:60000}),
  recordAgentReply: (id,runId,vendorId,text) => api.post(`/sourcing/${id}/agent/runs/${runId}/vendors/${vendorId}/reply`, {text}),
  externalSearch: (id, query, location) => api.post(`/sourcing/${id}/agent/external-search`, {query, location}, {timeout:60000}),
  addVendor: (id, runId, payload) => api.post(`/sourcing/${id}/agent/runs/${runId}/vendors`, payload),
  reviewRfq: (id, runId, vendorId, payload) =>
    api.put(`/sourcing/${id}/agent/runs/${runId}/vendors/${vendorId}/rfq-review`, payload),
  sendAiRfqs: (id, runId, vendorIds) =>
    api.post(`/sourcing/${id}/agent/runs/${runId}/send-rfqs`, { vendor_ids: vendorIds, compose_with_ai: false, confirm_send: true }, { timeout: 120000 }),
  analyzeResponses: (id, runId) =>
    api.post(`/sourcing/${id}/agent/runs/${runId}/analyze`, {}, { timeout: 90000 }),
  getAgentRun: (id, runId) => api.get(`/sourcing/${id}/agent/runs/${runId}`),
  activityStreamUrl: (id, runId, token) =>
    `${api.defaults.baseURL}/sourcing/${id}/agent/runs/${runId}/activity-stream?token=${token}`,
  getSmtpStatus: () => api.get('/sourcing/smtp/status'),
  saveSmtpConfig: payload => api.post('/sourcing/smtp/config', payload),
  testSmtp: payload => api.post('/sourcing/smtp/test', payload),
  testInbox: () => api.post('/sourcing/smtp/test-inbox', {}),
  simulateVendorQuote: (id, runId, vendorId) => api.post(`/sourcing/${id}/agent/runs/${runId}/vendors/${vendorId}/simulate-quote`),
  simulateAllQuotes: (id, runId) => api.post(`/sourcing/${id}/agent/runs/${runId}/simulate-quotes`),
  getNegotiationReport: (id, runId) => api.post(`/sourcing/${id}/agent/runs/${runId}/negotiation-report`, {}, { timeout: 90000 }),
  checkInbox: (id, runId) => api.post(`/sourcing/${id}/agent/runs/${runId}/check-inbox`, {}, { timeout: 60000 }),
  sendCounteroffer: (id, runId, vendorId, payload) =>
    api.post(`/sourcing/${id}/agent/runs/${runId}/vendors/${vendorId}/send-counteroffer`, payload, { timeout: 60000 }),
  // Stage 6: Executive human approval gate — authorize Purchase Order
  approveWinner: (id, runId, payload) =>
    api.post(`/sourcing/${id}/agent/runs/${runId}/approve-winner`, payload || {}, { timeout: 30000 }),
};

export const dograhApi = {
  config: () => api.get('/voice/dograh/config'),
  startCall: (payload) => api.post('/voice/dograh/start-call', payload),
  startTwilioCall: (payload, forceLive = false) =>
    api.post(`/voice/twilio/start-call?force_live=${forceLive}`, payload),
  getStatus: (workflowRunId) => api.get(`/voice/dograh/status/${workflowRunId}`),
  postWebhook: (payload, secret) =>
    api.post('/voice/dograh/webhook', payload, {
      headers: secret ? { 'X-Dograh-Secret': secret } : {},
    }),
  postExotelCallback: (payload) => api.post('/voice/exotel/callback', payload),
  postTwilioCallback: (payload) => api.post('/voice/twilio/callback', payload),
};



export const assistantApi = {
  context: () => api.get('/assistant/context'),
  chat: (message, history) => api.post('/assistant/chat', { message, history }),
};

export default api;
