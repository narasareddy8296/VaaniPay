import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { SpeechAdapter } from '../services/speech';
import { parseConfirmationIntent, CONFIRMATION_INTENTS } from '../services/intent';

export function CustomerBanking() {
  const { currentUser, refreshAccount } = useAuth();

  // Banking State
  const [transactions, setTransactions] = useState([]);
  const [showTransactions, setShowTransactions] = useState(false);

  // Contacts State
  const [contacts, setContacts] = useState([]);
  const [showAddContact, setShowAddContact] = useState(false);
  const [newContactName, setNewContactName] = useState('');
  const [newBeneficiaryAccount, setNewBeneficiaryAccount] = useState('');
  const [newPhoneNumber, setNewPhoneNumber] = useState('');
  const [newAliases, setNewAliases] = useState('');
  const [contactError, setContactError] = useState(null);
  const [contactSuccess, setContactSuccess] = useState(null);
  const [isAddingContact, setIsAddingContact] = useState(false);
  const [selectedContactId, setSelectedContactId] = useState(null);

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
  const [voiceGuidance, setVoiceGuidance] = useState(null);

  // Input States
  const [transcript, setTranscript] = useState('');
  const [typedInput, setTypedInput] = useState('');
  const [speechState, setSpeechState] = useState('IDLE'); // IDLE, LISTENING, PROCESSING, ERROR
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pinInput, setPinInput] = useState('');
  const [pinError, setPinError] = useState(null);

  // Handoff Two-Way Messaging State
  const [handoffCase, setHandoffCase] = useState(null);
  const [handoffMessages, setHandoffMessages] = useState([]);
  const [handoffInput, setHandoffInput] = useState('');
  const [isSendingHandoffMsg, setIsSendingHandoffMsg] = useState(false);
  const [handoffMsgError, setHandoffMsgError] = useState(null);
  const handoffMessagesEndRef = useRef(null);
  const handoffSpeechAdapterRef = useRef(null);
  const [isListeningHandoffSpeech, setIsListeningHandoffSpeech] = useState(false);

  // Speech Adapter Instance & State Refs
  const speechAdapterRef = useRef(null);
  const ttlTimerRef = useRef(null);
  const dialogueStateRef = useRef(dialogueState);
  dialogueStateRef.current = dialogueState;
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const livenessChallengeRef = useRef(livenessChallenge);
  livenessChallengeRef.current = livenessChallenge;
  const [sessionChannel, setSessionChannel] = useState('VOICE');
  const sessionChannelRef = useRef('VOICE');
  sessionChannelRef.current = sessionChannel;

  useEffect(() => {
    loadTransactions();
    loadContacts();

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

  // Restore active handoff case on mount or customer change
  useEffect(() => {
    if (!currentUser) return;
    api.getActiveHandoffCase()
      .then((activeCase) => {
        if (activeCase?.id) {
          setHandoffCase(activeCase);
          setHandoffCaseId(activeCase.id);
          setSessionId(activeCase.session_id);
          sessionIdRef.current = activeCase.session_id;
          setDialogueState('HANDOFF');
          dialogueStateRef.current = 'HANDOFF';
          setHandoffMessages(activeCase.messages || []);
          if (activeCase.parsed_context?.note) {
            setPromptText(activeCase.parsed_context.note);
          }
        }
      })
      .catch(() => {});
  }, [currentUser?.id]);

  // Polling for handoff case messages and status updates
  useEffect(() => {
    if (dialogueState !== 'HANDOFF' || !handoffCaseId) return;

    const fetchCaseAndMessages = () => {
      api.getHandoffCase(handoffCaseId)
        .then((c) => {
          setHandoffCase(c);
          if (c.status === 'CANCELLED' && dialogueStateRef.current !== 'CANCELLED') {
            setDialogueState('CANCELLED');
            dialogueStateRef.current = 'CANCELLED';
          }
        })
        .catch(() => {});

      api.getHandoffMessages(handoffCaseId)
        .then((msgs) => setHandoffMessages(msgs))
        .catch(() => {});
    };

    fetchCaseAndMessages();
    const interval = setInterval(fetchCaseAndMessages, 2500);
    return () => clearInterval(interval);
  }, [dialogueState, handoffCaseId]);

  useEffect(() => {
    if (dialogueState === 'HANDOFF') {
      handoffMessagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [handoffMessages, dialogueState]);

  async function loadTransactions() {
    if (!currentUser) return;
    try {
      const data = await api.getTransactions(currentUser.id);
      setTransactions(data || []);
    } catch (err) {
      console.warn('Could not load transactions:', err);
    }
  }

  async function loadContacts() {
    if (!currentUser) return;
    try {
      const data = await api.getContacts(currentUser.id);
      setContacts(data || []);
    } catch (err) {
      console.warn('Could not load contacts:', err);
    }
  }

  async function handleAddContact(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (isAddingContact) return;
    setContactError(null);
    setContactSuccess(null);

    const name = newContactName.trim();
    const beneficiaryAcc = newBeneficiaryAccount.trim();

    if (name.length < 2) {
      setContactError('Payee name must be at least 2 characters long.');
      return;
    }
    if (!beneficiaryAcc) {
      setContactError('Mock account identifier is required.');
      return;
    }

    setIsAddingContact(true);
    try {
      const created = await api.createContact(currentUser.id, {
        contact_name: name,
        beneficiary_account_id: beneficiaryAcc,
        phone_number: newPhoneNumber.trim() || null,
        aliases: newAliases.trim() || null,
        is_frequent: false,
      });

      setContactSuccess(`Added "${created.contact_name}" to saved payees! Step-up PIN will be required on first payment.`);
      setNewContactName('');
      setNewBeneficiaryAccount('');
      setNewPhoneNumber('');
      setNewAliases('');
      await loadContacts();
    } catch (err) {
      setContactError(err.message || 'Failed to add contact.');
    } finally {
      setIsAddingContact(false);
    }
  }

  function handleSelectContact(contact) {
    setSelectedContactId(contact.id);
    if (dialogueState === 'CLARIFY_PAYEE') {
      setTypedInput(contact.contact_name);
      setPromptText(`Selected ${contact.contact_name}. Click Send or press Enter to confirm this recipient.`);
    } else {
      setTypedInput(`Send 500 to ${contact.contact_name}`);
      setPromptText(`Ready to pay ${contact.contact_name}. State an amount or say "Send 500 to ${contact.contact_name}".`);
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

  // =========================================================================
  // STATE MACHINE AUDIO & LISTENING COORDINATION
  // =========================================================================

  async function coordinateDialogueTurnAudio(res) {
    if (!speechAdapterRef.current) return;
    const state = res.state;

    if (state === 'READBACK' && res.readback_card) {
      const speechText = `Please confirm: send ${res.readback_card.amount_words} to ${res.readback_card.payee_name}. Say 'Confirm' to proceed, or say 'Cancel'.`;
      setVoiceGuidance('Speaking payment summary...');
      speechAdapterRef.current.speak(speechText, async () => {
        setVoiceGuidance("🎙️ Listening: Say 'Confirm' to proceed, or click 'Confirm Details' below");
        try {
          const ok = await speechAdapterRef.current?.startListening();
          if (!ok) {
            setVoiceGuidance("Say 'Confirm' or click 'Confirm Details' below.");
          }
        } catch (_) {
          setVoiceGuidance("Say 'Confirm' or click 'Confirm Details' below.");
        }
      });
      return;
    }

    if (state === 'CLARIFY_AMOUNT' || state === 'CLARIFY_PAYEE') {
      const speechText = res.prompt_text || 'Please provide clarification.';
      setVoiceGuidance('Speaking clarification question...');
      speechAdapterRef.current.speak(speechText, async () => {
        setVoiceGuidance('🎙️ Listening for your clarification...');
        try {
          const ok = await speechAdapterRef.current?.startListening();
          if (!ok) {
            setVoiceGuidance('Tap microphone to speak clarification, or use typed input.');
          }
        } catch (_) {
          setVoiceGuidance("Browser requires user click to activate mic. Click 'Speak Now' or use typed input.");
        }
      });
      return;
    }

    if (state === 'LIVENESS' && res.liveness_challenge) {
      const challengeSpoken = res.liveness_challenge.split('').join(' ');
      const speechText = `For voice security, please repeat these verification digits: ${challengeSpoken}.`;
      setVoiceGuidance('Speaking verification challenge...');
      speechAdapterRef.current.speak(speechText, async () => {
        setVoiceGuidance(`🎙️ Listening: Repeat digits "${res.liveness_challenge}"`);
        try {
          const ok = await speechAdapterRef.current?.startListening();
          if (!ok) {
            setVoiceGuidance('Tap microphone to speak challenge digits, or use typed fallback.');
          }
        } catch (_) {
          setVoiceGuidance("Browser requires user click to activate mic. Click 'Speak Challenge' or use typed fallback.");
        }
      });
      return;
    }

    if (state === 'STEP_UP_PIN') {
      speechAdapterRef.current.abortListening();
      const speechText = 'Security verification requires your 4-digit PIN. Please enter your PIN on the keypad.';
      setVoiceGuidance('🔒 Security PIN required. Enter your 4-digit PIN on the manual keypad below.');
      speechAdapterRef.current.speak(speechText);
      return;
    }

    if (state === 'RECEIPT') {
      speechAdapterRef.current.abortListening();
      const amountStr = res.receipt ? `₹${res.receipt.amount}` : '';
      const payeeStr = res.receipt ? res.receipt.payee_name : '';
      const speechText = `Payment of ${amountStr} to ${payeeStr} was successful.`;
      setVoiceGuidance('✅ Payment completed successfully.');
      speechAdapterRef.current.speak(speechText);
      return;
    }

    if (state === 'HANDOFF') {
      speechAdapterRef.current.abortListening();
      const speechText = 'Payment has been paused. A human representative will assist you.';
      setVoiceGuidance('👥 Transferred to human support queue.');
      speechAdapterRef.current.speak(speechText);
      return;
    }

    if (state === 'CANCELLED') {
      speechAdapterRef.current.abortListening();
      const speechText = 'Payment has been cancelled.';
      setVoiceGuidance('🛑 Payment cancelled. You can start a new request anytime.');
      speechAdapterRef.current.speak(speechText);
      return;
    }

    if (state === 'FAILED') {
      speechAdapterRef.current.abortListening();
      const speechText = res.prompt_text || 'Payment failed.';
      setVoiceGuidance('⚠️ Payment could not be processed.');
      speechAdapterRef.current.speak(speechText);
      return;
    }
  }

  // =========================================================================
  // STATE MACHINE TURN DISPATCHERS
  // =========================================================================

  async function sendTurnRequest(payload) {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const requestPayload = {
        session_id: sessionIdRef.current,
        account_id: currentUser.id,
        ...payload,
      };

      const res = await api.executeTurn(requestPayload);

      // Synchronize frontend state with authoritative backend response
      setSessionId(res.session_id);
      sessionIdRef.current = res.session_id;
      setDialogueState(res.state);
      dialogueStateRef.current = res.state;
      setPromptText(res.prompt_text);

      if (res.readback_card) {
        setReadbackCard(res.readback_card);
      }
      if (res.liveness_challenge) {
        setLivenessChallenge(res.liveness_challenge);
        livenessChallengeRef.current = res.liveness_challenge;
      }
      if (res.state === 'RECEIPT' || res.receipt) {
        if (res.receipt) {
          setReceipt(res.receipt);
        }
        await refreshAccount();
        await loadTransactions();
      }
      if (res.handoff_case_id) {
        setHandoffCaseId(res.handoff_case_id);
        api.getHandoffCase(res.handoff_case_id)
          .then((c) => {
            setHandoffCase(c);
            setHandoffMessages(c.messages || []);
          })
          .catch(() => {});
      }
      if (res.error) {
        setErrorMessage(res.error);
      }

      // Coordinate audio read-back and fresh listening turn
      await coordinateDialogueTurnAudio(res);

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
    setSessionChannel('VOICE');
    sessionChannelRef.current = 'VOICE';
    const currentState = dialogueStateRef.current;

    if (currentState === 'CAPTURE') {
      sendTurnRequest({
        action: 'SUBMIT_TRANSCRIPT',
        transcript: spokenText,
        channel: 'VOICE',
      });
      return;
    }

    if (currentState === 'CLARIFY_AMOUNT' || currentState === 'CLARIFY_PAYEE') {
      const intentEval = parseConfirmationIntent(spokenText);
      if (intentEval.intent === CONFIRMATION_INTENTS.CANCEL) {
        sendTurnRequest({
          action: 'CANCEL',
          transcript: spokenText,
          channel: 'VOICE',
        });
      } else {
        sendTurnRequest({
          action: 'CLARIFY',
          transcript: spokenText,
          channel: 'VOICE',
        });
      }
      return;
    }

    if (currentState === 'READBACK') {
      const intentEval = parseConfirmationIntent(spokenText);
      if (intentEval.intent === CONFIRMATION_INTENTS.CONFIRM) {
        sendTurnRequest({
          action: 'CONFIRM_READBACK',
          transcript: spokenText,
          channel: 'VOICE',
        });
      } else if (intentEval.intent === CONFIRMATION_INTENTS.CANCEL) {
        sendTurnRequest({
          action: 'CANCEL',
          transcript: spokenText,
          channel: 'VOICE',
        });
      } else if (intentEval.intent === CONFIRMATION_INTENTS.AMBIGUOUS) {
        const ambiguityPrompt = "I couldn't tell if you wanted to confirm or cancel. Please clearly say 'Confirm' or 'Cancel'.";
        setPromptText(ambiguityPrompt);
        setVoiceGuidance("Awaiting clear confirmation: say 'Confirm' or 'Cancel'");
        speechAdapterRef.current?.speak(ambiguityPrompt, async () => {
          await speechAdapterRef.current?.startListening();
        });
      } else if (intentEval.intent === CONFIRMATION_INTENTS.PAYMENT_REQUEST) {
        const paymentNotice = 'A payment request is already pending. Please say "Confirm" to proceed, or "Cancel" to stop.';
        setPromptText(paymentNotice);
        setVoiceGuidance('Say "Confirm" to proceed, or "Cancel" to stop');
        speechAdapterRef.current?.speak(paymentNotice, async () => {
          await speechAdapterRef.current?.startListening();
        });
      } else {
        const retryPrompt = 'I did not hear a clear confirmation. Please say "Confirm" to proceed, or "Cancel" to stop.';
        setPromptText(retryPrompt);
        setVoiceGuidance('Say "Confirm" or "Cancel"');
        speechAdapterRef.current?.speak(retryPrompt, async () => {
          await speechAdapterRef.current?.startListening();
        });
      }
      return;
    }

    if (currentState === 'LIVENESS') {
      const intentEval = parseConfirmationIntent(spokenText);
      if (intentEval.intent === CONFIRMATION_INTENTS.CANCEL) {
        sendTurnRequest({
          action: 'CANCEL',
          transcript: spokenText,
          channel: 'VOICE',
        });
      } else {
        sendTurnRequest({
          action: 'SUBMIT_LIVENESS',
          liveness_response: spokenText,
          channel: 'VOICE',
          audio_metadata: { scenario: 'browser_stt' },
        });
      }
      return;
    }

    if (currentState === 'STEP_UP_PIN') {
      // Invariant: PIN is never collected or recognized via voice
      speechAdapterRef.current?.abortListening();
      const pinNotice = 'Please enter your 4-digit PIN using the secure keypad below.';
      setPromptText(pinNotice);
      speechAdapterRef.current?.speak(pinNotice);
      return;
    }
  }

  // 2. Submit typed text
  function handleTypedSubmit(e) {
    e.preventDefault();
    if (!typedInput.trim()) return;

    setSessionChannel('TYPED');
    sessionChannelRef.current = 'TYPED';
    const text = typedInput.trim();
    setTypedInput('');
    setTranscript(text);
    const currentState = dialogueStateRef.current;

    if (currentState === 'CAPTURE') {
      sendTurnRequest({
        action: 'SUBMIT_TRANSCRIPT',
        transcript: text,
        channel: 'TYPED',
      });
    } else if (currentState === 'CLARIFY_AMOUNT' || currentState === 'CLARIFY_PAYEE') {
      const intentEval = parseConfirmationIntent(text);
      if (intentEval.intent === CONFIRMATION_INTENTS.CANCEL) {
        sendTurnRequest({
          action: 'CANCEL',
          transcript: text,
          channel: 'TYPED',
        });
      } else {
        sendTurnRequest({
          action: 'CLARIFY',
          transcript: text,
          channel: 'TYPED',
        });
      }
    } else if (currentState === 'READBACK') {
      const intentEval = parseConfirmationIntent(text);
      if (intentEval.intent === CONFIRMATION_INTENTS.CANCEL) {
        sendTurnRequest({
          action: 'CANCEL',
          transcript: text,
          channel: 'TYPED',
        });
      } else {
        sendTurnRequest({
          action: 'CONFIRM_READBACK',
          transcript: text,
          channel: 'TYPED',
        });
      }
    } else if (currentState === 'LIVENESS') {
      sendTurnRequest({
        action: 'SUBMIT_LIVENESS',
        liveness_response: text,
        channel: 'TYPED',
      });
    }
  }

  // 3. Confirm Read-Back Card via button
  function handleConfirmReadback() {
    if (speechAdapterRef.current) {
      speechAdapterRef.current.stopSpeaking();
    }
    sendTurnRequest({
      action: 'CONFIRM_READBACK',
      channel: sessionChannelRef.current || 'VOICE',
    });
  }

  // 4. Submit Liveness via button
  function handleLivenessSubmit(channel = 'VOICE', forcedDigits = null) {
    if (channel === 'VOICE') {
      speechAdapterRef.current?.startListening();
      return;
    }
    const digits = forcedDigits || livenessChallengeRef.current;
    sendTurnRequest({
      action: 'SUBMIT_LIVENESS',
      liveness_response: digits,
      channel: sessionChannelRef.current || 'VOICE',
      audio_metadata: { scenario: sessionChannelRef.current === 'VOICE' ? 'liveness_verified' : 'typed_fallback' },
    });
  }

  // 5. Submit PIN Verification
  function handlePinSubmit() {
    if (!pinInput || pinInput.length !== 4) {
      setPinError('Please enter your complete 4-digit PIN.');
      return;
    }
    setPinError(null);
    const submittedPin = pinInput;
    setPinInput(''); // Clear immediately from state for safety

    sendTurnRequest({
      action: 'SUBMIT_PIN',
      pin: submittedPin,
      channel: 'TYPED',
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
      channel: 'TYPED',
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
      channel: 'TYPED',
    });
  }

  // Reset dialogue session
  function handleStartNewSession() {
    if (speechAdapterRef.current) {
      speechAdapterRef.current.stopSpeaking();
      speechAdapterRef.current.abortListening();
    }
    setSessionId(null);
    sessionIdRef.current = null;
    setDialogueState('CAPTURE');
    dialogueStateRef.current = 'CAPTURE';
    setPromptText('How can I help you today? State an amount and payee in English or Hinglish.');
    setReadbackCard(null);
    setLivenessChallenge(null);
    livenessChallengeRef.current = null;
    setReceipt(null);
    setHandoffCaseId(null);
    setHandoffCase(null);
    setHandoffMessages([]);
    setHandoffInput('');
    setHandoffMsgError(null);
    setIsListeningHandoffSpeech(false);
    setTranscript('');
    setPinInput('');
    setErrorMessage(null);
    setPinError(null);
    setVoiceGuidance(null);
  }

  // Two-Way Handoff Messaging Handlers
  async function handleSendHandoffMessage(e) {
    if (e) e.preventDefault();
    if (!handoffCaseId || !handoffInput.trim() || isSendingHandoffMsg) return;

    const textToSend = handoffInput.trim();
    setIsSendingHandoffMsg(true);
    setHandoffMsgError(null);

    try {
      const sent = await api.sendHandoffMessage(handoffCaseId, textToSend);
      setHandoffMessages((prev) => [...prev, sent]);
      setHandoffInput('');
    } catch (err) {
      setHandoffMsgError(err.message);
    } finally {
      setIsSendingHandoffMsg(false);
    }
  }

  function handleToggleHandoffSpeech() {
    if (isListeningHandoffSpeech) {
      handoffSpeechAdapterRef.current?.stopListening();
      setIsListeningHandoffSpeech(false);
    } else {
      setHandoffMsgError(null);
      if (!handoffSpeechAdapterRef.current) {
        handoffSpeechAdapterRef.current = new SpeechAdapter({
          onTranscript: (spokenText, isFinal) => {
            setHandoffInput(spokenText);
            if (isFinal) {
              setIsListeningHandoffSpeech(false);
            }
          },
          onStateChange: (state) => {
            setIsListeningHandoffSpeech(state === 'LISTENING');
          },
          onError: (err) => {
            setHandoffMsgError(err.message || 'Speech recognition failed');
            setIsListeningHandoffSpeech(false);
          },
        });
      }
      handoffSpeechAdapterRef.current.startListening();
    }
  }

  async function handleCancelHandoffCase() {
    if (!handoffCaseId) {
      handleCancelPayment();
      return;
    }
    try {
      const res = await api.cancelHandoffCase(handoffCaseId);
      setHandoffCase(res);
      setDialogueState('CANCELLED');
      dialogueStateRef.current = 'CANCELLED';
      setPromptText('Payment request has been cancelled.');
    } catch (err) {
      setErrorMessage(err.message);
    }
  }

  // Toggle Microphone Listening
  async function handleMicToggle() {
    if (speechState === 'LISTENING') {
      speechAdapterRef.current?.stopListening();
    } else {
      setTranscript('');
      setErrorMessage(null);
      await speechAdapterRef.current?.startListening();
    }
  }

  return (
    <div className="customer-banking-container">
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

      {/* Saved Payees & Contacts Card */}
      <div className="glass-card" style={{ marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '1.1rem' }}>👥</span>
            <div>
              <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                Saved Payees & Contacts
              </h3>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {contacts.length} registered recipient{contacts.length === 1 ? '' : 's'}
              </div>
            </div>
          </div>
          <button
            id="btn-toggle-add-contact"
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setShowAddContact(!showAddContact);
              setContactError(null);
              setContactSuccess(null);
            }}
            style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}
          >
            {showAddContact ? 'Close Form' : '+ Add Payee'}
          </button>
        </div>

        {/* Add Payee Form Drawer */}
        {showAddContact && (
          <form
            id="form-add-contact"
            onSubmit={handleAddContact}
            style={{
              marginTop: '1rem',
              padding: '1rem',
              background: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
              Add New Beneficiary / Contact
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
              Enter payee name and valid mock account ID (e.g. acc_ramesh, ACC_RAMESH_002).
              Adding a contact does not authorize a payment. Voice transfers to new payees mandate step-up PIN verification.
            </div>

            {contactError && (
              <div className="alert alert-error" style={{ fontSize: '0.8rem', padding: '0.5rem', marginBottom: '0.75rem' }}>
                {contactError}
              </div>
            )}
            {contactSuccess && (
              <div className="alert alert-success" style={{ fontSize: '0.8rem', padding: '0.5rem', marginBottom: '0.75rem' }}>
                {contactSuccess}
              </div>
            )}

            <div className="contact-form-row">
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                  Payee Full Name *
                </label>
                <input
                  id="input-contact-name"
                  type="text"
                  className="input-field"
                  placeholder="e.g. Vikram Verma"
                  value={newContactName}
                  onChange={(e) => setNewContactName(e.target.value)}
                  required
                  style={{ width: '100%', fontSize: '0.85rem' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                  Mock Account Identifier *
                </label>
                <input
                  id="input-contact-account"
                  type="text"
                  className="input-field"
                  placeholder="e.g. acc_ramesh"
                  value={newBeneficiaryAccount}
                  onChange={(e) => setNewBeneficiaryAccount(e.target.value)}
                  required
                  style={{ width: '100%', fontSize: '0.85rem' }}
                />
              </div>
            </div>

            <div className="contact-form-row">
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                  Phone Number (Optional)
                </label>
                <input
                  id="input-contact-phone"
                  type="tel"
                  className="input-field"
                  placeholder="+919876543211"
                  value={newPhoneNumber}
                  onChange={(e) => setNewPhoneNumber(e.target.value)}
                  style={{ width: '100%', fontSize: '0.85rem' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                  Voice Aliases (Comma-separated)
                </label>
                <input
                  id="input-contact-aliases"
                  type="text"
                  className="input-field"
                  placeholder="e.g. Vikram, Vicky, Bhai"
                  value={newAliases}
                  onChange={(e) => setNewAliases(e.target.value)}
                  style={{ width: '100%', fontSize: '0.85rem' }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowAddContact(false)}
                style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
              >
                Cancel
              </button>
              <button
                id="btn-submit-contact"
                type="submit"
                className="btn btn-primary"
                disabled={isAddingContact}
                style={{ fontSize: '0.8rem', padding: '0.4rem 1rem' }}
              >
                {isAddingContact ? 'Saving...' : 'Save Payee'}
              </button>
            </div>
          </form>
        )}

        {/* Contact list & selectable recipients */}
        <div style={{ marginTop: '0.75rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
          {contacts.length === 0 ? (
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: '0.25rem 0' }}>
              No contacts saved yet. Click "+ Add Payee" to add your first recipient.
            </p>
          ) : (
            contacts.map((contact) => (
              <div
                key={contact.id}
                id={`contact-card-${contact.id}`}
                onClick={() => handleSelectContact(contact)}
                style={{
                  padding: '0.5rem 0.75rem',
                  background: selectedContactId === contact.id ? 'rgba(56, 189, 248, 0.15)' : 'var(--bg-secondary)',
                  border: selectedContactId === contact.id ? '1px solid #38BDF8' : '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.2rem',
                  transition: 'all 0.15s ease',
                  minWidth: '150px',
                  flex: '1 1 calc(50% - 0.5rem)',
                }}
                title={`Click to select ${contact.contact_name} for payment`}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                    {contact.contact_name}
                  </span>
                  <span
                    style={{
                      fontSize: '0.65rem',
                      padding: '0.1rem 0.4rem',
                      borderRadius: '4px',
                      fontWeight: 600,
                      background: contact.is_frequent ? 'rgba(52, 211, 153, 0.2)' : 'rgba(251, 191, 36, 0.2)',
                      color: contact.is_frequent ? '#34D399' : '#FBBF24',
                    }}
                  >
                    {contact.is_frequent ? 'Frequent' : 'New Payee'}
                  </span>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  Acc: {contact.beneficiary_account_id ? `•••• ${contact.beneficiary_account_id.slice(-6)}` : 'No Bank Acc'}
                  {contact.phone_number ? ` • ${contact.phone_number}` : ''}
                </div>
                {contact.aliases && (
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                    Aliases: {contact.aliases}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
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

        {/* Live Assistant Voice Guidance Badge */}
        {voiceGuidance && (
          <div
            style={{
              background: 'rgba(56, 189, 248, 0.08)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              color: '#38BDF8',
              padding: '0.6rem 0.9rem',
              borderRadius: 'var(--radius-md)',
              fontSize: '0.85rem',
              marginBottom: '1.25rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            <span>ℹ️</span>
            <span>{voiceGuidance}</span>
          </div>
        )}

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

            <div className="dialogue-action-buttons">
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
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.4rem', marginBottom: '1.25rem' }}>
              Enter your 4-digit security PIN on the manual keypad below to authorize this transfer. (Demo PIN: <strong>1234</strong>)
            </p>

            {pinError && (
              <div
                style={{
                  background: 'var(--danger-bg)',
                  border: '1px solid var(--danger)',
                  color: '#FCA5A5',
                  padding: '0.65rem 0.9rem',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.8rem',
                  marginBottom: '1.25rem',
                  textAlign: 'left',
                }}
              >
                ⚠️ {pinError}
              </div>
            )}

            {/* Masked PIN Display */}
            <div className="pin-display">
              {[0, 1, 2, 3].map((idx) => (
                <div key={idx} className={`pin-digit-box ${pinInput.length > idx ? 'filled' : ''}`}>
                  {pinInput.length > idx ? '•' : ''}
                </div>
              ))}
            </div>

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

            <div className="dialogue-action-buttons" style={{ marginTop: '1.25rem' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleCancelPayment}
                disabled={isSubmitting}
                style={{ flex: 1, maxWidth: '140px' }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handlePinSubmit}
                disabled={pinInput.length !== 4 || isSubmitting}
                style={{ flex: 1, maxWidth: '200px' }}
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

        {/* 5. HANDOFF TWO-WAY CONVERSATION SCREEN */}
        {dialogueState === 'HANDOFF' && (
          <div
            className="glass-card-elevated"
            style={{
              padding: '1.75rem',
              margin: '1.5rem 0',
              border: '1px solid rgba(245, 158, 11, 0.35)',
              background: 'linear-gradient(180deg, rgba(30, 41, 59, 0.85) 0%, rgba(15, 23, 42, 0.95) 100%)',
            }}
          >
            {/* Header / Case Status */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                <span style={{ fontSize: '1.6rem' }}>👨‍💼</span>
                <div>
                  <h3 style={{ fontFamily: 'var(--font-display)', color: 'var(--text-primary)', fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>
                    Banking Specialist Support
                  </h3>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    Case ID: {handoffCaseId || 'Pending'}
                  </div>
                </div>
              </div>

              {/* Status Badge */}
              <div
                style={{
                  padding: '0.35rem 0.85rem',
                  borderRadius: 'var(--radius-full)',
                  fontSize: '0.8rem',
                  fontWeight: 700,
                  background:
                    handoffCase?.status === 'AGENT_CONNECTED'
                      ? 'rgba(56, 189, 248, 0.2)'
                      : ['APPROVED', 'RESOLVED'].includes(handoffCase?.status)
                      ? 'rgba(16, 185, 129, 0.2)'
                      : handoffCase?.status === 'CANCELLED'
                      ? 'rgba(239, 68, 68, 0.2)'
                      : 'rgba(245, 158, 11, 0.2)',
                  color:
                    handoffCase?.status === 'AGENT_CONNECTED'
                      ? '#38BDF8'
                      : ['APPROVED', 'RESOLVED'].includes(handoffCase?.status)
                      ? '#34D399'
                      : handoffCase?.status === 'CANCELLED'
                      ? '#F87171'
                      : '#FBBF24',
                  border: '1px solid currentColor',
                }}
              >
                ● {handoffCase?.status_display || (handoffCase?.status === 'AGENT_CONNECTED' ? 'Agent Connected' : 'Waiting for Agent')}
              </div>
            </div>

            {/* Payment Context Card */}
            <div
              style={{
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)',
                padding: '0.9rem 1.1rem',
                marginBottom: '1.25rem',
                border: '1px solid var(--border-subtle)',
                fontSize: '0.85rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>Reason for Review:</span>
                <span style={{ fontWeight: 600, color: '#FBBF24' }}>
                  {handoffCase?.escalation_reason || 'Manual Verification'}
                </span>
              </div>
              {handoffCase?.parsed_context?.pending_amount && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Intended Amount:</span>
                  <span style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>
                    ₹{handoffCase.parsed_context.pending_amount}
                  </span>
                </div>
              )}
              {handoffCase?.parsed_context?.pending_payee_name && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Intended Recipient:</span>
                  <span style={{ fontWeight: 600 }}>{handoffCase.parsed_context.pending_payee_name}</span>
                </div>
              )}
              {handoffCase?.parsed_context?.raw_transcript && (
                <div style={{ marginTop: '0.4rem', paddingTop: '0.4rem', borderTop: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Original Speech: </span>
                  <em>"{handoffCase.parsed_context.raw_transcript}"</em>
                </div>
              )}
              {promptText && (
                <div style={{ marginTop: '0.4rem', color: '#CBD5E1', fontSize: '0.82rem' }}>
                  {promptText}
                </div>
              )}
            </div>

            {/* Conversation Messages Container */}
            <div
              style={{
                background: 'var(--bg-tertiary)',
                borderRadius: 'var(--radius-md)',
                padding: '1rem',
                minHeight: '180px',
                maxHeight: '280px',
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.75rem',
                marginBottom: '1rem',
                border: '1px solid var(--border-subtle)',
              }}
            >
              {handoffMessages.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem', margin: 'auto' }}>
                  <div style={{ fontSize: '1.5rem', marginBottom: '0.4rem' }}>⏳</div>
                  Connecting you with a human banking specialist...
                  <div style={{ fontSize: '0.75rem', marginTop: '0.25rem' }}>
                    You can type a message below or push to talk to leave a question for the agent.
                  </div>
                </div>
              ) : (
                handoffMessages.map((m) => {
                  const isCustomer = m.sender_role === 'customer';
                  return (
                    <div
                      key={m.id}
                      style={{
                        alignSelf: isCustomer ? 'flex-end' : 'flex-start',
                        maxWidth: '82%',
                        background: isCustomer
                          ? 'linear-gradient(135deg, rgba(99, 102, 241, 0.3) 0%, rgba(139, 92, 246, 0.3) 100%)'
                          : 'rgba(30, 41, 59, 0.9)',
                        border: isCustomer
                          ? '1px solid rgba(99, 102, 241, 0.5)'
                          : '1px solid rgba(56, 189, 248, 0.3)',
                        borderRadius: 'var(--radius-md)',
                        padding: '0.65rem 0.9rem',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', marginBottom: '0.2rem' }}>
                        <span style={{ fontSize: '0.75rem', fontWeight: 700, color: isCustomer ? '#A5B4FC' : '#38BDF8' }}>
                          {isCustomer ? '👤 You' : `👨‍💼 Support Agent (${m.sender_name})`}
                        </span>
                        <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                          {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)', wordBreak: 'break-word', lineHeight: 1.45 }}>
                        {m.message_text}
                      </div>
                    </div>
                  );
                })
              )}
              <div ref={handoffMessagesEndRef} />
            </div>

            {/* Message Input Controls */}
            {!['APPROVED', 'REJECTED', 'RESOLVED', 'CANCELLED'].includes(handoffCase?.status) ? (
              <div>
                <form onSubmit={handleSendHandoffMessage} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
                  <input
                    type="text"
                    value={handoffInput}
                    onChange={(e) => setHandoffInput(e.target.value)}
                    placeholder="Type a message or question to the specialist..."
                    disabled={isSendingHandoffMsg}
                    style={{
                      flex: 1,
                      padding: '0.7rem 0.9rem',
                      background: 'var(--bg-secondary)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontSize: '0.9rem',
                    }}
                  />
                  <button
                    type="button"
                    onClick={handleToggleHandoffSpeech}
                    className={`btn ${isListeningHandoffSpeech ? 'btn-danger' : 'btn-secondary'}`}
                    style={{ fontSize: '0.85rem', padding: '0.7rem 0.9rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}
                    title={isListeningHandoffSpeech ? 'Stop listening' : 'Speak your message'}
                  >
                    <span>🎤</span>
                    <span>{isListeningHandoffSpeech ? 'Listening...' : 'Speak'}</span>
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={isSendingHandoffMsg || !handoffInput.trim()}
                    style={{ fontSize: '0.85rem', padding: '0.7rem 1.25rem' }}
                  >
                    {isSendingHandoffMsg ? 'Sending...' : 'Send'}
                  </button>
                </form>

                {handoffMsgError && (
                  <div style={{ color: '#F87171', fontSize: '0.8rem', marginBottom: '0.75rem' }}>
                    ⚠️ {handoffMsgError}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ background: 'var(--bg-secondary)', padding: '0.75rem', borderRadius: 'var(--radius-md)', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '1rem' }}>
                🔒 This case is {handoffCase?.status_display || handoffCase?.status}. Conversation is closed.
              </div>
            )}

            {/* Actions: Cancel or Start New Session */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)' }}>
              <button
                type="button"
                className="btn btn-danger"
                onClick={handleCancelHandoffCase}
                style={{ fontSize: '0.85rem', padding: '0.5rem 1rem' }}
              >
                Cancel Payment & Case
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleStartNewSession}
                style={{ fontSize: '0.85rem', padding: '0.5rem 1rem' }}
              >
                Return to Banking
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

        {/* Push-to-Talk Mic Controls & Typed Fallback (Active during voice conversation states) */}
        {['CAPTURE', 'CLARIFY_AMOUNT', 'CLARIFY_PAYEE', 'READBACK', 'LIVENESS'].includes(dialogueState) && (
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
              {speechState === 'LISTENING'
                ? (dialogueState === 'READBACK'
                    ? 'Listening... Say "Confirm" or "Cancel"'
                    : dialogueState === 'LIVENESS'
                    ? `Listening... Repeat "${livenessChallenge}"`
                    : 'Listening... Speak now')
                : (dialogueState === 'READBACK'
                    ? 'Push to Confirm / Cancel by Voice'
                    : dialogueState === 'LIVENESS'
                    ? 'Push to Speak Challenge Digits'
                    : dialogueState === 'CLARIFY_AMOUNT' || dialogueState === 'CLARIFY_PAYEE'
                    ? 'Push to Speak Clarification'
                    : 'Push to Talk (English or Hinglish)')}
            </div>

            {/* Typed Fallback Input Form */}
            <form onSubmit={handleTypedSubmit} style={{ width: '100%', marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={typedInput}
                onChange={(e) => setTypedInput(e.target.value)}
                placeholder={
                  dialogueState === 'READBACK'
                    ? "Or type 'confirm' or 'cancel'"
                    : dialogueState === 'LIVENESS'
                    ? `Or type digits (e.g. '${livenessChallenge}')`
                    : dialogueState === 'CLARIFY_AMOUNT'
                    ? "Or type amount (e.g. '500 rupees')"
                    : dialogueState === 'CLARIFY_PAYEE'
                    ? "Or type payee name"
                    : "Or type here (e.g. 'Ramesh ko 500 bhej do')"
                }
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
          <div
            style={{
              background: 'var(--danger-bg)',
              border: '1px solid var(--danger)',
              color: '#FCA5A5',
              padding: '0.75rem 1rem',
              borderRadius: 'var(--radius-md)',
              fontSize: '0.85rem',
              marginTop: '1rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '0.75rem',
            }}
          >
            <div>⚠️ {errorMessage}</div>
            <button
              type="button"
              onClick={() => {
                setErrorMessage(null);
                document.getElementById('typed-input-field')?.focus();
              }}
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem', whiteSpace: 'nowrap' }}
            >
              Use Typed Input
            </button>
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
