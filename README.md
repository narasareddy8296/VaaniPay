# VaaniPay — Voice-Based Mock Banking Agent & Safe Dialogue System

VaaniPay is a voice-controlled mock banking agent that accepts English and Hinglish payment requests. Its core purpose is to prevent incorrect payments caused by misheard numerical amounts, ambiguous payee names, replayed audio recordings, or synthetic voice input.

> **CRITICAL SAFETY NOTE**: VaaniPay connects exclusively to a simulated mock double-entry ledger. It never transfers real money or connects to genuine payment rails.

---

## 1. Quick Start & Local Run Instructions

### Prerequisites
- **Python 3.11+**
- **Node.js 20+** and **npm**
- *(Optional)* **Docker Desktop** (for containerized deployment)

---

### Option A: Local Native Execution (Recommended)

#### Step 1: Start the FastAPI Backend Service
```bash
# Navigate to the backend directory
cd backend

# (Optional) Create and activate a virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# Install backend dependencies
pip install -r requirements.txt

# Start the development server (runs on port 8000)
uvicorn app.main:app --reload --port 8000
```
API endpoints will be available at:
- Interactive Swagger Docs: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`
- Versioned Health: `http://localhost:8000/api/v1/health`

#### Step 2: Start the React Frontend Application
```bash
# In a separate terminal, navigate to the frontend directory
cd frontend

# Install frontend dependencies
npm install

# Start the Vite development server (runs on port 5173)
npm run dev
```
Open your browser at `http://localhost:5173`.

---

### Option B: Docker Compose Execution (Full Container Stack)
Ensure Docker Desktop is running, then execute from the repository root:
```bash
docker compose up --build
```
This launches:
- `postgres`: Persistent PostgreSQL 16 database with volume `pgdata`.
- `backend`: FastAPI backend on `http://localhost:8000`.
- `frontend`: Production Nginx SPA on `http://localhost:5173`.

---

## 2. Seeded Demo Accounts & Authentication

The application automatically seeds three synthetic accounts on startup. PINs are securely hashed using **Argon2id** (memory cost: 64 MiB, time cost: 3 iterations):

| Account ID | Holder Name | Role | Starting Balance | Demo PIN | Purpose |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `acc_priya` | Priya Sharma | `customer` | **₹50,000.00** | `1234` | Primary customer voice banking demo |
| `acc_ramesh` | Ramesh Kumar | `customer` | **₹25,000.00** | `5678` | Secondary customer & beneficiary |
| `acc_agent` | Support Agent | `agent` | **₹0.00** | N/A | Human specialist escalation dashboard |

### Server-Validated Demo Sessions
- The demo login endpoint (`POST /api/v1/accounts/demo-login`) issues a cryptographically signed HMAC-SHA256 session token (`Authorization: Bearer <token>`).
- Every protected backend endpoint validates the session token and derives caller identity directly from the verified payload.
- Caller-supplied identity headers (`X-Caller-Id`, `X-User-Id`) are strictly ignored. Customers cannot access other customers' accounts or agent routes.
- **Notice**: This authentication is tailored for local evaluator demonstration. It does not replace enterprise OAuth2 / OIDC token servers in production.

---

## 3. Running Verification Test Suites

### Backend Unit & Security Tests (139 Tests)
```bash
cd backend
pytest -v
```
*Result: 139 passed, 0 failed in 19.2s.*

### Frontend Unit & State Machine Tests (10 Tests)
```bash
cd frontend
npm test
```
*Result: 10 passed, 0 failed in 86ms.*

### Frontend Production Bundle Build
```bash
cd frontend
npm run build
```
*Result: Production build succeeded in 769ms (dist: 265kB JS, 9.8kB CSS).*

---

## 4. Evaluator Demo Reset

To restore baseline balances (Priya ₹50,000, Ramesh ₹25,000) and clear account lockouts without dropping database tables:
- **Via UI**: Click **Reset Demo Data** in the header or login screen.
- **Via API**:
  ```bash
  curl -X POST http://localhost:8000/api/v1/accounts/demo-reset
  ```

---

## 5. Key Architectural Safeguards

1. **Deterministic Parser**: Rule-based normalization for Indian Hinglish numerals (*paanch sau*, *dedh hazaar*, *dhai sau*, *sawa do lakh*, *paune teen hazaar*, *two thousand paanch sau*).
2. **Dual-Engine Consensus Cross-Checking**: Mathematical amount ($A_1 == A_2$) and RapidFuzz payee consensus ($P_1 == P_2$) required before advancing.
3. **Multi-Modal Read-Back Card**: Visual card and spoken TTS. Active listening is halted prior to TTS to prevent acoustic feedback loops.
4. **Server Liveness Challenge**: Cryptographically random 4 digits with a 30-second TTL; single-use hash protection against audio replay.
5. **Risk-Based PIN Step-Up (Argon2id)**: Required for payments > ₹2,000, new payees, grey-zone acoustic score, or typed fallback. 3-attempt permanent lockout. Raw PINs are never stored or logged.
6. **Non-Executable Human Handoff**: Escalates ambiguous or high-risk cases. Agent approvals do **not** trigger payments.
7. **Double-Entry Ledger Integrity**: Every transaction writes balanced debits and credits ($\Delta Balance = 0$), enforces daily limits (₹25k) and single limits (₹10k), and deduplicates via idempotency keys.
8. **Audit Trail Cleanliness**: Plaintext PINs and raw audio binary buffers are strictly excluded from logs and audit records.

---

## 6. Known Limitations & Disclosures

1. **Simulated Mock Ledger Only**: VaaniPay is a demonstration prototype with an internal SQLite/PostgreSQL database. It has **no** connection to UPI, NPCI, IMPS, or real banks.
2. **Audio Anti-Spoofing Status**: The acoustic adapter (`backend/app/services/antispoof_service.py`) operates in honest mock/unavailable mode. When unavailable, it triggers conservative PIN step-up rather than fabricating deepfake detection confidence. No claims of production biometric deepfake defense are made without integrating a genuine, calibrated acoustic deepfake model (e.g., RawNet3 / AASIST).
3. **Browser Speech Vendor Telemetry**: The Web Speech API depends on browser-vendor cloud speech engines (e.g., Google Speech Services). A full local typed input fallback is provided for private or microphone-free testing.

---

## 7. Submission Artifacts & Documentation Index

- [DESIGN_NOTE.md](file:///d:/VaaniPay/DESIGN_NOTE.md) — Architecture summary, design decisions, and tradeoffs.
- [THREAT_MODEL.md](file:///d:/VaaniPay/THREAT_MODEL.md) — Comprehensive threat analysis and defensive countermeasures.
- [DEMO_SCRIPT.md](file:///d:/VaaniPay/DEMO_SCRIPT.md) — Step-by-step evaluator walkthrough script with expected outcomes.
- [EVALUATION_RESULTS.md](file:///d:/VaaniPay/EVALUATION_RESULTS.md) — Automated test results and verification matrix.
- [SECURITY_AUDIT.md](file:///d:/VaaniPay/SECURITY_AUDIT.md) — Detailed security audit findings and fixes.
- [IMPLEMENTATION_STATUS.md](file:///d:/VaaniPay/IMPLEMENTATION_STATUS.md) — Stage-by-stage implementation and verification status.
