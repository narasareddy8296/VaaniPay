import React, { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null);
  const [availableAccounts, setAvailableAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Load available demo accounts and establish valid demo session on mount
  useEffect(() => {
    loadAccounts();
  }, []);

  async function loadAccounts() {
    try {
      setLoading(true);
      setError(null);
      const accounts = await api.getAccounts();
      setAvailableAccounts(accounts);

      const savedUserId = sessionStorage.getItem('vaanipay_demo_user');
      const savedToken = sessionStorage.getItem('vaanipay_session_token');
      const targetUser = accounts.find((a) => a.id === savedUserId) || accounts[0];

      if (targetUser) {
        if (!savedToken || savedUserId !== targetUser.id) {
          // Acquire server-validated session credential
          const loginRes = await api.loginDemo(targetUser.id);
          setCurrentUser(loginRes.account);
        } else {
          // Fetch freshest account balance with existing session
          try {
            const acc = await api.getAccount(targetUser.id);
            setCurrentUser(acc);
          } catch {
            // Re-authenticate if session expired or invalidated
            const loginRes = await api.loginDemo(targetUser.id);
            setCurrentUser(loginRes.account);
          }
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function login(accountId) {
    try {
      setLoading(true);
      setError(null);
      const res = await api.loginDemo(accountId);
      setCurrentUser(res.account);
      return res;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    sessionStorage.removeItem('vaanipay_demo_user');
    sessionStorage.removeItem('vaanipay_session_token');
    setCurrentUser(null);
  }

  async function refreshAccount() {
    if (!currentUser) return;
    try {
      const updated = await api.getAccount(currentUser.id);
      setCurrentUser(updated);
    } catch (err) {
      console.warn('Could not refresh account balance:', err);
    }
  }

  async function resetDemo() {
    try {
      setLoading(true);
      await api.resetDemoData();
      await loadAccounts();
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        availableAccounts,
        role: currentUser?.role || 'customer',
        loading,
        error,
        login,
        logout,
        refreshAccount,
        loadAccounts,
        resetDemo,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
