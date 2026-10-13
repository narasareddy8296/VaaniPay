# VaaniPay — Comprehensive Evaluation & Verification Results

**Date**: October 2026  
**Environment**: Windows 11, Python 3.13.9, Node.js v20.17.0, Vite 6.4.4, FastAPI 0.115.x  
**Status**: All Stage 1–6 Test Suites & Safety Invariants Verified  

---

## 1. Automated Test Suite Execution Summary

### 1.1 Backend Test Suite (Pytest)
- **Command**: `pytest -v` (in `backend/`)
- **Total Tests**: **139**
- **Passed**: **139**
- **Failed**: **0**
- **Execution Duration**: 19.21 seconds

#### Module-by-Module Breakdown:
| Test Module | Coverage Area | Count | Result |
| :--- | :--- | :---: | :---: |
| `tests/test_accounts_api.py` | Account details, contacts, demo login, session tokens, locked account block | 5 | **PASS** |
| `tests/test_antispoof.py` | Anti-spoof risk boundaries, adapter tiers, mock / unavailable fallback | 5 | **PASS** |
| `tests/test_config.py` | Central security thresholds, CORS origin validation, env loading | 4 | **PASS** |
| `tests/test_cross_check.py` | Deterministic vs secondary cross-checking, injection detection, limits | 10 | **PASS** |
| `tests/test_db.py` | Database session lifecycle, SQLite foreign key constraint enforcement | 4 | **PASS** |
| `tests/test_handoff_api.py` | Agent escalation queue, mandatory operator notes, non-executable approval | 5 | **PASS** |
| `tests/test_health.py` | Root `/health` and versioned `/api/v1/health` checks | 4 | **PASS** |
| `tests/test_liveness.py` | Random 4-digit challenge, SHA-256 challenge hash, 30s TTL, single-use replay block | 6 | **PASS** |
| `tests/test_models_and_seed.py` | Domain models, seed idempotency, contact associations | 4 | **PASS** |
| `tests/test_number_parser.py` | Indian numerals (*paanch sau*, *dedh hazaar*, *dhai sau*, *sawa do lakh*), limits | 42 | **PASS** |
| `tests/test_payee_resolver.py` | RapidFuzz contact matching, calibrated ambiguity bands, contact isolation | 13 | **PASS** |
| `tests/test_payment_ledger.py` | Double-entry balance conservation, rolling 24hr limits, idempotency | 5 | **PASS** |
| `tests/test_security_audit.py` | Argon2id verification, 3-try lockout, session tokens, forged header resistance, IDOR | 19 | **PASS** |
| `tests/test_state_machine_and_turn.py` | FSM transitions, read-back cards, confirmation, liveness, PIN, out-of-order rejection | 9 | **PASS** |
| `tests/test_step_up.py` | Risk triggers, 3-try failure lockout, reset on success | 4 | **PASS** |
| **Total** | | **139** | **100% PASS** |

---

### 1.2 Frontend Test Suite (Node Native Test Runner)
- **Command**: `npm test` (in `frontend/`)
- **Total Tests**: **10**
- **Passed**: **10**
- **Failed**: **0**
- **Execution Duration**: 86.7 milliseconds

#### Test Suites Verified:
1. `Frontend SpeechAdapter Unit Tests`: Graceful detection of unsupported environments, clean abort of listening before speech synthesis (2 tests).
2. `Frontend API Client & In-Flight Deduplication Tests`: `ApiError` initialization with status and details, exposure of all required API methods including session login and demo reset (2 tests).
3. `Frontend Dialogue Safety & State Invariant Tests`: Read-back card format validation (digits, words, payee), typed fallback live-speech disclaimer, mandatory agent operator note length validation, role-gated agent review, 4-digit masked PIN validation, payment cancellation session reset (6 tests).

---

### 1.3 Frontend Production Build Validation
- **Command**: `npm run build` (in `frontend/`)
- **Output**:
  - `dist/index.html` (0.85 kB)
  - `dist/assets/index-C6lnll2O.css` (9.82 kB)
  - `dist/assets/index-C5jk6VLu.js` (265.91 kB)
- **Result**: Built successfully in 769ms with zero bundling or syntax errors.

---

## 2. Invariant Verification Matrix

