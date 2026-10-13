# VaaniPay — System Architecture & Design Choices (Design Note)

**System Name**: VaaniPay  
**Version**: 0.1.0 (Stage 6 Hardened)  
**Type**: Voice-Controlled Mock Banking Dialogue Agent  
**Environment**: English & Hinglish Conversational Payments  

---

## 1. Architectural Overview

VaaniPay is designed as a fail-safe, voice-controlled banking agent that prioritizes financial correctness and customer intent verification over conversational flexibility. The system prevents erroneous fund transfers caused by misheard amounts, ambiguous names, replayed audio, or adversarial speech prompts.

```
+-----------------------------------------------------------------------------------+
|                                 CLIENT LAYER                                      |
|  React 19 / Vite SPA                                                              |
|  - Web Speech API (SpeechRecognition & SpeechSynthesis)                           |
|  - Local Typed Fallback Interface                                                 |
|  - Push-to-Talk State Controller (Acoustic Echo Guard: stops STT prior to TTS)    |
|  - Server-Validated Session Storage (Authorization: Bearer <session_token>)       |
+-----------------------------------------------------------------------------------+
                                       |
                                       | HTTPS / JSON (REST)
                                       v
+-----------------------------------------------------------------------------------+
|                                FASTAPI BACKEND                                    |
|                                                                                   |
|  [Security & Session Layer]                                                       |
|  - HMAC-SHA256 Server-Validated Demo Sessions (Token expiry, role binding)        |
|  - Caller Isolation Guard (Rejects forged X-Caller-Id / X-User-Id)                |
|  - Cross-Origin Resource Sharing (CORS) restricted to authorized origins          |
|                                                                                   |
|  [Dialogue State Machine - POST /api/v1/turn]                                     |
|  - Explicit States: CAPTURE -> CLARIFY -> READBACK -> CONFIRM -> LIVENESS         |
|                     -> STEP_UP_PIN -> EXECUTE -> RECEIPT / HANDOFF / CANCELLED    |
|  - Server-Enforced Transition Validation & Session Ownership Binding              |
|                                                                                   |
|  [Parsing & Disambiguation Core]                                                  |
|  - Deterministic Indian Numeral Parser (paanch sau, dedh hazaar, sawa do lakh)   |
|  - RapidFuzz Payee Resolver with Calibrated Ambiguity Zones (>=85%, 60-84%, <60%)|
|  - Dual-Engine Consensus Cross-Checker (Consensus on A1==A2 and P1==P2)          |
|  - Spoken Prompt Injection Defense (Adversarial text isolated as raw data)       |
|                                                                                   |
|  [Risk & Verification Engines]                                                    |
|  - Challenge-Response Liveness (Cryptographic 4 digits, 30s TTL, single-use hash) |
|  - Anti-Spoof Acoustic Adapter (Honest mock/unavailable mode; triggers step-up)  |
|  - Argon2id PIN Step-Up Manager (Memory-hard RFC 9106 profile, 3-try lockout)     |
|                                                                                   |
|  [Execution & Audit Boundary]                                                     |
|  - Double-Entry Payment Ledger Service (Atomic debits == credits, limits, idemp)  |
|  - Human Handoff Review Queue (Mandatory notes; review does NOT execute payment)  |
|  - Privacy Audit Trail (Plaintext PINs and raw audio binary strictly excluded)    |
+-----------------------------------------------------------------------------------+
                                       |
                                       | SQLAlchemy 2.0 Engine
                                       v
+-----------------------------------------------------------------------------------+
|                                DATABASE LAYER                                     |
|  - Local Dev / Test: SQLite with PRAGMA foreign_keys = ON                         |
|  - Production / Cloud: Hosted PostgreSQL (via psycopg2-binary)                    |
+-----------------------------------------------------------------------------------+
```

---

## 2. Key Design Decisions & Tradeoffs

### Decision 1: Deterministic Parser vs. Pure LLM Intent Extraction
- **Choice**: Implemented a rule-based deterministic parser for Indian and Hinglish numerical expressions (`backend/app/parsers/number_parser.py`) coupled with a secondary consensus extractor (`backend/app/core/cross_check.py`).
- **Rationale**: LLMs are non-deterministic and susceptible to hallucinations, rounding anomalies, or misinterpreting cultural fractions (*paanch sau* = 500, *dedh hazaar* = 1,500, *dhai sau* = 250, *sawa do lakh* = 225,000, *paune teen hazaar* = 2,750).
- **Tradeoff**: Required handcrafting normalization grammars for prefixes, multipliers, and colloquial Hinglish stems. However, this guarantees exact integer amounts without runtime hallucinations.

### Decision 2: Dual-Engine Consensus Cross-Checking
- **Choice**: Execution requires mathematical agreement ($A_1 == A_2$) and payee alignment ($P_1 == P_2$) between the primary parser and secondary extractor before advancing to read-back.
- **Rationale**: If one engine misinterprets background noise or ambiguous phrasing (e.g., *"send 500 or 1000"*), the consensus check detects the mismatch and forces a clarification turn rather than executing an erroneous debit.
- **Tradeoff**: Introduces an extra verification stage; however, preventing incorrect fund transfers is the paramount safety objective.

### Decision 3: Server-Validated Sessions vs. Caller-Controlled Headers
- **Choice**: Deprecated `X-Caller-Id` / `X-User-Id` request headers in favor of server-validated HMAC-SHA256 signed session tokens (`Authorization: Bearer <token>`).
- **Rationale**: Client-controlled headers are trivial to forge in API tools (curl, Postman), enabling Broken Object Level Authorization (BOLA/IDOR). Server-issued tokens cryptographically bind the caller's account ID and role (`customer` vs `agent`) with strict expiration timestamps.
- **Tradeoff**: Requires clients to maintain a session credential in memory or session storage. For evaluators, the demo login endpoint (`POST /api/v1/accounts/demo-login`) makes acquiring this token instantaneous with a single click.

### Decision 4: Argon2id Memory-Hard PIN Hashing
- **Choice**: Replaced fast salted SHA-256 with Argon2id using `argon2-cffi` ($m=64\text{ MiB}$, $t=3$ iterations, $p=4$ lanes).
- **Rationale**: 4-digit PIN spaces consist of only 10,000 combinations. Fast hashes can be cracked in milliseconds on commodity GPUs. Argon2id's memory hardness resists hardware-accelerated dictionary attacks.
- **Tradeoff**: Computing hashes requires approximately 50-100ms of CPU time per PIN verification, which is an acceptable and desired latency for authentication security.

### Decision 5: Non-Executable Human Agent Resolution
- **Choice**: Human agent case approval (`POST /api/v1/handoff/cases/{id}/resolve`) is strictly an audit review decision. It does **not** invoke payment ledger execution.
- **Rationale**: Prevents rogue agents, compromised agent accounts, or social engineering attacks from arbitrarily triggering fund transfers. If an escalated case is reviewed and approved, the customer must still provide explicit confirmation and PIN step-up.

### Decision 6: Honest Anti-Spoofing & Deepfake Disclosure
- **Choice**: In the absence of a genuine trained acoustic deepfake neural network (e.g., AASIST / RawNet3), the acoustic service adapter operates in honest `UNAVAILABLE` or simulated mock mode.
- **Rationale**: Fabricating synthetic deepfake confidence scores would give false security assurances. When the acoustic adapter is unavailable, the system safely falls back to conservative PIN step-up.
