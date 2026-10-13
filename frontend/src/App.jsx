import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginScreen } from './pages/LoginScreen';
import { CustomerBanking } from './pages/CustomerBanking';
import { AgentDashboard } from './pages/AgentDashboard';

function MainApplication() {
  const { currentUser, role, logout, availableAccounts, login } = useAuth();
  const [activeTab, setActiveTab] = useState('customer'); // 'customer' | 'agent'
  const [showProfileSwitcher, setShowProfileSwitcher] = useState(false);

  if (!currentUser) {
    return <LoginScreen />;
  }

  return (
    <div className="app-container">
      {/* Top Navigation Bar */}
      <header className="top-navbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          <div className="brand-badge">
            <div className="brand-icon">VP</div>
            <div>
              <div className="brand-title">VaaniPay</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Voice Banking Agent</div>
            </div>
          </div>
          <span className="brand-pill">Stage 4 Verified</span>
        </div>

        {/* View Switcher & Current User Badge */}
        <div className="nav-actions">
          {/* Tab navigation */}
          <div className="tab-switcher">
            <button
              type="button"
              className={`tab-btn ${activeTab === 'customer' ? 'active' : ''}`}
              onClick={() => setActiveTab('customer')}
            >
              Customer Banking
            </button>
            <button
              type="button"
              className={`tab-btn ${activeTab === 'agent' ? 'active' : ''}`}
              onClick={() => setActiveTab('agent')}
            >
              Agent Dashboard {role === 'agent' ? '★' : ''}
            </button>
          </div>

          {/* User Profile Pill */}
          <div style={{ position: 'relative' }}>
            <button
              type="button"
              onClick={() => setShowProfileSwitcher(!showProfileSwitcher)}
              className="user-status-pill"
              style={{ cursor: 'pointer', background: 'var(--bg-tertiary)' }}
            >
              <span>👤 <strong>{currentUser.holder_name}</strong></span>
              <span className={`role-badge ${role}`}>{role}</span>
              <span style={{ fontSize: '0.7rem' }}>▼</span>
            </button>

            {/* Profile Dropdown Menu */}
            {showProfileSwitcher && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: '110%',
                  width: '260px',
                  background: 'var(--bg-glass-elevated)',
                  backdropFilter: 'blur(20px)',
                  border: '1px solid var(--border-highlight)',
                  borderRadius: 'var(--radius-md)',
                  boxShadow: 'var(--shadow-lg)',
                  padding: '0.5rem',
                  zIndex: 100,
                }}
              >
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', padding: '0.4rem 0.6rem', fontWeight: 600 }}>
                  SWITCH DEMO PROFILE
                </div>
                {availableAccounts.map((acc) => (
                  <button
                    key={acc.id}
                    type="button"
                    onClick={() => {
                      login(acc.id);
                      setShowProfileSwitcher(false);
                    }}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      padding: '0.5rem 0.6rem',
                      background: acc.id === currentUser.id ? 'rgba(99, 102, 241, 0.2)' : 'transparent',
                      border: 'none',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                      cursor: 'pointer',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600 }}>{acc.holder_name}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Role: {acc.role}</div>
                    </div>
                    {acc.id === currentUser.id && <span style={{ color: 'var(--accent-cyan)' }}>✓</span>}
                  </button>
                ))}
                <div style={{ borderTop: '1px solid var(--border-subtle)', marginTop: '0.4rem', paddingTop: '0.4rem' }}>
                  <button
                    type="button"
                    onClick={() => {
                      logout();
                      setShowProfileSwitcher(false);
                    }}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      padding: '0.4rem 0.6rem',
                      background: 'transparent',
                      border: 'none',
                      color: '#F87171',
                      fontSize: '0.8rem',
                      cursor: 'pointer',
                    }}
                  >
                    Sign Out
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="main-content">
        {/* Global Simulated Ledger Notice */}
        <div className="disclaimer-banner">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="disclaimer-badge">SIMULATION NOTICE</span>
            <span>VaaniPay is connected to a mock double-entry ledger. No real currency is transferred.</span>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
            Auth: Demo-Safe Profile Selection
          </span>
        </div>

        {/* View Component */}
        {activeTab === 'customer' ? <CustomerBanking /> : <AgentDashboard />}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <MainApplication />
    </AuthProvider>
  );
}
