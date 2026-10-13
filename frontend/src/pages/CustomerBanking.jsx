import React, { useState, useEffect, useRef, useId } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { SpeechAdapter } from '../services/speech';

export function CustomerBanking() {
  const { currentUser, refreshAccount } = useAuth();

  // Banking State
  const [transactions, setTransactions] = useState([]);
  const [showTransactions, setShowTransactions] = useState(false);

  // Dialogue FSM State
  const [sessionId, setSessionId] = useState(null);
  const [dialogueState, setDialogueState] = useState('CAPTURE'); // CAPTURE, CLARIFY_AMOUNT, CLARIFY_PAYEE, READBACK, LIVENESS, STEP_UP_PIN, RECEIPT, HANDOFF, CANCELLED, FAILED
  const [promptText, setPromptText] = useState('How can I help you today? State an amount and payee in English or Hinglish.');
  const [readbackCard, setReadbackCard] = useState(null);
  const [livenessChallenge, setLivenessChallenge] = useState(null);
  const [challengeTtl, setChallengeTtl] = useState(30);
  const [receipt, setReceipt] = useState(null);
  const [handoffCaseId, setHandoffCaseId] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  // Input States
  const [transcript, setTranscript] = useState('');
  const [typedInput, setTypedInput] = useState('');
  const [speechState, setSpeechState] = useState('IDLE'); // IDLE, LISTENING, PROCESSING, ERROR
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pinInput, setPinInput] = useState('');
  const [pinError, setPinError] = useState(null);

  // Speech Adapter Instance
  const speechAdapterRef = useRef(null);
  const ttlTimerRef = useRef(null);

  useEffect(() => {
    loadTransactions();

    // Initialize replaceable SpeechAdapter
    speechAdapterRef.current = new SpeechAdapter({
      onTranscript: (spokenText, isFinal) => {
        setTranscript(spokenText);
        if (isFinal) {
          submitSpeechTurn(spokenText);
        }
      },
      onStateChange: (state) => {
        setSpeechState(state);
      },
      onError: (err) => {
        setErrorMessage(err.message);
      },
    });

    return () => {
      if (speechAdapterRef.current) {
        speechAdapterRef.current.abortListening();
        speechAdapterRef.current.stopSpeaking();
      }
      if (ttlTimerRef.current) {
        clearInterval(ttlTimerRef.current);
      }
    };
  }, [currentUser]);

  async function loadTransactions() {
    if (!currentUser) return;
    try {
      const data = await api.getTransactions(currentUser.id);
      setTransactions(data);
    } catch (err) {
      console.warn('Could not load transactions:', err);
    }
  }

  // Handle Liveness TTL Countdown
  useEffect(() => {
    if (dialogueState === 'LIVENESS' && livenessChallenge) {
      setChallengeTtl(30);
      if (ttlTimerRef.current) clearInterval(ttlTimerRef.current);

      ttlTimerRef.current = setInterval(() => {
        setChallengeTtl((prev) => {
          if (prev <= 1) {
            clearInterval(ttlTimerRef.current);
            setErrorMessage('Liveness challenge expired (30s TTL exceeded). Please request a new turn.');
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    } else {
      if (ttlTimerRef.current) clearInterval(ttlTimerRef.current);
    }

    return () => {
      if (ttlTimerRef.current) clearInterval(ttlTimerRef.current);
    };
  }, [dialogueState, livenessChallenge]);

  // Read-Back Audio Synthesis
  useEffect(() => {
    if (dialogueState === 'READBACK' && readbackCard) {
      const speechText = `Please confirm: send ${readbackCard.amount_words} to ${readbackCard.payee_name}.`;
      if (speechAdapterRef.current) {
        speechAdapterRef.current.speak(speechText);
      }
    }
  }, [dialogueState, readbackCard]);

  // =========================================================================
  // STATE MACHINE TURN DISPATCHERS
  // =========================================================================

  async function sendTurnRequest(payload) {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const requestPayload = {
        session_id: sessionId,
        account_id: currentUser.id,
        ...payload,
      };

      const res = await api.executeTurn(requestPayload);

      // Synchronize frontend state with authoritative backend response
      setSessionId(res.session_id);
      setDialogueState(res.state);
      setPromptText(res.prompt_text);

      if (res.readback_card) {
        setReadbackCard(res.readback_card);
      }
      if (res.liveness_challenge) {
        setLivenessChallenge(res.liveness_challenge);
      }
      if (res.receipt) {
        setReceipt(res.receipt);
        // Refresh balance and transaction list
        await refreshAccount();
        await loadTransactions();
      }
      if (res.handoff_case_id) {
        setHandoffCaseId(res.handoff_case_id);
      }
      if (res.error) {
        setErrorMessage(res.error);
      }

      return res;
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  // 1. Submit voice speech
  function submitSpeechTurn(spokenText) {
    if (!spokenText.trim()) return;
    sendTurnRequest({
      action: dialogueState === 'CAPTURE' ? 'SUBMIT_TRANSCRIPT' : 'CLARIFY',
      transcript: spokenText,
      channel: 'VOICE',
    });
  }

  // 2. Submit typed text
  function handleTypedSubmit(e) {
    e.preventDefault();
    if (!typedInput.trim()) return;

    const text = typedInput.trim();
    setTypedInput('');
    setTranscript(text);

    sendTurnRequest({
      action: dialogueState === 'CAPTURE' ? 'SUBMIT_TRANSCRIPT' : 'CLARIFY',
      transcript: text,
      channel: 'TYPED',
    });
  }

  // 3. Confirm Read-Back Card
  function handleConfirmReadback() {
    if (speechAdapterRef.current) {
      speechAdapterRef.current.stopSpeaking();
    }
    sendTurnRequest({
      action: 'CONFIRM_READBACK',
    });
  }

  // 4. Submit Liveness Response (Voice or Typed)
  function handleLivenessSubmit(channel = 'VOICE', forcedDigits = null) {
    const digits = forcedDigits || livenessChallenge;
    sendTurnRequest({
      action: 'SUBMIT_LIVENESS',
      liveness_response: digits,
      channel: channel,
      audio_metadata: { scenario: 'unavailable' }, // Honest reporting in local dev
    });
  }

  // 5. Submit PIN Verification
  function handlePinSubmit(e) {
    if (e) e.preventDefault();
    if (pinInput.length !== 4) {
      setPinError('Please enter your complete 4-digit PIN.');
      return;
    }
    setPinError(null);
    const submittedPin = pinInput;
    setPinInput(''); // Clear immediately from state for safety

    sendTurnRequest({
      action: 'SUBMIT_PIN',
      pin: submittedPin,
    });
  }

  // 6. Explicit Cancellation
  function handleCancelPayment() {
    if (speechAdapterRef.current) {
      speechAdapterRef.current.stopSpeaking();
      speechAdapterRef.current.abortListening();
    }
    setPinInput('');
    sendTurnRequest({
      action: 'CANCEL',
    });
  }

  // 7. Request Human Agent Handoff
  function handleRequestHuman() {
    if (speechAdapterRef.current) {
      speechAdapterRef.current.stopSpeaking();
      speechAdapterRef.current.abortListening();
    }
    sendTurnRequest({
      action: 'REQUEST_HUMAN',
    });
  }

  // Reset dialogue session
  function handleStartNewSession() {
    setSessionId(null);
    setDialogueState('CAPTURE');
    setPromptText('How can I help you today? State an amount and payee in English or Hinglish.');
    setReadbackCard(null);
    setLivenessChallenge(null);
    setReceipt(null);
    setHandoffCaseId(null);
    setTranscript('');
    setPinInput('');
    setErrorMessage(null);
    setPinError(null);
  }

  // Toggle Microphone Listening
  function handleMicToggle() {
    if (speechState === 'LISTENING') {
      speechAdapterRef.current?.stopListening();
    } else {
      setTranscript('');
      setErrorMessage(null);
      speechAdapterRef.current?.startListening();
    }
  }

  return (
    <div style={{ maxWidth: '680px', margin: '0 auto' }}>
      {/* Account Balance Card */}
      <div className="glass-card" style={{ marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Primary Savings Account
            </div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: '2.25rem', fontWeight: 800, color: '#38BDF8', margin: '0.25rem 0' }}>
              ₹{currentUser?.balance?.toLocaleString('en-IN', { minimumFractionDigits: 2 }) || '0.00'}
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Acc No: •••• {currentUser?.account_number?.slice(-4) || '0000'} | Holder: {currentUser?.holder_name}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setShowTransactions(!showTransactions)}
            style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
          >
            {showTransactions ? 'Hide History' : 'View Ledger'}
          </button>
        </div>

        {/* Transaction History Accordion */}
        {showTransactions && (
          <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
            <h4 style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.75rem', textTransform: 'uppercase' }}>
              Recent Mock Ledger Entries
            </h4>
            {transactions.length === 0 ? (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>No prior transactions found on this account.</p>
            ) : (
              <div style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {transactions.map((tx) => (
                  <div
                    key={tx.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '0.4rem 0.6rem',
                      background: 'var(--bg-secondary)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.8rem',
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{tx.description || 'Voice Payment'}</div>
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                        {new Date(tx.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • Tx ID: {tx.transaction_id.slice(0, 10)}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span style={{ fontWeight: 700, color: tx.entry_type === 'DEBIT' ? '#F87171' : '#34D399' }}>
                        {tx.entry_type === 'DEBIT' ? '-' : '+'}₹{tx.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </span>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Bal: ₹{tx.balance_after.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Main Dialogue Assistant Card */}
      <div className="glass-card-elevated">
        {/* Status Tracker */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: 'var(--radius-full)',
                background: dialogueState === 'RECEIPT' ? 'var(--success)' : 'var(--primary)',
                boxShadow: '0 0 8px var(--primary-glow)',
              }}
            />
            <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
              State: {dialogueState}
            </span>
          </div>
          {sessionId && dialogueState !== 'RECEIPT' && dialogueState !== 'CANCELLED' && dialogueState !== 'FAILED' && (
            <button
              type="button"
              onClick={handleCancelPayment}
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem', color: '#F87171' }}
            >
              Cancel Payment
            </button>
          )}
        </div>

        {/* Assistant Response Bubble */}
        <div
          style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '1.25rem',
            marginBottom: '1.5rem',
          }}
        >
          <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-cyan)', marginBottom: '0.4rem' }}>
            VAANIPAY AGENT
          </div>
          <div style={{ fontSize: '1.05rem', fontWeight: 500, color: 'var(--text-primary)', lineHeight: 1.4 }}>
            {promptText}
          </div>
        </div>

        {/* Dynamic Screen Sub-Views according to DialogueState */}

        {/* 1. READBACK STATE */}
        {dialogueState === 'READBACK' && readbackCard && (
          <div className="readback-card">
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Confirm Payment Details
            </div>
            <div className="readback-amount">₹{readbackCard.amount_digits.toLocaleString('en-IN')}</div>
            <div className="readback-words">{readbackCard.amount_words}</div>
            <div className="readback-payee">
              Beneficiary: <strong>{readbackCard.payee_name}</strong>
            </div>

            <div style={{ display: 'flex', gap: '1rem', marginTop: '1.5rem', justifyContent: 'center' }}>
              <button
                type="button"
                className="btn btn-success"
                onClick={handleConfirmReadback}
                disabled={isSubmitting}
                style={{ flex: 1, maxWidth: '200px' }}
              >
                {isSubmitting ? 'Verifying...' : 'Confirm Details'}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={handleCancelPayment}
                disabled={isSubmitting}
                style={{ flex: 1, maxWidth: '140px' }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* 2. LIVENESS STATE */}
        {dialogueState === 'LIVENESS' && livenessChallenge && (
          <div className="liveness-box">
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              🔒 Server Challenge-Response Verification
            </div>
            <p style={{ fontSize: '0.9rem', color: 'var(--text-primary)', marginTop: '0.5rem' }}>
              Please speak or repeat these verification digits clearly:
            </p>
            <div className="challenge-code">{livenessChallenge}</div>
            <div className="ttl-timer">Challenge expires in: {challengeTtl}s</div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '1.5rem', alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handleLivenessSubmit('VOICE')}
                disabled={isSubmitting || challengeTtl === 0}
                style={{ width: '100%', maxWidth: '320px' }}
              >
                🎙️ Speak Challenge ({livenessChallenge})
              </button>

              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => handleLivenessSubmit('TYPED')}
                disabled={isSubmitting || challengeTtl === 0}
                style={{ width: '100%', maxWidth: '320px', fontSize: '0.8rem' }}
              >
                ⌨️ Submit via Typed Fallback
              </button>

              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', maxWidth: '340px' }}>
                Note: Typed challenge response does not prove live human speech and triggers mandatory PIN step-up.
              </div>
            </div>
          </div>
        )}

        {/* 3. STEP_UP_PIN STATE */}
        {dialogueState === 'STEP_UP_PIN' && (
          <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '1.5rem', textAlign: 'center', margin: '1.5rem 0' }}>
            <div style={{ fontSize: '0.85rem', color: 'var(--warning)', fontWeight: 700, textTransform: 'uppercase' }}>
              🔐 Step-Up PIN Authorization
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.4rem' }}>
              Enter your 4-digit security PIN to authorize this transfer. (Demo PIN: <strong>1234</strong>)
            </p>

            {/* Masked PIN Display */}
            <div className="pin-display">
              {[0, 1, 2, 3].map((idx) => (
                <div key={idx} className={`pin-digit-box ${pinInput.length > idx ? 'filled' : ''}`}>
                  {pinInput.length > idx ? '•' : ''}
                </div>
              ))}
            </div>

            {pinError && (
              <div style={{ color: '#F87171', fontSize: '0.8rem', marginBottom: '1rem' }}>
                {pinError}
              </div>
            )}

            {/* Numeric Keypad Grid */}
            <div className="pin-keypad">
              {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((digit) => (
                <button
                  key={digit}
                  type="button"
                  className="keypad-btn"
                  onClick={() => {
                    if (pinInput.length < 4) setPinInput(pinInput + digit);
                  }}
                >
                  {digit}
                </button>
              ))}
              <button
                type="button"
                className="keypad-btn"
                onClick={() => setPinInput('')}
                style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}
              >
                Clear
              </button>
              <button
                type="button"
                className="keypad-btn"
                onClick={() => {
                  if (pinInput.length < 4) setPinInput(pinInput + '0');
                }}
              >
                0
              </button>
              <button
                type="button"
                className="keypad-btn"
                onClick={() => setPinInput(pinInput.slice(0, -1))}
                style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}
              >
                ⌫
              </button>
            </div>

            <div style={{ marginTop: '1.25rem' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handlePinSubmit()}
                disabled={pinInput.length !== 4 || isSubmitting}
                style={{ width: '100%', maxWidth: '280px' }}
              >
                {isSubmitting ? 'Verifying PIN...' : 'Authorize Payment'}
              </button>
            </div>
          </div>
        )}

        {/* 4. RECEIPT STATE */}
        {dialogueState === 'RECEIPT' && receipt && (
          <div className="receipt-card">
            <div className="receipt-icon">✓</div>
            <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem', marginBottom: '0.5rem', color: 'white' }}>
              Payment Successful
            </h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
              Double-entry ledger transfer has been posted.
            </p>

            <div style={{ textAlign: 'left', marginBottom: '1.5rem' }}>
              <div className="receipt-field">
                <span style={{ color: 'var(--text-muted)' }}>Transaction Reference</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{receipt.transaction_id}</span>
              </div>
              <div className="receipt-field">
                <span style={{ color: 'var(--text-muted)' }}>Amount Debited</span>
                <span style={{ fontWeight: 700, color: '#38BDF8' }}>₹{receipt.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="receipt-field">
                <span style={{ color: 'var(--text-muted)' }}>Beneficiary</span>
                <span style={{ fontWeight: 600 }}>{receipt.payee_name}</span>
              </div>
              <div className="receipt-field">
                <span style={{ color: 'var(--text-muted)' }}>New Account Balance</span>
                <span style={{ fontWeight: 700, color: '#34D399' }}>₹{receipt.sender_balance_after.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="receipt-field">
                <span style={{ color: 'var(--text-muted)' }}>Timestamp</span>
                <span>{new Date(receipt.timestamp).toLocaleString()}</span>
              </div>
            </div>

            <button
              type="button"
              className="btn btn-primary"
              onClick={handleStartNewSession}
              style={{ width: '100%', maxWidth: '240px' }}
            >
              Make Another Payment
            </button>
          </div>
        )}

        {/* 5. HANDOFF ESCALATED STATE */}
        {dialogueState === 'HANDOFF' && (
          <div style={{ background: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: 'var(--radius-lg)', padding: '1.75rem', textAlign: 'center', margin: '1.5rem 0' }}>
            <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>👨‍💼</div>
            <h3 style={{ fontFamily: 'var(--font-display)', color: '#FBBF24', fontSize: '1.35rem', marginBottom: '0.5rem' }}>
              Escalated to Human Banking Specialist
            </h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '1rem' }}>
              Your transaction has been routed to our support queue for manual verification. A specialist will review your request.
            </p>
            {handoffCaseId && (
              <div style={{ background: 'var(--bg-secondary)', padding: '0.5rem 1rem', borderRadius: 'var(--radius-sm)', display: 'inline-block', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
                Case ID: {handoffCaseId}
              </div>
            )}
            <div style={{ marginTop: '1.5rem' }}>
              <button type="button" className="btn btn-secondary" onClick={handleStartNewSession}>
                Start New Session
              </button>
            </div>
          </div>
        )}

        {/* 6. CANCELLED / FAILED STATE */}
        {(dialogueState === 'CANCELLED' || dialogueState === 'FAILED') && (
          <div style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 'var(--radius-lg)', padding: '1.5rem', textAlign: 'center', margin: '1.5rem 0' }}>
            <div style={{ color: '#F87171', fontWeight: 700, fontSize: '1.1rem', marginBottom: '0.5rem' }}>
              {dialogueState === 'CANCELLED' ? 'Payment Cancelled' : 'Transaction Blocked'}
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '1.25rem' }}>
              {dialogueState === 'CANCELLED' ? 'No funds were debited. This session has been closed.' : promptText}
            </p>
            <button type="button" className="btn btn-secondary" onClick={handleStartNewSession}>
              Start Over
            </button>
          </div>
        )}

        {/* Live Transcript / Speech Indicator */}
        {transcript && dialogueState !== 'RECEIPT' && (
          <div style={{ margin: '1rem 0', padding: '0.75rem', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-md)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            <span style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>You said: </span>
            "{transcript}"
          </div>
        )}

        {/* Push-to-Talk Mic Controls (Shown in CAPTURE and CLARIFICATION states) */}
        {(dialogueState === 'CAPTURE' || dialogueState === 'CLARIFY_AMOUNT' || dialogueState === 'CLARIFY_PAYEE') && (
          <div className="mic-btn-container">
            <button
              type="button"
              className={`mic-button ${speechState === 'LISTENING' ? 'listening' : ''} ${isSubmitting ? 'processing' : ''}`}
              onClick={handleMicToggle}
              disabled={isSubmitting}
              aria-label={speechState === 'LISTENING' ? 'Stop listening' : 'Push to talk'}
              id="push-to-talk-btn"
            >
              {speechState === 'LISTENING' ? '⏹️' : '🎙️'}
            </button>
            <div style={{ fontSize: '0.85rem', fontWeight: 600, color: speechState === 'LISTENING' ? '#F87171' : 'var(--text-secondary)' }}>
              {speechState === 'LISTENING' ? 'Listening... Speak now' : 'Push to Talk (English or Hinglish)'}
            </div>

            {/* Typed Fallback Input Form */}
            <form onSubmit={handleTypedSubmit} style={{ width: '100%', marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={typedInput}
                onChange={(e) => setTypedInput(e.target.value)}
                placeholder="Or type here (e.g. 'Ramesh ko 500 bhej do')"
                disabled={isSubmitting}
                style={{
                  flex: 1,
                  padding: '0.7rem 1rem',
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-primary)',
                  fontSize: '0.9rem',
                }}
                id="typed-input-field"
              />
              <button type="submit" className="btn btn-primary" disabled={!typedInput.trim() || isSubmitting}>
                Send
              </button>
            </form>
          </div>
        )}

        {/* Global Error Banner */}
        {errorMessage && (
          <div style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger)', color: '#FCA5A5', padding: '0.75rem 1rem', borderRadius: 'var(--radius-md)', fontSize: '0.85rem', marginTop: '1rem' }}>
            ⚠️ {errorMessage}
          </div>
        )}

        {/* Persistent "Talk to Human" Button */}
        {dialogueState !== 'HANDOFF' && dialogueState !== 'RECEIPT' && (
          <div style={{ marginTop: '1.5rem', textAlign: 'center', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
            <button
              type="button"
              onClick={handleRequestHuman}
              disabled={isSubmitting}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '0.8rem', cursor: 'pointer', textDecoration: 'underline' }}
            >
              Need assistance? Connect with a human specialist
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
