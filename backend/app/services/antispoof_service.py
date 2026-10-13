"""
Audio Anti-Spoofing Service Adapter for VaaniPay.
Defines a swappable interface for acoustic deepfake and voice replay detection.
Enforces conservative safety tiers:
- LOW_RISK (< 0.30)
- GREY_ZONE (0.30 - 0.70) -> Mandatory PIN Step-Up
- HIGH_RISK (> 0.70) -> Automatic Block & Handoff
- UNAVAILABLE -> Conservative Step-Up / Handoff
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from app.core.config import get_settings


class AntiSpoofOutcome(str, Enum):
    LOW_RISK = "LOW_RISK"
    GREY_ZONE = "GREY_ZONE"
    HIGH_RISK = "HIGH_RISK"
    UNAVAILABLE = "UNAVAILABLE"


class AntiSpoofResult(BaseModel):
    """Result of audio anti-spoof analysis."""
    model_config = ConfigDict(from_attributes=True)

    outcome: AntiSpoofOutcome
    score: Optional[float] = None
    confidence: float = 0.0
    is_mock: bool = True
    model_name: str = "mock_service"
    requires_pin_step_up: bool = False
    is_blocked: bool = False
    explanation: str = ""
    metadata: Dict[str, Any] = {}


class BaseAntiSpoofService(ABC):
    """Abstract interface for audio anti-spoofing and deepfake detection."""

    @abstractmethod
    def analyze_audio(
        self,
        audio_bytes: Optional[bytes] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> AntiSpoofResult:
        """
        Analyzes audio sample or telemetry for signs of synthetic cloning, vocoding, or replay.
        SAFETY INVARIANT: Raw audio buffers must never be persisted or logged.
        """
        pass


class SwappableAntiSpoofService(BaseAntiSpoofService):
    """
    Configurable anti-spoof adapter supporting local mock modes,
    rule-based acoustic heuristics, or future pre-trained model integrations.
    """

    def __init__(
        self,
        mode: str = "unavailable",
        forced_score: Optional[float] = None,
        settings: Optional[Any] = None,
    ):
        """
        Modes:
        - 'unavailable': Real detector not loaded; triggers conservative fallback.
        - 'low_risk': Simulates clean genuine human voice.
        - 'grey_zone': Simulates ambiguous acoustics requiring PIN step-up.
        - 'high_risk': Simulates synthetic voice or replay attack (blocks payment).
        - 'simulated_score': Uses provided forced_score.
        """
        from app.core.config import Settings
        self.settings = settings or Settings()
        self.mode = mode
        self.forced_score = forced_score
        self._validate_thresholds()

    def _validate_thresholds(self):
        low = self.settings.ANTISPOOF_LOW_RISK_THRESHOLD
        high = self.settings.ANTISPOOF_HIGH_RISK_THRESHOLD
        if not (0.0 <= low <= high <= 1.0):
            raise ValueError(f"Invalid anti-spoof thresholds configured: low={low}, high={high}")

    def analyze_audio(
        self,
        audio_bytes: Optional[bytes] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> AntiSpoofResult:
        low_threshold = self.settings.ANTISPOOF_LOW_RISK_THRESHOLD
        high_threshold = self.settings.ANTISPOOF_HIGH_RISK_THRESHOLD

        # If telemetry supplies an explicit test scenario or score
        telemetry = telemetry or {}
        scenario = telemetry.get("scenario") or self.mode

        if scenario == "unavailable":
            # Honest reporting: No detector loaded in local development
            return AntiSpoofResult(
                outcome=AntiSpoofOutcome.UNAVAILABLE,
                score=None,
                confidence=0.0,
                is_mock=True,
                model_name="mock_unavailable",
                requires_pin_step_up=True,
                is_blocked=False,
                explanation=(
                    "Real acoustic anti-spoofing detector is unavailable in this environment. "
                    "Conservative policy applied: mandatory PIN step-up enforced."
                ),
                metadata={"reason": "DETECTOR_UNAVAILABLE"},
            )

        # Derive score based on scenario or forced score
        if self.forced_score is not None:
            score = self.forced_score
        elif scenario == "low_risk":
            score = 0.12
        elif scenario == "grey_zone":
            score = 0.48
        elif scenario == "high_risk":
            score = 0.88
        else:
            score = telemetry.get("spoof_score", 0.50)

        # Map score to conservative risk tiers
        if score > high_threshold:
            outcome = AntiSpoofOutcome.HIGH_RISK
            requires_pin = False
            is_blocked = True
            explanation = (
                f"High acoustic spoof risk detected (score: {score:.2f} > {high_threshold:.2f}). "
                "Automated transaction blocked; routing case to human review."
            )
        elif score >= low_threshold:
            outcome = AntiSpoofOutcome.GREY_ZONE
            requires_pin = True
            is_blocked = False
            explanation = (
                f"Acoustic score in grey zone ({low_threshold:.2f} <= {score:.2f} <= {high_threshold:.2f}). "
                "Conservative policy applied: requiring PIN step-up verification."
            )
        else:
            outcome = AntiSpoofOutcome.LOW_RISK
            requires_pin = False
            is_blocked = False
            explanation = (
                f"Audio acoustic check clean (score: {score:.2f} < {low_threshold:.2f}). "
                "Note: Low acoustic risk is not identity verification."
            )

        return AntiSpoofResult(
            outcome=outcome,
            score=round(score, 3),
            confidence=0.90,
            is_mock=True,
            model_name=f"swappable_adapter_{scenario}",
            requires_pin_step_up=requires_pin,
            is_blocked=is_blocked,
            explanation=explanation,
            metadata={
                "score": round(score, 3),
                "low_threshold": low_threshold,
                "high_threshold": high_threshold,
            },
        )


# Default global instance (initialized in unavailable mode by default for honest safety)
antispoof_service = SwappableAntiSpoofService(mode="unavailable")
