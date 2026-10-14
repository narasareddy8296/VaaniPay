import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';

export function AgentDashboard() {
  const { currentUser, role } = useAuth();

  const [cases, setCases] = useState([]);
  const [selectedCase, setSelectedCase] = useState(null);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Two-Way Messaging State
  const [messages, setMessages] = useState([]);
  const [newMessage, setNewMessage] = useState('');
  const [sendingMessage, setSendingMessage] = useState(false);
  const [msgError, setMsgError] = useState(null);
  const messagesEndRef = useRef(null);

  // Resolution Form State
  const [actionChoice, setActionChoice] = useState('APPROVE');
  const [operatorNote, setOperatorNote] = useState('');
  const [submittingResolution, setSubmittingResolution] = useState(false);
  const [resolutionMessage, setResolutionMessage] = useState(null);

  // Load cases list
  useEffect(() => {
    if (role === 'agent') {
      loadCases();
    }
  }, [role, statusFilter]);

  // Polling for cases and active case conversation
  useEffect(() => {
    if (role !== 'agent') return;

    const interval = setInterval(() => {
      // Background refresh queue
      api.getHandoffCases(statusFilter)
        .then((data) => {
          setCases(data);
          if (selectedCase) {
            const updated = data.find((c) => c.id === selectedCase.id);
            if (updated) setSelectedCase((prev) => ({ ...prev, ...updated }));
          }
        })
        .catch(() => {});

      // Background refresh messages for selected case
      if (selectedCase?.id) {
        api.getHandoffMessages(selectedCase.id)
          .then((msgs) => setMessages(msgs))
          .catch(() => {});
      }
    }, 2500);

    return () => clearInterval(interval);
  }, [role, statusFilter, selectedCase?.id]);

  // Load messages when selected case changes
  useEffect(() => {
    if (selectedCase?.id) {
      loadMessages(selectedCase.id);
    } else {
      setMessages([]);
    }
  }, [selectedCase?.id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function loadCases() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getHandoffCases(statusFilter);
      setCases(data);
      if (selectedCase) {
        const updated = data.find((c) => c.id === selectedCase.id);
        if (updated) setSelectedCase(updated);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadMessages(caseId) {
    try {
      const msgs = await api.getHandoffMessages(caseId);
      setMessages(msgs);
    } catch (err) {
      // Silently handle polling errors
    }
  }

  async function handleSendMessage(e) {
    e.preventDefault();
    if (!selectedCase || !newMessage.trim() || sendingMessage) return;

    const textToSend = newMessage.trim();
    setSendingMessage(true);
    setMsgError(null);

    try {
      const sentMsg = await api.sendHandoffMessage(selectedCase.id, textToSend);
      setMessages((prev) => [...prev, sentMsg]);
      setNewMessage('');
      // If case was pending/waiting, update local status to AGENT_CONNECTED
      if (['PENDING', 'WAITING'].includes(selectedCase.status)) {
        setSelectedCase((prev) => ({
          ...prev,
          status: 'AGENT_CONNECTED',
          status_display: 'Agent Connected',
        }));
      }
      await loadCases();
    } catch (err) {
      setMsgError(err.message);
    } finally {
      setSendingMessage(false);
    }
  }

  async function handleResolveCase(e) {
    e.preventDefault();
    if (!selectedCase) return;

    if (!operatorNote.trim() || operatorNote.trim().length < 3) {
      setError('A mandatory operator explanation note of at least 3 characters is required.');
      return;
    }

    setSubmittingResolution(true);
    setError(null);
    setResolutionMessage(null);

    try {
      const payload = {
        action: actionChoice,
        agent_id: currentUser.id,
        notes: operatorNote.trim(),
      };

      const res = await api.resolveHandoffCase(selectedCase.id, payload);
      setResolutionMessage(res.explanation);
      setOperatorNote('');
      await loadCases();
      if (selectedCase?.id) {
        const updatedCase = await api.getHandoffCase(selectedCase.id);
        setSelectedCase(updatedCase);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmittingResolution(false);
    }
  }

  const isCaseClosed = selectedCase && ['APPROVED', 'REJECTED', 'RESOLVED', 'CANCELLED'].includes(selectedCase.status);

  // Role Gate: If authenticated user is NOT an agent
  if (role !== 'agent') {
    return (
      <div style={{ maxWidth: '600px', margin: '3rem auto' }}>
        <div className="glass-card-elevated" style={{ textAlign: 'center', borderColor: 'var(--danger)' }}>
          <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>🚫</div>
          <h2 style={{ fontFamily: 'var(--font-display)', color: '#F87171', marginBottom: '0.75rem' }}>
            Access Restricted: Agent Privileges Required
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: 1.5, marginBottom: '1.5rem' }}>
            You are currently signed in as <strong>{currentUser?.holder_name || 'Customer'}</strong> (Role: {role}).
            The Human-Agent Escalation Dashboard requires an account with banking specialist authorization.
          </p>
          <div style={{ background: 'var(--bg-secondary)', padding: '1rem', borderRadius: 'var(--radius-md)', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            To inspect the agent dashboard, switch to the seeded <strong>Support Agent</strong> profile (acc_agent) from the profile menu.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="agent-dashboard-grid">
      {/* Left Column: Escalation Queue */}
      <div className="glass-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.25rem', fontWeight: 700 }}>
              Escalation Queue
            </h2>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Human-in-the-loop safety & review cases
            </div>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={loadCases}
            style={{ fontSize: '0.75rem', padding: '0.35rem 0.65rem' }}
          >
            Refresh
          </button>
        </div>

        {/* Filter Badges */}
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
          {['ALL', 'WAITING', 'AGENT_CONNECTED', 'APPROVED', 'REJECTED', 'CANCELLED'].map((filter) => (
            <button
              key={filter}
              type="button"
              onClick={() => setStatusFilter(filter)}
              style={{
                background: statusFilter === filter ? 'var(--primary)' : 'var(--bg-tertiary)',
                color: statusFilter === filter ? 'white' : 'var(--text-secondary)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '0.25rem 0.55rem',
                fontSize: '0.7rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {filter.replace('_', ' ')}
            </button>
          ))}
        </div>

        {/* Case List */}
        {loading && <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', padding: '1rem' }}>Loading cases...</div>}

        {!loading && cases.length === 0 && (
          <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            No handoff cases found matching filter "{statusFilter}".
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', maxHeight: '580px', overflowY: 'auto' }}>
          {cases.map((c) => {
            const isSelected = selectedCase?.id === c.id;
            const isPending = ['PENDING', 'WAITING'].includes(c.status);
            const isConnected = c.status === 'AGENT_CONNECTED';
            const isApproved = ['APPROVED', 'RESOLVED'].includes(c.status);

            const badgeBg = isPending
              ? 'rgba(245, 158, 11, 0.2)'
              : isConnected
              ? 'rgba(56, 189, 248, 0.2)'
              : isApproved
              ? 'rgba(16, 185, 129, 0.2)'
              : 'rgba(239, 68, 68, 0.2)';

            const badgeColor = isPending
              ? '#FBBF24'
              : isConnected
              ? '#38BDF8'
              : isApproved
              ? '#34D399'
              : '#F87171';

            return (
              <div
                key={c.id}
                onClick={() => setSelectedCase(c)}
                style={{
                  padding: '0.85rem',
                  borderRadius: 'var(--radius-md)',
                  background: isSelected ? 'rgba(99, 102, 241, 0.15)' : 'var(--bg-secondary)',
                  border: isSelected ? '1px solid var(--primary)' : '1px solid var(--border-subtle)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                  <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                    {c.customer_name}
                  </span>
                  <span
                    style={{
                      fontSize: '0.65rem',
                      fontWeight: 700,
                      padding: '0.15rem 0.45rem',
                      borderRadius: 'var(--radius-sm)',
                      background: badgeBg,
                      color: badgeColor,
                    }}
                  >
                    {c.status_display || c.status}
                  </span>
                </div>
                <div style={{ fontSize: '0.75rem', color: '#CBD5E1', marginBottom: '0.3rem' }}>
                  Reason: <strong>{c.escalation_reason}</strong>
                  {c.uncertain_field && <span> ({c.uncertain_field})</span>}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  <span>ID: {c.id}</span>
                  <span>{new Date(c.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right Column: Case Detail, Two-Way Conversation & Resolution */}
      <div className="glass-card-elevated" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        {!selectedCase ? (
          <div style={{ padding: '4rem 2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>📋</div>
            <h3 style={{ fontSize: '1.1rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
              Select a Case to Review
            </h3>
            <p style={{ fontSize: '0.85rem' }}>
              Choose any escalation from the queue on the left to examine speech context, message the customer, and submit an audit decision.
            </p>
          </div>
        ) : (
          <div>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)', fontWeight: 700, textTransform: 'uppercase' }}>
                  Case Dossier
                </span>
                <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', fontWeight: 700 }}>
                  {selectedCase.customer_name}
                </h3>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  ID: {selectedCase.id} | Session: {selectedCase.session_id}
                </div>
              </div>
              <div
                style={{
                  padding: '0.3rem 0.75rem',
                  borderRadius: 'var(--radius-full)',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  background: ['PENDING', 'WAITING'].includes(selectedCase.status)
                    ? 'rgba(245, 158, 11, 0.2)'
                    : selectedCase.status === 'AGENT_CONNECTED'
                    ? 'rgba(56, 189, 248, 0.2)'
                    : ['APPROVED', 'RESOLVED'].includes(selectedCase.status)
                    ? 'rgba(16, 185, 129, 0.2)'
                    : 'rgba(239, 68, 68, 0.2)',
                  color: ['PENDING', 'WAITING'].includes(selectedCase.status)
                    ? '#FBBF24'
                    : selectedCase.status === 'AGENT_CONNECTED'
                    ? '#38BDF8'
                    : ['APPROVED', 'RESOLVED'].includes(selectedCase.status)
                    ? '#34D399'
                    : '#F87171',
                }}
              >
                {selectedCase.status_display || selectedCase.status}
              </div>
            </div>

            {/* Context Fields */}
            <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', padding: '1rem', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>Escalation Reason:</span>
                <span style={{ fontWeight: 700, color: '#FBBF24' }}>{selectedCase.escalation_reason}</span>
              </div>
              {selectedCase.uncertain_field && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Uncertain Field:</span>
                  <span style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>{selectedCase.uncertain_field}</span>
                </div>
              )}
              {selectedCase.parsed_context?.pending_amount && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Parsed Amount:</span>
                  <span style={{ fontWeight: 700, color: '#38BDF8' }}>₹{selectedCase.parsed_context.pending_amount}</span>
                </div>
              )}
              {selectedCase.parsed_context?.pending_payee_name && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Candidate Payee:</span>
                  <span style={{ fontWeight: 600 }}>{selectedCase.parsed_context.pending_payee_name}</span>
                </div>
              )}
              {selectedCase.parsed_context?.raw_transcript && (
                <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Customer Speech Transcript:</div>
                  <div style={{ fontStyle: 'italic', color: 'var(--text-primary)', fontSize: '0.9rem' }}>
                    "{selectedCase.parsed_context.raw_transcript}"
                  </div>
                </div>
              )}
            </div>

            {/* TWO-WAY LIVE CONVERSATION PANEL */}
            <div
              style={{
                background: 'rgba(15, 23, 42, 0.6)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-lg)',
                padding: '1rem',
                marginBottom: '1.25rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontSize: '1.1rem' }}>💬</span>
                  <strong style={{ fontSize: '0.95rem' }}>Live Customer Conversation</strong>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  {messages.length} message{messages.length === 1 ? '' : 's'}
                </div>
              </div>

              {/* Messages Container */}
              <div
                style={{
                  maxHeight: '220px',
                  minHeight: '120px',
                  overflowY: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.6rem',
                  padding: '0.5rem',
                  background: 'var(--bg-tertiary)',
                  borderRadius: 'var(--radius-md)',
                  marginBottom: '0.75rem',
                }}
              >
                {messages.length === 0 ? (
                  <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem', padding: '1.5rem 0' }}>
                    No messages in this case yet. Send a message to initiate two-way communication with the customer.
                  </div>
                ) : (
                  messages.map((m) => {
                    const isAgent = m.sender_role === 'agent';
                    return (
                      <div
                        key={m.id}
                        style={{
                          alignSelf: isAgent ? 'flex-end' : 'flex-start',
                          maxWidth: '82%',
                          background: isAgent ? 'rgba(99, 102, 241, 0.25)' : 'rgba(30, 41, 59, 0.9)',
                          border: isAgent ? '1px solid rgba(99, 102, 241, 0.5)' : '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-md)',
                          padding: '0.6rem 0.85rem',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', marginBottom: '0.2rem' }}>
                          <span style={{ fontSize: '0.7rem', fontWeight: 700, color: isAgent ? '#A5B4FC' : '#38BDF8' }}>
                            {isAgent ? '👨‍💼 You (Agent)' : `👤 ${m.sender_name}`}
                          </span>
                          <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                            {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', wordBreak: 'break-word', lineHeight: 1.4 }}>
                          {m.message_text}
                        </div>
                      </div>
                    );
                  })
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Message Input Form */}
              {!isCaseClosed ? (
                <form onSubmit={handleSendMessage} style={{ display: 'flex', gap: '0.5rem' }}>
                  <input
                    type="text"
                    value={newMessage}
                    onChange={(e) => setNewMessage(e.target.value)}
                    placeholder="Type reply to customer..."
                    disabled={sendingMessage}
                    style={{
                      flex: 1,
                      padding: '0.6rem 0.85rem',
                      background: 'var(--bg-secondary)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                    }}
                  />
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={sendingMessage || !newMessage.trim()}
                    style={{ fontSize: '0.85rem', padding: '0.6rem 1rem' }}
                  >
                    {sendingMessage ? 'Sending...' : 'Send Reply'}
                  </button>
                </form>
              ) : (
                <div style={{ background: 'var(--bg-secondary)', padding: '0.5rem 1rem', borderRadius: 'var(--radius-md)', fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                  🔒 Case is {selectedCase.status_display || selectedCase.status}. Conversation is closed.
                </div>
              )}

              {msgError && (
                <div style={{ color: '#F87171', fontSize: '0.75rem', marginTop: '0.4rem' }}>
                  ⚠️ {msgError}
                </div>
              )}
            </div>

            {/* Resolution Form (Active for PENDING/CONNECTED or already resolved) */}
            {!isCaseClosed ? (
              <form onSubmit={handleResolveCase}>
                <div style={{ marginBottom: '1rem' }}>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>
                    Review Action Decision:
                  </label>
                  <div className="resolution-choice-group">
                    {[
                      { id: 'APPROVE', label: 'Approve Review', color: 'var(--success)' },
                      { id: 'REJECT', label: 'Reject / Block', color: 'var(--danger)' },
                      { id: 'REPEAT_REQUESTED', label: 'Request Repeat', color: 'var(--warning)' },
                    ].map((opt) => (
                      <label
                        key={opt.id}
                        style={{
                          flex: 1,
                          padding: '0.65rem 0.5rem',
                          background: actionChoice === opt.id ? 'var(--bg-tertiary)' : 'var(--bg-secondary)',
                          border: actionChoice === opt.id ? `2px solid ${opt.color}` : '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-md)',
                          fontSize: '0.8rem',
                          fontWeight: 600,
                          textAlign: 'center',
                          cursor: 'pointer',
                        }}
                      >
                        <input
                          type="radio"
                          name="actionChoice"
                          value={opt.id}
                          checked={actionChoice === opt.id}
                          onChange={(e) => setActionChoice(e.target.value)}
                          style={{ display: 'none' }}
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>
                </div>

                <div style={{ marginBottom: '1.25rem' }}>
                  <label htmlFor="agent-notes" style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.4rem' }}>
                    Mandatory Operator Explanation Note:
                  </label>
                  <textarea
                    id="agent-notes"
                    value={operatorNote}
                    onChange={(e) => setOperatorNote(e.target.value)}
                    placeholder="Enter reason for decision (e.g. 'Verified speech recording with customer over chat; confirmed payee Abhishek')."
                    rows={2}
                    style={{
                      width: '100%',
                      padding: '0.75rem',
                      borderRadius: 'var(--radius-md)',
                      background: 'var(--bg-tertiary)',
                      border: '1px solid var(--border-subtle)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                      fontFamily: 'inherit',
                      resize: 'vertical',
                    }}
                  />
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                    Minimum 3 characters required by backend audit engine.
                  </div>
                </div>

                {error && (
                  <div style={{ background: 'var(--danger-bg)', color: '#F87171', padding: '0.65rem', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', marginBottom: '1rem' }}>
                    ⚠️ {error}
                  </div>
                )}

                {resolutionMessage && (
                  <div style={{ background: 'var(--success-bg)', color: '#34D399', padding: '0.65rem', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', marginBottom: '1rem' }}>
                    ✓ {resolutionMessage}
                  </div>
                )}

                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submittingResolution || operatorNote.trim().length < 3}
                  style={{ width: '100%' }}
                >
                  {submittingResolution ? 'Submitting Resolution...' : 'Submit Agent Decision'}
                </button>
              </form>
            ) : (
              <div style={{ background: 'var(--bg-secondary)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--success)', marginBottom: '0.5rem' }}>
                  Case Closed ({selectedCase.status_display || selectedCase.status})
                </div>
                {selectedCase.agent_id && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Agent ID: <strong>{selectedCase.agent_id}</strong>
                  </div>
                )}
                {selectedCase.agent_notes && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
                    Operator Note: <em>"{selectedCase.agent_notes}"</em>
                  </div>
                )}
                {selectedCase.resolved_at && (
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
                    Resolved at: {new Date(selectedCase.resolved_at).toLocaleString()}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
