/**
 * Central API Client for VaaniPay Frontend.
 * Interacts with FastAPI backend services.
 * Enforces server-validated session credentials (Authorization: Bearer <token>),
 * in-flight deduplication, error handling, and session tracking.
 */

const API_BASE_URL =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) ||
  (typeof process !== 'undefined' && process.env?.VITE_API_BASE_URL) ||
  'http://localhost:8000';
const API_PREFIX = '/api/v1';

class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

// In-flight request tracker to prevent duplicate concurrent submissions
const activeRequests = new Set();

async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  const requestKey = `${options.method || 'GET'}:${url}:${JSON.stringify(options.body || '')}`;

  if (activeRequests.has(requestKey) && options.method === 'POST') {
    throw new ApiError('Duplicate request in progress. Please wait.', 429);
  }

  if (options.method === 'POST') {
    activeRequests.add(requestKey);
  }

  try {
    const sessionToken =
      typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('vaanipay_session_token') : null;

    const config = {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}),
        ...(options.headers || {}),
      },
    };

    const response = await fetch(url, config);

    let data = null;
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = text ? { detail: text } : {};
    }

    if (!response.ok) {
      const errorMsg = data?.detail || data?.error || `Request failed with status ${response.status}`;
      throw new ApiError(errorMsg, response.status, data);
    }

    return data;
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    // Network or connection failure
    throw new ApiError(
      `Failed to connect to VaaniPay backend at ${API_BASE_URL}. Please ensure the backend server is running.`,
      0,
      { originalError: err.message }
    );
  } finally {
    if (options.method === 'POST') {
      activeRequests.delete(requestKey);
    }
  }
}

export const api = {
  // Service Health
  getHealth: () => request(`${API_PREFIX}/health`),

  // Accounts & Profile
  getAccounts: () => request(`${API_PREFIX}/accounts`),
  getAccount: (accountId) => request(`${API_PREFIX}/accounts/${accountId}`),
  getTransactions: (accountId) => request(`${API_PREFIX}/accounts/${accountId}/transactions`),
  getContacts: (accountId) => request(`${API_PREFIX}/accounts/${accountId}/contacts`),
  createContact: (accountId, contactData) =>
    request(`${API_PREFIX}/accounts/${accountId}/contacts`, {
      method: 'POST',
      body: JSON.stringify(contactData),
    }),

  loginDemo: async (accountId) => {
    const res = await request(`${API_PREFIX}/accounts/demo-login`, {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId }),
    });
    if (res?.session_token && typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('vaanipay_session_token', res.session_token);
      sessionStorage.setItem('vaanipay_demo_user', accountId);
    }
    return res;
  },

  // Evaluator convenience demo reset
  resetDemoData: () =>
    request(`${API_PREFIX}/accounts/demo-reset`, {
      method: 'POST',
    }),

  // Dialogue State Machine Turn
  executeTurn: (payload) =>
    request(`${API_PREFIX}/turn`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Human Handoff Queue & Two-Way Messaging
  getHandoffCases: (statusFilter = null) => {
    const query = statusFilter && statusFilter !== 'ALL' ? `?status=${encodeURIComponent(statusFilter)}` : '';
    return request(`${API_PREFIX}/handoff/cases${query}`);
  },
  getHandoffCase: (caseId) => request(`${API_PREFIX}/handoff/cases/${caseId}`),
  getActiveHandoffCase: () => request(`${API_PREFIX}/handoff/cases/active`),
  getHandoffMessages: (caseId) => request(`${API_PREFIX}/handoff/cases/${caseId}/messages`),
  sendHandoffMessage: (caseId, messageText) =>
    request(`${API_PREFIX}/handoff/cases/${caseId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ message_text: messageText }),
    }),
  cancelHandoffCase: (caseId) =>
    request(`${API_PREFIX}/handoff/cases/${caseId}/cancel`, {
      method: 'POST',
    }),
  resolveHandoffCase: (caseId, payload) =>
    request(`${API_PREFIX}/handoff/cases/${caseId}/resolve`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

export { ApiError, API_BASE_URL };
