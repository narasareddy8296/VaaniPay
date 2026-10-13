"""Tests for security threshold defaults and environment overrides."""

import pytest
from app.core.config import Settings, get_settings


def test_authoritative_security_threshold_defaults():
    """
    Verifies that central configuration explicitly enforces all mandatory
    security thresholds from the assignment specification.
    """
    settings = Settings()

    # 1. Maximum voice transaction amount: ₹10,000
    assert settings.MAX_VOICE_TX_AMOUNT == 10000.0

    # 2. Maximum cumulative voice payments per rolling 24-hour period: ₹25,000
    assert settings.MAX_DAILY_VOICE_PAYMENTS == 25000.0

    # 3. PIN step-up threshold: ₹2,000
    assert settings.PIN_STEP_UP_THRESHOLD == 2000.0

    # 4. PIN failure limit: 3 attempts
    assert settings.PIN_MAX_FAILED_ATTEMPTS == 3

    # 5. Liveness challenge expiry: 30 seconds
    assert settings.LIVENESS_CHALLENGE_EXPIRY_SECONDS == 30

    # 6. Anti-spoof risk boundaries: 0.30 and 0.70
    assert settings.ANTISPOOF_LOW_RISK_THRESHOLD == 0.30
    assert settings.ANTISPOOF_HIGH_RISK_THRESHOLD == 0.70


def test_pin_threshold_and_payment_limits_are_distinct():
    """
    Ensures the PIN step-up threshold (₹2,000) is distinct and not confused
    with the maximum transaction limit (₹10,000).
    """
    settings = Settings()
    assert settings.PIN_STEP_UP_THRESHOLD < settings.MAX_VOICE_TX_AMOUNT
    assert settings.MAX_VOICE_TX_AMOUNT < settings.MAX_DAILY_VOICE_PAYMENTS


def test_configuration_environment_overrides(monkeypatch):
    """Verifies that security thresholds can be configured via environment variables."""
    monkeypatch.setenv("PIN_STEP_UP_THRESHOLD", "1500.0")
    monkeypatch.setenv("MAX_VOICE_TX_AMOUNT", "5000.0")
    monkeypatch.setenv("PIN_MAX_FAILED_ATTEMPTS", "5")
    monkeypatch.setenv("ANTISPOOF_LOW_RISK_THRESHOLD", "0.25")
    monkeypatch.setenv("ANTISPOOF_HIGH_RISK_THRESHOLD", "0.75")

    overridden_settings = Settings()
    assert overridden_settings.PIN_STEP_UP_THRESHOLD == 1500.0
    assert overridden_settings.MAX_VOICE_TX_AMOUNT == 5000.0
    assert overridden_settings.PIN_MAX_FAILED_ATTEMPTS == 5
    assert overridden_settings.ANTISPOOF_LOW_RISK_THRESHOLD == 0.25
    assert overridden_settings.ANTISPOOF_HIGH_RISK_THRESHOLD == 0.75


def test_cors_origins_parsing(monkeypatch):
    """Verifies parsing of CORS origins from comma-separated string or list."""
    monkeypatch.setenv("CORS_ORIGINS", "http://example.com, https://app.vaanipay.mock")
    settings = Settings()
    assert "http://example.com" in settings.CORS_ORIGINS
    assert "https://app.vaanipay.mock" in settings.CORS_ORIGINS
