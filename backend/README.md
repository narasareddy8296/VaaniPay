# VaaniPay — Backend Service

FastAPI-powered backend foundation for the VaaniPay voice banking agent.

## Prerequisites
- Python 3.11+
- SQLite 3 (included with Python) or PostgreSQL

## Setup Instructions

1. **Navigate to the backend directory**:
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment** (recommended):
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```

5. **Seed synthetic demonstration data** (idempotent):
   ```bash
   python -m app.db.seed
   ```

6. **Start the development server**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   - API Root: `http://localhost:8000/`
   - Health Endpoint: `http://localhost:8000/health`
   - Interactive Swagger Docs: `http://localhost:8000/docs`
   - ReDoc: `http://localhost:8000/redoc`

## Running Tests

From the backend directory:
```bash
pytest
```
Or from the project root:
```bash
python -m pytest backend
```

## Authoritative Security Thresholds
Configured in `app/core/config.py`:
- `MAX_VOICE_TX_AMOUNT`: ₹10,000.00 (Single voice payment limit)
- `MAX_DAILY_VOICE_PAYMENTS`: ₹25,000.00 (24-hour cumulative voice payment limit)
- `PIN_STEP_UP_THRESHOLD`: ₹2,000.00 (Mandatory PIN requirement trigger)
- `PIN_MAX_FAILED_ATTEMPTS`: 3 (Lockout limit)
- `LIVENESS_CHALLENGE_EXPIRY_SECONDS`: 30 (TTL for challenge digits)
- `ANTISPOOF_LOW_RISK_THRESHOLD`: 0.30 (Acoustic clean boundary)
- `ANTISPOOF_HIGH_RISK_THRESHOLD`: 0.70 (Acoustic high-risk block boundary)
