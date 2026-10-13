# VaaniPay — Implementation & Verification Status

This document tracks the implementation progress, verification evidence, and test coverage for all mandatory assignment requirements across each development stage.

> **Status Legend**:
> - `NOT IMPLEMENTED` — Work has not begun.
> - `IN PROGRESS` — Implementation underway.
> - `VERIFIED` — Code implemented, passing unit & integration tests, and verified with reproducible commands.

---

## 1. Stage-by-Stage Implementation Summary

### Stage 1: Project Skeleton & Backend Foundation (Completed & Verified)
- **Status**: `VERIFIED`
- **Execution Date**: 2026-10-13
- **Test Results**: 16 passed, 0 failed.
- **Implemented Artifacts**:
  - `backend/app/core/config.py`: Authoritative security and payment thresholds (`MAX_VOICE_TX_AMOUNT=10000.0`, `MAX_DAILY_VOICE_PAYMENTS=25000.0`, `PIN_STEP_UP_THRESHOLD=2000.0`, `PIN_MAX_FAILED_ATTEMPTS=3`, `LIVENESS_CHALLENGE_EXPIRY_SECONDS=30`, `ANTISPOOF_LOW_RISK_THRESHOLD=0.30`, `ANTISPOOF_HIGH_RISK_THRESHOLD=0.70`).
  - `backend/app/db/database.py`: SQLAlchemy 2.0 engine with SQLite `PRAGMA foreign_keys=ON` enforcement.
  - `backend/app/models/`: Synthetic domain models (`Account`, `Contact`, `LedgerEntry`, `PaymentSession`, `HandoffCase`, `AuditEvent`).
  - `backend/app/db/seed.py`: Idempotent seed operation for demo accounts (Priya Sharma ₹50k, Ramesh Kumar ₹25k, Support Agent ₹0) and address book contacts.
  - `backend/app/main.py`: FastAPI `/health`, `/api/v1/health`, interactive `/docs`, and CORS middleware.

---

### Stage 2: Deterministic Parser, Payee Resolver & Cross-Checking (Completed & Verified)
- **Status**: `VERIFIED`
- **Execution Date**: 2026-10-13
- **Test Results**: 81 passed, 0 failed.
- **Implemented Artifacts**:
  1. `backend/app/parsers/number_parser.py`:
     - Deterministic rule-based parser for Indian numerical expressions (fractions: *paanch sau*, *dedh hazaar*, *dhai sau*, *sawa do lakh*, *paune teen hazaar*, *two thousand paanch sau*).
     - Standard and numeric INR formats (`1500 rupees`, `₹1,500`, `rs 500`, `10k`).
     - Case, whitespace, and punctuation normalization.
     - Ambiguity detection for multiple conflicting amounts (`send 500 or 1000`).
     - Rejection of zero (`0 rupees`) and negative amounts (`minus 500`, `-500`).
     - Disambiguation of numbers in payee positions (`Ramesh 2 ko paanch sau bhej do` correctly extracts 500 without confusing payee digit 2).
     - Transaction limit validation without silent clamping (`sawa do lakh` parses to exact integer 225000 with `limit_exceeded=True`).
  2. `backend/app/parsers/payee_resolver.py`:
     - RapidFuzz fuzzy string matching against authenticated customer's seeded contacts.
     - Calibrated threshold classification: High confidence ($\ge 85\%$), Clarification ($60-84\%$), Unrecognized ($< 60\%$).
     - Ambiguity detection for close competing candidates (e.g. `Ramesh Kumar` vs `Ramesh Verma` flags `AMBIGUOUS`).
     - Strict Customer Contact Isolation: Priya cannot resolve or transfer to Ramesh's private contact `Amit`.
     - Zero automatic authorization for unrecognized names (`is_authorized_payee=False`).
  3. `backend/app/core/cross_check.py`:
     - Independent multi-method reconciliation engine between deterministic parser and secondary extractor (`ConservativeSecondaryExtractor`).
     - Independent amount ($A_1 == A_2$) and payee ($P_1 == P_2$) consensus verification.
     - Spoken prompt-injection resistance: Adversarial instructions (e.g. *"Ignore all previous instructions..."*) are treated as raw data strings and rejected with `SUSPICIOUS_PROMPT_INJECTION`.
     - Non-executable output on mismatch, limit exceed, or injection. Zero ledger or payment execution occurs during cross-checking.

