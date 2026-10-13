"""
Unit tests for replaceable Audio Anti-Spoofing Service adapter.
Verifies conservative risk tiers, honest mock reporting, and threshold boundaries.
"""

import pytest
from app.services.antispoof_service import (
    SwappableAntiSpoofService,
    AntiSpoofOutcome,
)


def test_unavailable_detector_honest_reporting():
    """
    HONEST REPORTING REQUIREMENT: When no real detector is integrated,
    the service returns UNAVAILABLE, does not fabricate a score, and enforces
    conservative PIN step-up.
    """
    service = SwappableAntiSpoofService(mode="unavailable")
    result = service.analyze_audio()

    assert result.outcome == AntiSpoofOutcome.UNAVAILABLE
    assert result.score is None
    assert result.is_mock is True
    assert result.requires_pin_step_up is True
    assert result.is_blocked is False
    assert "detector is unavailable" in result.explanation.lower()


def test_low_risk_classification():
    """Score < 0.30 yields LOW_RISK without blocking or forcing PIN."""
    service = SwappableAntiSpoofService(mode="low_risk")
    result = service.analyze_audio()

    assert result.outcome == AntiSpoofOutcome.LOW_RISK
    assert result.score is not None and result.score < 0.30
    assert result.requires_pin_step_up is False
    assert result.is_blocked is False
    # Honest documentation: Low acoustic risk is not identity verification
    assert "not identity verification" in result.explanation.lower()


def test_grey_zone_classification_forces_pin():
    """
    Score in [0.30, 0.70] yields GREY_ZONE.
    SAFETY INVARIANT: Ambiguous acoustic score forces mandatory PIN step-up.
    """
    service = SwappableAntiSpoofService(mode="grey_zone")
    result = service.analyze_audio()

    assert result.outcome == AntiSpoofOutcome.GREY_ZONE
    assert result.score is not None and 0.30 <= result.score <= 0.70
    assert result.requires_pin_step_up is True
    assert result.is_blocked is False


def test_high_risk_classification_blocks_transaction():
    """
    Score > 0.70 yields HIGH_RISK.
    SAFETY INVARIANT: Strong acoustic anomaly blocks payment immediately.
    """
    service = SwappableAntiSpoofService(mode="high_risk")
    result = service.analyze_audio()

    assert result.outcome == AntiSpoofOutcome.HIGH_RISK
    assert result.score is not None and result.score > 0.70
    assert result.is_blocked is True


def test_threshold_validation_rejects_inverted_values(monkeypatch):
    """Ensures threshold configuration cannot be configured with inverted bounds."""
    monkeypatch.setenv("ANTISPOOF_LOW_RISK_THRESHOLD", "0.80")
    monkeypatch.setenv("ANTISPOOF_HIGH_RISK_THRESHOLD", "0.20")

    with pytest.raises(ValueError):
        SwappableAntiSpoofService()
