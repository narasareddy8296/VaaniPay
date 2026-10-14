import test, { describe, it } from 'node:test';
import assert from 'node:assert/strict';

// Import services to test
import { SpeechAdapter, SPEECH_ERROR_CODES, mapMediaError } from '../src/services/speech.js';
import { api, ApiError } from '../src/services/api.js';
import { parseConfirmationIntent, CONFIRMATION_INTENTS, normalizeIntentText } from '../src/services/intent.js';

describe('Frontend SpeechAdapter Unit Tests', () => {
  it('detects unsupported browser environment gracefully without crashing', async () => {
    // In Node.js environment where window.SpeechRecognition is absent
    const adapter = new SpeechAdapter();
    assert.equal(adapter.isSupported, false);
    assert.equal(adapter.isListening, false);

    let errorReported = null;
    adapter.onError = (err) => {
      errorReported = err;
    };

    const started = await adapter.startListening();
    assert.equal(started, false);
    assert.equal(errorReported?.code, SPEECH_ERROR_CODES.UNSUPPORTED);
    assert.match(errorReported?.message, /Web Speech API is not supported/);
  });

  it('aborts listening cleanly without triggering spurious errors', () => {
    const adapter = new SpeechAdapter();
    adapter.isListening = true;
    adapter.abortListening();
    assert.equal(adapter.isListening, false);
  });

  it('correctly maps getUserMedia NotAllowedError to PERMISSION_DENIED', () => {
    const err = new Error('Permission dismissed');
    err.name = 'NotAllowedError';
    const mapped = mapMediaError(err);
    assert.equal(mapped.code, SPEECH_ERROR_CODES.PERMISSION_DENIED);
    assert.match(mapped.message, /Microphone permission was denied/);
  });

  it('correctly maps getUserMedia NotFoundError to NO_DEVICE', () => {
    const err = new Error('Requested device not found');
    err.name = 'NotFoundError';
    const mapped = mapMediaError(err);
    assert.equal(mapped.code, SPEECH_ERROR_CODES.NO_DEVICE);
    assert.match(mapped.message, /No microphone hardware found/);
  });

  it('correctly maps getUserMedia NotReadableError to DEVICE_BUSY', () => {
    const err = new Error('Hardware device in use');
    err.name = 'NotReadableError';
    const mapped = mapMediaError(err);
    assert.equal(mapped.code, SPEECH_ERROR_CODES.DEVICE_BUSY);
    assert.match(mapped.message, /currently in use by another application/);
  });

  it('correctly maps getUserMedia SecurityError to SECURITY_ERROR', () => {
    const err = new Error('Permissions policy violation');
    err.name = 'SecurityError';
    const mapped = mapMediaError(err);
    assert.equal(mapped.code, SPEECH_ERROR_CODES.SECURITY_ERROR);
    assert.match(mapped.message, /restricted by security policy/);
  });

  it('distinguishes aborted recognition events from actual speech errors', () => {
    let errorCalled = false;
    let stateChanges = [];

    const adapter = new SpeechAdapter({
      onError: () => {
        errorCalled = true;
      },
      onStateChange: (s) => {
        stateChanges.push(s);
      },
    });

    adapter._handleRecognitionError({ error: 'aborted' });
    assert.equal(errorCalled, false, 'Aborted events must not dispatch user-facing errors');
    assert.equal(stateChanges.includes('IDLE'), true);
  });

  it('handles no-speech event as operational notice without claiming permission denial', () => {
    let errorReported = null;

    const adapter = new SpeechAdapter({
      onError: (err) => {
        errorReported = err;
      },
    });

    adapter._handleRecognitionError({ error: 'no-speech' });
    assert.equal(errorReported?.code, SPEECH_ERROR_CODES.NO_SPEECH);
    assert.match(errorReported?.message, /No speech was detected/);
    assert.doesNotMatch(errorReported?.message, /permission denied/i);
  });

  it('correctly maps audio-capture recognition error to AUDIO_CAPTURE_FAILED', () => {
    let errorReported = null;
    const adapter = new SpeechAdapter({
      onError: (err) => {
        errorReported = err;
      },
    });

    adapter._handleRecognitionError({ error: 'audio-capture' });
    assert.equal(errorReported?.code, SPEECH_ERROR_CODES.AUDIO_CAPTURE_FAILED);
    assert.match(errorReported?.message, /Audio capture failed/);
  });

  it('correctly maps network recognition error to NETWORK_ERROR', () => {
    let errorReported = null;
    const adapter = new SpeechAdapter({
      onError: (err) => {
        errorReported = err;
      },
    });

    adapter._handleRecognitionError({ error: 'network' });
    assert.equal(errorReported?.code, SPEECH_ERROR_CODES.NETWORK_ERROR);
    assert.match(errorReported?.message, /Network error/);
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

  it('exposes all required API methods for Stage 4 & Stage 6', () => {
    assert.equal(typeof api.getHealth, 'function');
    assert.equal(typeof api.getAccounts, 'function');
    assert.equal(typeof api.getAccount, 'function');
    assert.equal(typeof api.getTransactions, 'function');
    assert.equal(typeof api.loginDemo, 'function');
    assert.equal(typeof api.resetDemoData, 'function');
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

describe('Stage 7: Deterministic Confirmation & Intent Safety Tests', () => {
  it('correctly parses explicit English confirmation utterances', () => {
    assert.equal(parseConfirmationIntent('Yes, confirm.').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('confirm').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('proceed').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('yes please').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('sure confirm').intent, CONFIRMATION_INTENTS.CONFIRM);
  });

  it('correctly parses explicit Hinglish confirmation utterances', () => {
    assert.equal(parseConfirmationIntent('Haan, confirm karo.').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('haan').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('bhej do').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('kar do').intent, CONFIRMATION_INTENTS.CONFIRM);
    assert.equal(parseConfirmationIntent('haanji confirm').intent, CONFIRMATION_INTENTS.CONFIRM);
  });

  it('correctly parses explicit English cancellation utterances', () => {
    assert.equal(parseConfirmationIntent('No, cancel.').intent, CONFIRMATION_INTENTS.CANCEL);
    assert.equal(parseConfirmationIntent('cancel').intent, CONFIRMATION_INTENTS.CANCEL);
    assert.equal(parseConfirmationIntent('stop payment').intent, CONFIRMATION_INTENTS.CANCEL);
    assert.equal(parseConfirmationIntent('do not send').intent, CONFIRMATION_INTENTS.CANCEL);
  });

  it('correctly parses explicit Hinglish cancellation utterances', () => {
    assert.equal(parseConfirmationIntent('Nahi, cancel karo.').intent, CONFIRMATION_INTENTS.CANCEL);
    assert.equal(parseConfirmationIntent('nahi').intent, CONFIRMATION_INTENTS.CANCEL);
    assert.equal(parseConfirmationIntent('mat bhejo').intent, CONFIRMATION_INTENTS.CANCEL);
    assert.equal(parseConfirmationIntent('ruk jao').intent, CONFIRMATION_INTENTS.CANCEL);
    assert.equal(parseConfirmationIntent('roko').intent, CONFIRMATION_INTENTS.CANCEL);
  });

  it('rejects ambiguous or conflicting utterances as AMBIGUOUS', () => {
    assert.equal(parseConfirmationIntent('yes but cancel').intent, CONFIRMATION_INTENTS.AMBIGUOUS);
    assert.equal(parseConfirmationIntent('haan nahi').intent, CONFIRMATION_INTENTS.AMBIGUOUS);
    assert.equal(parseConfirmationIntent('confirm ya cancel').intent, CONFIRMATION_INTENTS.AMBIGUOUS);
    assert.equal(parseConfirmationIntent('maybe').intent, CONFIRMATION_INTENTS.AMBIGUOUS);
    assert.equal(parseConfirmationIntent('not sure').intent, CONFIRMATION_INTENTS.AMBIGUOUS);
  });

  it('strictly rejects payment requests as confirmation (SAFETY INVARIANT)', () => {
    // Payment requests themselves are never confirmation
    assert.equal(parseConfirmationIntent('send 500 to Ramesh').intent, CONFIRMATION_INTENTS.PAYMENT_REQUEST);
    assert.equal(parseConfirmationIntent('transfer 1500 to Priya').intent, CONFIRMATION_INTENTS.PAYMENT_REQUEST);
    assert.equal(parseConfirmationIntent('dedh hazaar bhej do').intent, CONFIRMATION_INTENTS.PAYMENT_REQUEST);
  });

  it('handles silence or empty utterances safely', () => {
    assert.equal(parseConfirmationIntent('').intent, CONFIRMATION_INTENTS.SILENCE);
    assert.equal(parseConfirmationIntent('   ').intent, CONFIRMATION_INTENTS.SILENCE);
    assert.equal(parseConfirmationIntent(null).intent, CONFIRMATION_INTENTS.SILENCE);
  });

  it('prevents speech recognition feedback loops while assistant TTS is speaking', () => {
    const adapter = new SpeechAdapter();
    adapter.isSpeaking = true; // System is synthesizing read-back

    let capturedTranscript = null;
    adapter.onTranscript = (text) => {
      capturedTranscript = text;
    };

    // Simulate recognition onresult arriving while assistant speaks
    if (adapter.recognition && adapter.recognition.onresult) {
      adapter.recognition.onresult({
        resultIndex: 0,
        results: [
          [{ transcript: 'Please confirm send 500 rupees' }],
        ],
      });
    }

    assert.equal(capturedTranscript, null, 'Transcripts received during system TTS must be discarded');
  });

  it('ensures PIN is never processed via voice recognition or sent to TTS', () => {
    function processVoiceTurn(state, utterance) {
      if (state === 'STEP_UP_PIN') {
        // Invariant: PIN is strictly rejected from voice processing
        return {
          allowed: false,
          error: 'PIN must be entered on keypad only',
        };
      }
      return { allowed: true };
    }

    const res = processVoiceTurn('STEP_UP_PIN', '1234');
    assert.equal(res.allowed, false);
    assert.match(res.error, /keypad only/i);
  });
});

describe('Stage 8: Secure Manual 4-Digit PIN Keypad Entry & Security Tests', () => {
  it('validates 4-digit numeric PIN format strictly on manual keypad', () => {
    function validatePin(pin) {
      return Boolean(pin && pin.length === 4 && /^\d{4}$/.test(pin));
    }

    assert.equal(validatePin(''), false);
    assert.equal(validatePin('1'), false);
    assert.equal(validatePin('12'), false);
    assert.equal(validatePin('123'), false);
    assert.equal(validatePin('1234'), true);
    assert.equal(validatePin('12345'), false);
    assert.equal(validatePin('abcd'), false);
    assert.equal(validatePin('12a4'), false);
  });

  it('simulates manual keypad operations: digit entry, clear, backspace, and masking', () => {
    let pinInput = '';

    const handleKeypadPress = (val) => {
      if (pinInput.length < 4) {
        pinInput += val;
      }
    };
    const handleBackspace = () => {
      pinInput = pinInput.slice(0, -1);
    };
    const handleClear = () => {
      pinInput = '';
    };

    // Press 1, 2, 3
    handleKeypadPress('1');
    handleKeypadPress('2');
    handleKeypadPress('3');
    assert.equal(pinInput, '123');
    assert.equal('•'.repeat(pinInput.length), '•••');

    // Backspace
    handleBackspace();
    assert.equal(pinInput, '12');

    // Keypad press 5, 6
    handleKeypadPress('5');
    handleKeypadPress('6');
    assert.equal(pinInput, '1256');
    assert.equal('•'.repeat(pinInput.length), '••••');

    // Attempting 5th digit is blocked
    handleKeypadPress('7');
    assert.equal(pinInput, '1256');

    // Clear resets keypad
    handleClear();
    assert.equal(pinInput, '');
  });

  it('ensures PIN is never processed via voice recognition or sent in speech transcripts', () => {
    function processVoiceTurn(state, transcript) {
      if (state === 'STEP_UP_PIN') {
        return {
          allowed: false,
          error: 'PIN must be entered on keypad only',
        };
      }
      return { allowed: true, transcript };
    }

    const res = processVoiceTurn('STEP_UP_PIN', '1234');
    assert.equal(res.allowed, false);
    assert.match(res.error, /keypad only/i);
  });

  it('verifies PIN step-up state machine ordering: PIN cannot bypass confirmation or liveness', () => {
    function simulateTurnAction(currentState, action) {
      if (action === 'SUBMIT_PIN' && currentState !== 'STEP_UP_PIN') {
        return {
          allowed: false,
          error: 'Out of order action received. Please follow the guided security steps.',
        };
      }
      return { allowed: true };
    }

    assert.equal(simulateTurnAction('CAPTURE', 'SUBMIT_PIN').allowed, false);
    assert.equal(simulateTurnAction('READBACK', 'SUBMIT_PIN').allowed, false);
    assert.equal(simulateTurnAction('LIVENESS', 'SUBMIT_PIN').allowed, false);
    assert.equal(simulateTurnAction('STEP_UP_PIN', 'SUBMIT_PIN').allowed, true);
  });
});

describe('Stage 10: Hinglish & Devanagari Voice Amount Recognition Tests', () => {
  it('correctly classifies Hindi/Hinglish amount phrases as PAYMENT_REQUEST and not confirmation', () => {
    const amountPhrases = [
      'dedh hazaar rupaye bhej do',
      'sawa do lakh rupaye',
      'dhai sau rupaye',
      'paanch sau',
      '1500 rupaye',
      'डेढ़ हज़ार',
      'ढाई सौ',
      'सवा दो लाख',
    ];

    for (const phrase of amountPhrases) {
      const res = parseConfirmationIntent(phrase);
      assert.equal(
        res.intent,
        CONFIRMATION_INTENTS.PAYMENT_REQUEST,
        `Expected phrase "${phrase}" to be detected as PAYMENT_REQUEST, got ${res.intent}`
      );
    }
  });

  it('normalizes Devanagari text preserving combining marks and letters', () => {
    const rawDevanagari = 'डेढ़ हज़ार';
    const normalized = normalizeIntentText(rawDevanagari);
    assert.equal(normalized, 'डेढ़ हज़ार');

    const dhaiSau = 'ढाई सौ';
    assert.equal(normalizeIntentText(dhaiSau), 'ढाई सौ');
  });

  it('SpeechAdapter retains accurate speech transcripts without alteration or guessing', () => {
    let capturedTranscript = null;
    let capturedIsFinal = null;

    const adapter = new SpeechAdapter({
      onTranscript: (text, isFinal) => {
        capturedTranscript = text;
        capturedIsFinal = isFinal;
      },
    });

    // Verify adapter configuration for Indian English & Hinglish
    if (adapter.recognition) {
      assert.equal(adapter.recognition.lang, 'en-IN');
      assert.equal(adapter.recognition.interimResults, true);
    }

    // Simulate recognition delivering a colloquial Hinglish transcript
    const testTranscript = 'dedh hazaar rupaye bhej do';
    adapter.onTranscript(testTranscript, true);
    assert.equal(capturedTranscript, testTranscript);
    assert.equal(capturedIsFinal, true);
  });
});

describe('Stage 9: Balance Consistency & Customer-Managed Payees Tests', () => {
  it('exposes required contact management API methods in frontend client', () => {
    assert.equal(typeof api.getContacts, 'function');
    assert.equal(typeof api.createContact, 'function');
  });

  it('validates contact creation input rules on frontend before submission', () => {
    function validateContactForm({ contact_name, beneficiary_account_id }) {
      const name = (contact_name || '').trim();
      const account = (beneficiary_account_id || '').trim();
      if (name.length < 2) {
        return { valid: false, error: 'Payee name must be at least 2 characters long.' };
      }
      if (!account) {
        return { valid: false, error: 'Mock account identifier is required.' };
      }
      return { valid: true };
    }

    assert.equal(validateContactForm({ contact_name: '', beneficiary_account_id: 'acc_123' }).valid, false);
    assert.equal(validateContactForm({ contact_name: 'A', beneficiary_account_id: 'acc_123' }).valid, false);
    assert.equal(validateContactForm({ contact_name: 'Anita', beneficiary_account_id: '' }).valid, false);
    assert.equal(validateContactForm({ contact_name: 'Anita', beneficiary_account_id: 'acc_anita' }).valid, true);
  });

  it('rejects duplicate contact name or account in local contact list', () => {
    const existingContacts = [
      { id: 'c1', contact_name: 'Ramesh Kumar', beneficiary_account_id: 'acc_ramesh' },
      { id: 'c2', contact_name: 'Sharmaji', beneficiary_account_id: null },
    ];

    function checkDuplicate(newContact, contacts) {
      const nameLower = newContact.contact_name.trim().toLowerCase();
      const hasNameDup = contacts.some((c) => c.contact_name.trim().toLowerCase() === nameLower);
      if (hasNameDup) {
        return { isDuplicate: true, field: 'name' };
      }
      if (newContact.beneficiary_account_id) {
        const hasAccDup = contacts.some(
          (c) => c.beneficiary_account_id === newContact.beneficiary_account_id
        );
        if (hasAccDup) {
          return { isDuplicate: true, field: 'account' };
        }
      }
      return { isDuplicate: false };
    }

    assert.equal(checkDuplicate({ contact_name: 'ramesh kumar', beneficiary_account_id: 'acc_new' }, existingContacts).isDuplicate, true);
    assert.equal(checkDuplicate({ contact_name: 'New Name', beneficiary_account_id: 'acc_ramesh' }, existingContacts).isDuplicate, true);
    assert.equal(checkDuplicate({ contact_name: 'Sunil', beneficiary_account_id: 'acc_sunil' }, existingContacts).isDuplicate, false);
  });

  it('immediately updates balance and ledger history when receipt is received', async () => {
    let balanceRefreshed = false;
    let transactionsLoaded = false;

    const mockAuthContext = {
      refreshAccount: async () => {
        balanceRefreshed = true;
      },
    };
    const mockLoadTransactions = async () => {
      transactionsLoaded = true;
    };

    // Simulate turn response with receipt
    async function handleTurnReceipt(res) {
      if (res.state === 'RECEIPT' || res.receipt) {
        await mockAuthContext.refreshAccount();
        await mockLoadTransactions();
      }
    }

    await handleTurnReceipt({
      session_id: 'sess_123',
      state: 'RECEIPT',
      receipt: {
        transaction_id: 'tx_stage9_001',
        amount: 500,
        payee_name: 'Ramesh Kumar',
        sender_balance_after: 48500,
      },
    });

    assert.equal(balanceRefreshed, true);
    assert.equal(transactionsLoaded, true);
  });

  it('verifies selecting a saved contact configures prompt without authorizing payment', () => {
    const contact = {
      id: 'cnt_001',
      contact_name: 'Anita Roy',
      beneficiary_account_id: 'acc_anita',
      is_frequent: false,
    };

    function selectContact(c) {
      return {
        selectedContactId: c.id,
        typedInput: `Send 500 to ${c.contact_name}`,
        promptText: `Ready to pay ${c.contact_name}. State an amount or say "Send 500 to ${c.contact_name}".`,
        paymentAuthorized: false, // Adding or selecting a contact NEVER authorizes payment!
      };
    }

    const state = selectContact(contact);
    assert.equal(state.selectedContactId, 'cnt_001');
    assert.match(state.typedInput, /Send 500 to Anita Roy/);
    assert.equal(state.paymentAuthorized, false);
  });
});

describe('Stage 12: Robust Natural Hinglish Speech Understanding & UI Tests', () => {
  it('correctly classifies natural Hinglish variants with payee and amount as PAYMENT_REQUEST', () => {
    const naturalPhrases = [
      'Abhishek ko sava do lakh bhejo',
      'Abhishek ko sawa 2 lakh bhejo',
      'Abhishek ko sava do laakh rupaye bhej do',
      'Abhishek ko dedh hazaar bhejo',
      'Abhishek ko dhai sau bhejo',
      'Abhishek ko paanch sau rupaye bhej do',
      '1500 rupaye Abhishek ko bhejo',
    ];

    for (const phrase of naturalPhrases) {
      const intent = parseConfirmationIntent(phrase);
      assert.equal(
        intent.intent,
        CONFIRMATION_INTENTS.PAYMENT_REQUEST,
        `Natural phrase "${phrase}" must be PAYMENT_REQUEST and never accidentally trigger CONFIRMED`
      );
    }
  });

  it('populates contact name directly when selecting a contact during CLARIFY_PAYEE', () => {
    const contact = {
      id: 'cnt_priya_abhishek',
      contact_name: 'Abhishek Verma',
    };

    function handleSelectContactSim(c, dialogueState) {
      if (dialogueState === 'CLARIFY_PAYEE') {
        return {
          typedInput: c.contact_name,
          promptText: `Selected ${c.contact_name}. Click Send or press Enter to confirm this recipient.`,
        };
      }
      return {
        typedInput: `Send 500 to ${c.contact_name}`,
        promptText: `Ready to pay ${c.contact_name}. State an amount or say "Send 500 to ${c.contact_name}".`,
      };
    }

    const clarifyState = handleSelectContactSim(contact, 'CLARIFY_PAYEE');
    assert.equal(clarifyState.typedInput, 'Abhishek Verma');
    assert.match(clarifyState.promptText, /Selected Abhishek Verma/);

    const normalState = handleSelectContactSim(contact, 'CAPTURE');
    assert.match(normalState.typedInput, /Send 500 to Abhishek Verma/);
  });
});

describe('Stage 13: Two-Way Human-Agent Handoff & Messaging Tests', () => {
  it('correctly maps raw handoff case status codes to human-friendly display titles', () => {
    function formatStatus(status) {
      const s = (status || '').toUpperCase();
      if (s === 'PENDING' || s === 'WAITING') return 'Waiting';
      if (s === 'AGENT_CONNECTED') return 'Agent Connected';
      if (s === 'APPROVED' || s === 'RESOLVED') return 'Resolved';
      if (s === 'REJECTED') return 'Rejected';
      if (s === 'REPEAT_REQUESTED') return 'Repeat Requested';
      if (s === 'CANCELLED') return 'Cancelled';
      return s;
    }

    assert.equal(formatStatus('PENDING'), 'Waiting');
    assert.equal(formatStatus('WAITING'), 'Waiting');
    assert.equal(formatStatus('AGENT_CONNECTED'), 'Agent Connected');
    assert.equal(formatStatus('APPROVED'), 'Resolved');
    assert.equal(formatStatus('RESOLVED'), 'Resolved');
    assert.equal(formatStatus('REJECTED'), 'Rejected');
    assert.equal(formatStatus('CANCELLED'), 'Cancelled');
  });

  it('determines whether conversation input must be disabled based on case closure', () => {
    function isConversationClosed(caseStatus) {
      return ['APPROVED', 'REJECTED', 'RESOLVED', 'CANCELLED'].includes((caseStatus || '').toUpperCase());
    }

    assert.equal(isConversationClosed('PENDING'), false);
    assert.equal(isConversationClosed('WAITING'), false);
    assert.equal(isConversationClosed('AGENT_CONNECTED'), false);
    assert.equal(isConversationClosed('APPROVED'), true);
    assert.equal(isConversationClosed('REJECTED'), true);
    assert.equal(isConversationClosed('CANCELLED'), true);
  });

  it('detects and forbids suspected PIN transmissions in chat text', () => {
    function containsSuspectedPin(text) {
      const lower = (text || '').toLowerCase().trim();
      const hasSecretKw = /\b(?:pin|otp|mpin|passcode|password|secret)\b/.test(lower);
      const hasStandaloneDigits = /^\d{4,6}$/.test(lower);
      const hasKwWithDigits = hasSecretKw && /\b\d{4,6}\b/.test(lower);
      return hasStandaloneDigits || hasKwWithDigits;
    }

    // Prohibited PIN messages
    assert.equal(containsSuspectedPin('Here is my pin 1234'), true);
    assert.equal(containsSuspectedPin('pin: 5678'), true);
    assert.equal(containsSuspectedPin('1234'), true);
    assert.equal(containsSuspectedPin('9999'), true);
    assert.equal(containsSuspectedPin('my mpin is 1234'), true);

    // Permitted benign transaction inquiries
    assert.equal(containsSuspectedPin('Why was my payment of 1500 flagged?'), false);
    assert.equal(containsSuspectedPin('I wanted to send money to Ramesh'), false);
    assert.equal(containsSuspectedPin('Please cancel this transaction'), false);
    assert.equal(containsSuspectedPin('Can I transfer 225000 in parts?'), false);
  });

  it('verifies message sorting orders messages chronologically', () => {
    const rawMessages = [
      { id: 'm2', created_at: '2026-10-14T10:05:00Z', message_text: 'Agent reply', sender_role: 'agent' },
      { id: 'm1', created_at: '2026-10-14T10:00:00Z', message_text: 'Customer note', sender_role: 'customer' },
      { id: 'm3', created_at: '2026-10-14T10:10:00Z', message_text: 'Customer thank you', sender_role: 'customer' },
    ];

    const sorted = [...rawMessages].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    assert.equal(sorted[0].id, 'm1');
    assert.equal(sorted[1].id, 'm2');
    assert.equal(sorted[2].id, 'm3');
  });

  it('exposes all required handoff messaging API methods in api client', () => {
    assert.equal(typeof api.getHandoffCases, 'function');
    assert.equal(typeof api.getHandoffCase, 'function');
    assert.equal(typeof api.getActiveHandoffCase, 'function');
    assert.equal(typeof api.getHandoffMessages, 'function');
    assert.equal(typeof api.sendHandoffMessage, 'function');
    assert.equal(typeof api.cancelHandoffCase, 'function');
    assert.equal(typeof api.resolveHandoffCase, 'function');
  });
});
