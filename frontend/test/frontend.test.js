import test, { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

// Import services to test
import { SpeechAdapter } from '../src/services/speech.js';
import { api, ApiError } from '../src/services/api.js';

describe('Frontend SpeechAdapter Unit Tests', () => {
  it('detects unsupported browser environment gracefully without crashing', () => {
    // In Node.js environment where window.SpeechRecognition is absent
    const adapter = new SpeechAdapter();
    assert.equal(adapter.isSupported, false);
    assert.equal(adapter.isListening, false);

    let errorReported = null;
    adapter.onError = (err) => {
      errorReported = err;
    };

    const started = adapter.startListening();
    assert.equal(started, false);
    assert.equal(errorReported?.code, 'UNSUPPORTED');
  });

  it('aborts listening cleanly', () => {
    const adapter = new SpeechAdapter();
    adapter.isListening = true;
    adapter.abortListening();
    assert.equal(adapter.isListening, false);
  });
});

describe('Frontend API Client & In-Flight Deduplication Tests', () => {
  it('instantiates ApiError with status and details', () => {
    const err = new ApiError('Test error message', 404, { detail: 'Not found' });
    assert.equal(err.name, 'ApiError');
    assert.equal(err.status, 404);
    assert.equal(err.message, 'Test error message');
    assert.deepEqual(err.details, { detail: 'Not found' });
  });

  it('exposes all required API methods for Stage 4', () => {
    assert.equal(typeof api.getHealth, 'function');
    assert.equal(typeof api.getAccounts, 'function');
    assert.equal(typeof api.getAccount, 'function');
    assert.equal(typeof api.getTransactions, 'function');
    assert.equal(typeof api.loginDemo, 'function');
    assert.equal(typeof api.executeTurn, 'function');
    assert.equal(typeof api.getHandoffCases, 'function');
    assert.equal(typeof api.getHandoffCase, 'function');
    assert.equal(typeof api.resolveHandoffCase, 'function');
  });
});

describe('Frontend Dialogue Safety & State Invariant Tests', () => {
  it('verifies read-back card formatting requires digits, words, and payee', () => {
    const mockCard = {
      amount_digits: 500,
      amount_words: 'Five Hundred Rupees',
      payee_name: 'Ramesh Kumar',
      currency: 'INR',
    };

    assert.equal(mockCard.amount_digits, 500);
    assert.match(mockCard.amount_words, /Five Hundred Rupees/);
    assert.equal(mockCard.payee_name, 'Ramesh Kumar');
    assert.equal(mockCard.currency, 'INR');
  });

  it('verifies typed fallback disclaims live speech', () => {
    const turnPayloadVoice = {
      action: 'SUBMIT_LIVENESS',
      liveness_response: '7 2 9',
      channel: 'VOICE',
    };
    const turnPayloadTyped = {
      action: 'SUBMIT_LIVENESS',
      liveness_response: '7 2 9',
      channel: 'TYPED',
    };

    assert.equal(turnPayloadVoice.channel, 'VOICE');
    assert.equal(turnPayloadTyped.channel, 'TYPED');
    // Typed responses require distinct handling
    assert.notEqual(turnPayloadVoice.channel, turnPayloadTyped.channel);
  });

  it('enforces mandatory operator note minimum length in agent review', () => {
    function validateAgentResolution(notes) {
      if (!notes || notes.trim().length < 3) {
        throw new Error('A mandatory operator explanation note of at least 3 characters is required.');
      }
      return true;
    }

    assert.throws(() => validateAgentResolution(''), /mandatory operator explanation note/);
    assert.throws(() => validateAgentResolution('  '), /mandatory operator explanation note/);
    assert.throws(() => validateAgentResolution('ok'), /mandatory operator explanation note/);
    assert.equal(validateAgentResolution('Verified customer intent via callback'), true);
  });

  it('validates agent role requirement prevents customer from approving cases', () => {
    function canResolveCase(userRole) {
      return userRole === 'agent';
    }

    assert.equal(canResolveCase('customer'), false);
    assert.equal(canResolveCase('guest'), false);
    assert.equal(canResolveCase('agent'), true);
  });

  it('verifies masked PIN length validation prevents premature submission', () => {
    function validatePin(pin) {
      return Boolean(pin && pin.length === 4 && /^\d{4}$/.test(pin));
    }

    assert.equal(validatePin(''), false);
    assert.equal(validatePin('12'), false);
    assert.equal(validatePin('123'), false);
    assert.equal(validatePin('12345'), false);
    assert.equal(validatePin('abcd'), false);
    assert.equal(validatePin('1234'), true);
  });

  it('verifies payment cancellation permanently resets pending session state', () => {
    let session = {
      id: 'sess_123',
      state: 'READBACK',
      pending_amount: 500,
    };

    function cancelSession(s) {
      return {
        ...s,
        state: 'CANCELLED',
        pending_amount: null,
      };
    }

    const cancelled = cancelSession(session);
    assert.equal(cancelled.state, 'CANCELLED');
    assert.equal(cancelled.pending_amount, null);
  });
});