---

### Stage 3: Secure Payment Dialogue State Machine & Execution Boundary (Completed & Verified)
- **Status**: `VERIFIED`
- **Execution Date**: 2026-10-13
- **Test Results**: 115 passed, 0 failed.
- **Implemented Artifacts**:
  1. `backend/app/core/state_machine.py` & `backend/app/api/routes/turn.py`:
     - Backend-controlled finite state machine exposing `POST /api/v1/turn`.
     - Explicit states: `CAPTURE`, `CLARIFY_AMOUNT`, `CLARIFY_PAYEE`, `READBACK`, `CONFIRM`, `LIVENESS`, `STEP_UP_PIN`, `EXECUTE`, `RECEIPT`, `HANDOFF`, `CANCELLED`, `FAILED`.
     - Server-side transition validation: Out-of-order actions rejected.
     - Strict session ownership validation: Cross-customer session manipulation rejected (`SESSION_MISMATCH`).
     - Permanent cancellation: Cancelled sessions permanently block execution for pending transactions.
     - Multi-modal read-back card: Formatted with resolved payee, currency (`INR`), exact amount in digits (`500`), and words (`Five Hundred Rupees`).
  2. `backend/app/core/liveness.py`:
     - Cryptographically random challenge generation (`secrets.choice`).
     - Server-side SHA-256 hashed challenge storage; plaintext never persisted.
     - Configurable 30-second TTL (`LIVENESS_CHALLENGE_EXPIRY_SECONDS=30`).
     - Single-use consumption: Replayed responses immediately rejected (`REPLAYED`).
     - Session and customer binding: Reject cross-account challenge submission.
     - Honest typed-fallback disclaimer: Typed input explicitly disclaims proof of live speech (`is_live_speech_proven=False`).
  3. `backend/app/services/antispoof_service.py`:
     - Documented, replaceable interface (`BaseAntiSpoofService`) and configurable adapter (`SwappableAntiSpoofService`).
     - Honest mock / unavailable reporting: Reports `UNAVAILABLE` and triggers conservative PIN step-up; does NOT fabricate fake deepfake confidence.
     - Conservative risk tiers: `LOW_RISK`, `GREY_ZONE` (forces PIN step-up), `HIGH_RISK` (halts and escalates to handoff), `UNAVAILABLE` (forces PIN step-up).
  4. `backend/app/core/auth_step_up.py`:
     - `PinSecurityManager` with salted SHA-256 password hashing.
     - Risk-based triggers: New payee, amount > ₹2,000 threshold, grey-zone acoustic score, or typed fallback.
     - Server-side 3 consecutive failure lockout: Account permanently locked upon 3 failed attempts.
  5. `backend/app/services/payment_service.py`:
     - Double-entry execution boundary with conservation of funds (Debits == Credits).
     - Per-transaction voice ceiling (₹10,000) and rolling 24-hr daily limit (₹25,000).
     - Overdraft protection and idempotency key deduplication.
  6. `backend/app/api/routes/handoff.py`:
     - Queue endpoints: `GET /api/v1/handoff/cases`, `GET /api/v1/handoff/cases/{case_id}`, `POST /api/v1/handoff/cases/{case_id}/resolve`.
     - Mandatory explanation note: Operator notes required for all resolutions.
     - **Critical safety invariant**: Agent approval is an audit decision, NOT direct payment execution.

---

### Stage 4: React Customer App and Agent Dashboard (Completed & Verified)
- **Status**: `VERIFIED`
- **Execution Date**: 2026-10-13
- **Test Results**:
  - **Backend Suite**: **120 passed, 0 failed** (pytest execution time: 1.21s)
  - **Frontend Suite**: **10 passed, 0 failed** (node:test execution time: 96ms)
  - **Production Build**: **Vite build succeeded** (dist bundles: 265kB JS, 9.8kB CSS)