| # | Safety Invariant | Automated Test Evidence | Status |
| :-: | :--- | :--- | :-: |
| **INV-1** | **No Execution Without Explicit Confirmation** | `tests/test_security_audit.py::test_no_execution_before_explicit_confirmation` | **VERIFIED** |
| **INV-2** | **Consensus Mismatch Blocks Execution** | `tests/test_cross_check.py::test_cross_check_mismatch_amount_fails_consensus`<br>`tests/test_security_audit.py::test_amount_mismatch_blocks_execution` | **VERIFIED** |
| **INV-3** | **Prompt Injection Resistance** | `tests/test_security_audit.py::test_spoken_prompt_injection_routed_to_handoff`<br>`tests/test_cross_check.py::test_prompt_injection_flagged_as_suspicious` | **VERIFIED** |
| **INV-4** | **Server-Validated Sessions (No Forged Headers)** | `tests/test_security_audit.py::test_forged_identity_headers_ignored`<br>`tests/test_security_audit.py::test_missing_session_rejected_with_401`<br>`tests/test_security_audit.py::test_tampered_or_invalid_session_rejected_with_401` | **VERIFIED** |
| **INV-5** | **Cross-Customer Data Isolation (No IDOR/BOLA)** | `tests/test_security_audit.py::test_customer_cannot_read_another_customers_account`<br>`tests/test_security_audit.py::test_customer_cannot_read_another_customers_transactions`<br>`tests/test_security_audit.py::test_customer_cannot_execute_turn_for_another_account` | **VERIFIED** |
| **INV-6** | **Agent Non-Executable Resolution Boundary** | `tests/test_handoff_api.py::test_agent_approval_does_not_bypass_safeguards_or_execute_ledger`<br>`tests/test_handoff_api.py::test_agent_resolution_requires_agent_role` | **VERIFIED** |
| **INV-7** | **Liveness Randomness, Expiry & Single-Use Replay** | `tests/test_liveness.py::test_liveness_challenge_expiry_and_replay`<br>`tests/test_security_audit.py::test_liveness_challenge_expiry_and_replay_rejection` | **VERIFIED** |
| **INV-8** | **Argon2id Memory-Hard PIN & 3-Attempt Lockout** | `tests/test_security_audit.py::test_pin_argon2id_hashing_and_verification`<br>`tests/test_security_audit.py::test_locked_account_cannot_submit_payments`<br>`tests/test_step_up.py::test_pin_verification_and_lockout` | **VERIFIED** |
| **INV-9** | **Idempotent Duplicate Request Protection** | `tests/test_payment_ledger.py::test_idempotent_execution_prevents_duplicate_debits`<br>`tests/test_security_audit.py::test_repeated_payment_idempotency_does_not_double_debit` | **VERIFIED** |
| **INV-10**| **Double-Entry Balance Conservation** | `tests/test_security_audit.py::test_ledger_entries_strictly_balance`<br>`tests/test_payment_ledger.py::test_successful_payment_creates_balanced_ledger_entries` | **VERIFIED** |
| **INV-11**| **Cancellation Leaves Balances Untouched** | `tests/test_security_audit.py::test_cancellation_permanently_prevents_execution`<br>`tests/test_state_machine_and_turn.py::test_customer_cancellation_permanently_halts_payment` | **VERIFIED** |
| **INV-12**| **Audit Log Sanitation (Zero Audio, Zero PINs)** | `tests/test_security_audit.py::test_pin_never_in_audit_logs_or_handoff_cases`<br>`tests/test_handoff_api.py::test_audit_logs_contain_zero_raw_audio_and_zero_plaintext_pins` | **VERIFIED** |

---

## 3. Disclosures & Untested / Out-of-Scope Scenarios

1. **Remote Cloud Deployment Execution**:
   - Docker Compose configuration, multi-stage Dockerfiles (`backend/Dockerfile`, `frontend/Dockerfile`), and PostgreSQL cloud drivers (`psycopg2-binary`) were implemented and verified locally.
   - Live public deployment to external providers (e.g. Render, Vercel, Supabase) requires user account signup and provider authentication credentials. No fake URLs are claimed.
2. **Biometric Deepfake Neural Detector**:
   - The acoustic anti-spoof adapter is verified in honest `UNAVAILABLE` or simulated mock mode.
   - When unavailable, the system conservatively falls back to mandatory Argon2id PIN step-up.
   - Genuine deepfake detection models (e.g., AASIST / RawNet3) were not deployed in this mock internship assignment.
3. **Simulated Financial Ledger**:
   - All accounts and ledger entries exist in a simulated double-entry relational database. No real banking networks (UPI, IMPS, NEFT) are connected.
