import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export function LoginScreen({ onLoginSuccess }) {
  const { availableAccounts, login, loading, error } = useAuth();
  const [selectedId, setSelectedId] = useState(availableAccounts[0]?.id || 'acc_priya');
  const [loginError, setLoginError] = useState(null);
  const [consentAcknowledged, setConsentAcknowledged] = useState(false);

  async function handleLoginSubmit(e) {
    e.preventDefault();
    setLoginError(null);

    if (!consentAcknowledged) {
      setLoginError('Please review and acknowledge the Speech & Demo Consent notice to continue.');
      return;
    }

    try {
      await login(selectedId);
      if (onLoginSuccess) {
        onLoginSuccess();
      }
    } catch (err) {
      setLoginError(err.message);
    }
  }

  return (
    <div style={{ maxWidth: '560px', margin: '2rem auto' }}>
      <div className="glass-card-elevated">
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div
            style={{
              width: '60px',
              height: '60px',
              margin: '0 auto 1rem',
              borderRadius: 'var(--radius-md)',
              background: 'linear-gradient(135deg, var(--primary), var(--accent-cyan))',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '2rem',
              color: 'white',
              boxShadow: 'var(--shadow-glow)',
            }}
          >
            VP
          </div>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '1.85rem', marginBottom: '0.5rem' }}>
            Sign In to VaaniPay
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Voice Banking Agent & Fail-Safe Dialogue Demo
          </p>
        </div>

        {/* Notice of Simulated Ledger & Demo Safe Authentication */}
        <div
          style={{
            background: 'rgba(99, 102, 241, 0.1)',
            border: '1px solid rgba(99, 102, 241, 0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            marginBottom: '1.5rem',
            fontSize: '0.85rem',
            lineHeight: 1.5,
          }}
        >
          <div style={{ fontWeight: 700, color: '#A5B4FC', marginBottom: '0.35rem' }}>
            🛡️ Simulated Ledger & Safe Demo Flow
          </div>
          <p style={{ color: '#CBD5E1' }}>
            VaaniPay operates strictly on a <strong>simulated mock ledger</strong>. No real financial
            rails or genuine bank accounts are connected. Select one of the seeded demo profiles below to test
            customer voice payments or the human-agent escalation dashboard.
          </p>
        </div>

        {/* Profile Selector */}
        <form onSubmit={handleLoginSubmit}>
          <div style={{ marginBottom: '1.5rem' }}>
            <label
              htmlFor="demo-account-select"
              style={{ display: 'block', fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.9rem' }}
            >
              Select Seeded Demo Profile:
            </label>
            <select
              id="demo-account-select"
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              style={{
                width: '100%',
                padding: '0.75rem 1rem',
                borderRadius: 'var(--radius-md)',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-primary)',
                fontSize: '0.95rem',
                cursor: 'pointer',
              }}
            >
              {availableAccounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.holder_name} ({acc.role.toUpperCase()}) — Balance: ₹
                  {acc.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  {acc.is_locked ? ' [LOCKED]' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Speech & Data Privacy Consent Section */}
          <div
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '1rem',
              marginBottom: '1.5rem',
              fontSize: '0.825rem',
            }}
          >
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
              🎙️ Speech Recognition Privacy Disclosure
            </div>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
              This web application uses your browser's native <strong>Web Speech API</strong>. Depending on
              your browser vendor (e.g., Google Chrome), voice audio or transcribed text may be transmitted
              to cloud speech recognition endpoints.
            </p>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
              <strong>Typed-Input Alternative:</strong> You may use the integrated keyboard text box at any time
              if you prefer not to use your microphone or if speech services are unavailable.
            </p>

            <label
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '0.65rem',
                cursor: 'pointer',
                color: 'var(--text-primary)',
                fontWeight: 500,
              }}
            >
              <input
                type="checkbox"
                id="consent-checkbox"
                checked={consentAcknowledged}
                onChange={(e) => setConsentAcknowledged(e.target.checked)}
                style={{ marginTop: '0.2rem' }}
              />
              <span>
                I understand that VaaniPay is a simulation, that speech transcripts may be processed by the
                browser speech engine, and that a typed fallback is always available.
              </span>
            </label>
          </div>

          {(loginError || error) && (
            <div
              style={{
                background: 'var(--danger-bg)',
                border: '1px solid var(--danger)',
                color: '#FCA5A5',
                padding: '0.75rem 1rem',
                borderRadius: 'var(--radius-md)',
                fontSize: '0.85rem',
                marginBottom: '1rem',
              }}
            >
              ⚠️ {loginError || error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading}
            style={{ width: '100%', padding: '0.85rem' }}
          >
            {loading ? 'Authenticating Profile...' : 'Launch Banking Session'}
          </button>
        </form>
      </div>
    </div>
  );
}