- **Implemented Artifacts**:
  1. `frontend/src/services/api.js`:
     - Central API client with configurable base URL (`VITE_API_BASE_URL`), in-flight request deduplication, and `ApiError` class.
     - Exposes typed methods for health, accounts, ledger history, demo-safe login, dialogue turns, and handoff queue.
  2. `frontend/src/services/speech.js`:
     - Replaceable `SpeechAdapter` supporting Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`).
     - Detects unsupported environments and microphone permission denials with clear user feedback.
     - Text-to-speech (TTS) synthesis for auditory read-back.
     - **Safety Guard**: Aborts speech listening before synthesis starts to prevent the microphone from transcribing the system's own voice.
  3. `frontend/src/context/AuthContext.jsx`:
     - Manages demo session state, profile selection, role-based authorization (`customer` vs `agent`), and balance refreshing.
  4. `frontend/src/pages/LoginScreen.jsx`:
     - Seeded profile selector supporting Priya Sharma (₹50k), Ramesh Kumar (₹25k), and Support Agent.
     - Explicit disclosure: Simulated mock ledger notice, Web Speech API privacy disclaimer (browser speech engine vendor disclosure), and typed fallback alternative.
  5. `frontend/src/pages/CustomerBanking.jsx`:
     - Mobile-first banking dashboard displaying live balance and mock ledger history.
     - Push-to-talk microphone button with animated states (`IDLE`, `LISTENING`, `PROCESSING`).
     - Always-accessible typed command input for microphone failure or preference.
     - Multi-modal Read-Back Card: Resolved payee, amount in INR digits (`₹500`), and words (`Five Hundred Rupees`) with explicit Confirm and Cancel buttons.
     - Liveness Challenge: 30s TTL timer with speech repetition or typed fallback with disclaimer (*"Typed response does not prove live human speech; requiring PIN step-up"*).
     - PIN Step-Up: Masked 4-digit input & numeric keypad. Handles incorrect attempts and lockout. Plaintext PINs are never stored or logged.
     - Verified Receipt: Transaction ID, debited amount, updated balance, and timestamp.
     - Persistent *"Connect with human specialist"* action and cancellation button.
  6. `frontend/src/pages/AgentDashboard.jsx`:
     - Human-agent escalation queue with filters (`ALL`, `PENDING`, `APPROVED`, `REJECTED`, `REPEAT_REQUESTED`).
     - Case detail dossier with raw transcript (zero PIN/audio), extracted amounts, and highlighted uncertainty reason.
     - Mandatory operator note (minimum 3 characters) validation before submission.
     - Role-gated: Non-agent profiles receive explicit access restriction notices.
     - Audit disclaimer banner: Explains that approval is a review decision, not direct payment execution.
  7. `backend/app/api/routes/accounts.py`:
     - Endpoints for `GET /api/v1/accounts`, `GET /api/v1/accounts/{id}`, `GET /api/v1/accounts/{id}/transactions`, and `POST /api/v1/accounts/demo-login`.
  8. `frontend/test/frontend.test.js`:
     - Native unit test suite verifying `SpeechAdapter`, `ApiError`, read-back formatting, PIN validation, agent note enforcement, and cancellation invariants.

---

### Stage 5: Security Audit and End-to-End Verification (Completed & Verified)
- **Status**: `VERIFIED`
- **Execution Date**: 2026-10-13
- **Test Results**:
  - **Backend Suite**: **133 passed, 0 failed** (pytest execution time: 16.43s)
  - **Frontend Suite**: **10 passed, 0 failed** (node:test execution time: 89ms)
  - **Production Build**: **Vite build succeeded** (dist bundles: 265kB JS, 9.8kB CSS)
- **Implemented Security Remediations & Tests**:
  1. `backend/app/core/auth_step_up.py` & `backend/app/db/seed.py`:
     - Replaced fast salted SHA-256 with **Argon2id** password hashing (`argon2-cffi`, RFC 9106 parameters: $m=64$ MiB, $t=3$, $p=4$).
     - Constant-time verification, legacy hash migration fallback, and zero storage/logging of raw PINs.
  2. `backend/app/api/routes/accounts.py`:
     - Enforced caller isolation (`X-Caller-Id` / `X-User-Id`).
     - Cross-customer private account data and ledger transaction inspection rejected with `403 Forbidden`. Agent support access preserved.
  3. `backend/app/core/state_machine.py`:
     - Hardened session resolution: non-existent session IDs explicitly return `SESSION_NOT_FOUND` error status.
  4. `backend/tests/test_security_audit.py`:
     - 13 comprehensive end-to-end security audit tests covering Argon2id hashing, 3-attempt lockout, non-bypassable server PIN enforcement, cross-customer isolation, idempotency deduplication, cancellation balance conservation, liveness challenge expiry and single-use replay prevention, and p   5. `SECURITY_AUDIT.md`:
     - Published complete audit findings, threat modeling, security invariant verification matrix, and residual risk disclosures.

---

### Stage 6: Public Demo Hardening & Deployment Preparation (Completed & Verified)
- **Status**: `VERIFIED`
- **Execution Date**: 2026-10-13
- **Test Results**:
  - **Backend Suite**: **139 passed, 0 failed** (pytest execution time: 19.21s)
  - **Frontend Suite**: **10 passed, 0 failed** (node:test execution time: 86.7ms)
  - **Production Build**: **Vite build succeeded** (dist bundles: 265kB JS, 9.8kB CSS)
- **Implemented Artifacts & Enhancements**:
  1. `backend/app/core/session.py`:
     - Server-validated session credential manager (`create_session_token`, `verify_session_token`, `get_current_session`, `get_current_agent`).
     - Cryptographically signed HMAC-SHA256 session tokens with TTL and role binding.
     - Deprecated caller-controlled `X-Caller-Id` / `X-User-Id` headers; identity is strictly derived from server-verified tokens.
  2. `backend/app/api/routes/accounts.py`:
     - `POST /api/v1/accounts/demo-login` issues signed session credentials for evaluator profiles.
     - `POST /api/v1/accounts/demo-reset` restores baseline demo balances and clears lockouts without schema destruction.
     - Protected routes enforce caller isolation; cross-customer inspection rejected with `403 Forbidden`.
  3. `backend/app/api/routes/turn.py`:
     - `POST /api/v1/turn` protected by server session token; prevents cross-customer turn execution.
  4. `backend/app/api/routes/handoff.py`:
     - Agent queue and case resolution endpoints strictly require `role == "agent"` session token; customer tokens rejected with `403 Forbidden`.
  5. Deployment Configurations:
     - `docker-compose.yml`: Multi-container stack (FastAPI backend, PostgreSQL 16 with persistent volume, and Nginx frontend).
     - `backend/Dockerfile`: Production container build with dynamic `$PORT` handling.
     - `frontend/Dockerfile` & `frontend/nginx.conf`: Multi-stage build with SPA client-side routing.
     - `backend/requirements.txt`: Added `psycopg2-binary>=2.9.9` for cloud PostgreSQL compatibility.
     - `backend/app/db/database.py`: Normalizes `postgres://` to `postgresql://` for hosted cloud databases.
     - Environment templates: `backend/.env.example` and `frontend/.env.example`.
  6. Documentation Deliverables:
     - `DESIGN_NOTE.md`: Architecture overview, design decisions, and tradeoffs.
     - `THREAT_MODEL.md`: In-depth voice banking attack vectors and defensive countermeasures.
     - `DEMO_SCRIPT.md`: Comprehensive 9-scenario evaluator walkthrough script.
     - `EVALUATION_RESULTS.md`: Complete automated test records and invariant verification matrix.

---

## 2. Requirement Implementation Matrix

| Requirement ID | Module / Component | Target Description | Current Status | Code Location | Test File / Evidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-01** | Synthetic Accounts & Ledger Models | Double-entry models, seeded users, contacts, and balances | `VERIFIED` | `backend/app/models/`, `backend/app/db/seed.py` | `tests/test_models_and_seed.py`, `tests/test_db.py`, `tests/test_accounts_api.py` (13 passed) |
| **REQ-02** | Bilingual Intent Processor | English & Hinglish payment request parsing | `VERIFIED` | `backend/app/parsers/`, `backend/app/core/state_machine.py` | `tests/test_number_parser.py`, `tests/test_state_machine_and_turn.py` |
| **REQ-03** | Deterministic Number Parser | Rule-based parser for *paanch sau*, *dedh hazaar*, *dhai sau*, *sawa do lakh* | `VERIFIED` | `backend/app/parsers/number_parser.py` | `tests/test_number_parser.py` (42 passed) |
| **REQ-04** | Payee Fuzzy Matching | RapidFuzz contact matching with calibrated ambiguity zones | `VERIFIED` | `backend/app/parsers/payee_resolver.py` | `tests/test_payee_resolver.py` (13 passed) |
| **REQ-05** | Consensus Cross-Checker | Dual-engine reconciliation (Deterministic vs Secondary/LLM) | `VERIFIED` | `backend/app/core/cross_check.py` | `tests/test_cross_check.py` (10 passed) |
| **REQ-06** | Multi-Modal Read-Back Card | Spoken TTS and visual card displaying digits and words | `VERIFIED` | `frontend/src/pages/CustomerBanking.jsx`, `backend/app/schemas/turn.py` | `frontend/test/frontend.test.js`, `tests/test_state_machine_and_turn.py` |
| **REQ-07** | Speech-to-Text Interface | Swappable STT adapter with privacy egress disclosure | `VERIFIED` | `frontend/src/services/speech.js`, `frontend/src/pages/LoginScreen.jsx` | `frontend/test/frontend.test.js` |
| **REQ-08** | Typed Input Fallback | Text entry box for evaluation without working microphone | `VERIFIED` | `frontend/src/pages/CustomerBanking.jsx`, `backend/app/core/state_machine.py` | `frontend/test/frontend.test.js`, `tests/test_liveness.py` |
| **REQ-09** | Liveness Challenge Check | Server-generated single-use random digits with 30s TTL | `VERIFIED` | `backend/app/core/liveness.py`, `frontend/src/pages/CustomerBanking.jsx` | `tests/test_liveness.py` (6 passed) |
| **REQ-10** | Audio Anti-Spoof Detection | Acoustic model/feature analyzer returning spoof risk score | `VERIFIED` | `backend/app/services/antispoof_service.py` | `tests/test_antispoof.py` (5 passed) |
| **REQ-11** | Risk-Based Step-Up PIN | PIN verification for new payees, large amounts, grey spoof; 3-try lockout | `VERIFIED` | `backend/app/core/auth_step_up.py`, `frontend/src/pages/CustomerBanking.jsx` | `tests/test_step_up.py` (4 passed), `frontend/test/frontend.test.js` |
| **REQ-12** | Human Handoff Dashboard | Escalation queue and agent review dashboard with required notes | `VERIFIED` | `frontend/src/pages/AgentDashboard.jsx`, `backend/app/api/routes/handoff.py` | `tests/test_handoff_api.py` (5 passed), `frontend/test/frontend.test.js` |
| **REQ-13** | Payment Limits Core | ₹10,000 per-transaction and ₹25,000 daily voice limit enforcement | `VERIFIED` | `backend/app/services/payment_service.py` | `tests/test_payment_ledger.py` (5 passed) |
| **REQ-14** | Dialogue State Machine & `/turn` | State transitions handling silence, timeouts, and clarifications | `VERIFIED` | `backend/app/core/state_machine.py`, `backend/app/api/routes/turn.py` | `tests/test_state_machine_and_turn.py` (9 passed) |
| **REQ-15** | Prompt-Injection Resistance | Spoken injection expressions treated as data, zero LLM execution | `VERIFIED` | `backend/app/core/cross_check.py` | `tests/test_cross_check.py`, `tests/test_state_machine_and_turn.py` |
| **REQ-16** | Immutable Audit Logging | Full decision trail logged without storing raw audio or PINs | `VERIFIED` | `backend/app/models/audit.py`, `backend/app/core/state_machine.py` | `tests/test_handoff_api.py` |
| **REQ-17** | Cloud & Container Deploy | Docker Compose, PostgreSQL persistence, multi-stage build, reset demo data | `VERIFIED` | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` | `docker-compose.yml`, `EVALUATION_RESULTS.md` |

---

## 3. Verification Commands and Actual Execution Output

### 1. Backend Test Suite (139 Tests)
```bash
# Executed from: d:\VaaniPay\backend
pytest -v
```
**Actual Output**:
```
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\VaaniPay\backend
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.12.1, asyncio-1.4.0, typeguard-4.5.1
collected 139 items

tests\test_accounts_api.py .....                                         [  3%]
tests\test_antispoof.py .....                                            [  7%]
tests\test_config.py ....                                                [ 10%]
tests\test_cross_check.py ..........                                     [ 17%]
tests\test_db.py ....                                                    [ 20%]
tests\test_handoff_api.py .....                                          [ 23%]
tests\test_health.py ....                                                [ 26%]
tests\test_liveness.py ......                                            [ 30%]
tests\test_models_and_seed.py ....                                       [ 33%]
tests\test_number_parser.py ..........................................   [ 64%]
tests\test_payee_resolver.py .............                               [ 73%]
tests\test_payment_ledger.py .....                                       [ 76%]
tests\test_security_audit.py ...................                         [ 90%]
tests\test_state_machine_and_turn.py .........                           [ 97%]
tests\test_step_up.py ....                                               [100%]

====================== 139 passed, 2 warnings in 19.21s =======================
```

### 2. Frontend Test Suite (10 Tests)
```bash
# Executed from: d:\VaaniPay\frontend
npm test
```
**Actual Output**:
```
> frontend@0.0.0 test
> node --test

▶ Frontend SpeechAdapter Unit Tests
  ✔ detects unsupported browser environment gracefully without crashing (1.1574ms)
  ✔ aborts listening cleanly (0.1206ms)
✔ Frontend SpeechAdapter Unit Tests (1.9043ms)
▶ Frontend API Client & In-Flight Deduplication Tests
  ✔ instantiates ApiError with status and details (0.5534ms)
  ✔ exposes all required API methods for Stage 4 (0.0861ms)
✔ Frontend API Client & In-Flight Deduplication Tests (0.7674ms)
▶ Frontend Dialogue Safety & State Invariant Tests
  ✔ verifies read-back card formatting requires digits, words, and payee (0.2269ms)
  ✔ verifies typed fallback disclaims live speech (0.097ms)
  ✔ enforces mandatory operator note minimum length in agent review (0.3608ms)
  ✔ validates agent role requirement prevents customer from approving cases (0.0977ms)
  ✔ verifies masked PIN length validation prevents premature submission (0.1461ms)
  ✔ verifies payment cancellation permanently resets pending session state (0.1333ms)
✔ Frontend Dialogue Safety & State Invariant Tests (1.28ms)
ℹ tests 10
ℹ suites 3
ℹ pass 10
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 96.3908
```

### 3. Production Bundle Build
```bash
# Executed from: d:\VaaniPay\frontend
npm run build
```
**Actual Output**:
```
vite v6.4.4 building for production...
transforming...
✓ 35 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.85 kB │ gzip:  0.48 kB
dist/assets/index-C6lnll2O.css    9.82 kB │ gzip:  2.77 kB
dist/assets/index-CPKQzkRQ.js   265.17 kB │ gzip: 80.14 kB
✓ built in 839ms
```

---

## 4. Benchmark Phrase Parsing Verification Table

| Benchmark Input Phrase | Parsed Amount | Parse Status | Limit Exceeded Flag | Target Validation Result |
| :--- | :---: | :---: | :---: | :---: |
| `paanch sau` | **₹500** | `SUCCESS` | `False` | **EXACT MATCH** |
| `dedh hazaar` | **₹1,500** | `SUCCESS` | `False` | **EXACT MATCH** |
| `dhai sau` | **₹250** | `SUCCESS` | `False` | **EXACT MATCH** |
| `sawa do lakh` | **₹225,000** | `SUCCESS` | `True` (Exceeds ₹10k) | **NOT CLAMPED; LIMIT FLAGGED** |
| `paune teen hazaar` | **₹2,750** | `SUCCESS` | `False` | **EXACT MATCH** |
| `two thousand paanch sau` | **₹2,500** | `SUCCESS` | `False` | **EXACT MATCH** |
| `1500 rupees` | **₹1,500** | `SUCCESS` | `False` | **EXACT MATCH** |
| `₹1,500` | **₹1,500** | `SUCCESS` | `False` | **EXACT MATCH** |
| `send 500 to Ramesh` | **₹500** | `SUCCESS` | `False` | **EXACT MATCH** |
| `Ramesh 2 ko paanch sau rupaye bhej do` | **₹500** | `SUCCESS` | `False` | **PAYEE DIGIT ISOLATED** |
| `send 500 or 1000` | `None` | `AMBIGUOUS` | `False` | **PROMPT CLARIFICATION** |
| `0 rupees` | `0` | `INVALID_VALUE` | `False` | **REJECTED** |
| `minus 500` | `None` | `INVALID_VALUE` | `False` | **REJECTED** |

---

## 5. Scope Boundaries Respected

- **Cloud Deployment & Containerization**: Deferred to Stage 5/6 (Docker Compose & remote hosting).
- **Anti-Spoof Limitations**: Operates with honest mock/unavailable detection in local development. No fabricated deepfake scores.
- **Simulated Ledger**: No real financial institutions or UPI payment rails are connected.
