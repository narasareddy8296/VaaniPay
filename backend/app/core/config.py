"""
Central application configuration and security threshold settings for VaaniPay.
Provides one authoritative configuration source loaded from environment variables.
"""

from functools import lru_cache
from typing import List, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Authoritative configuration model for VaaniPay backend.
    Enforces security thresholds, database connection strings, and application metadata.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Identification
    PROJECT_NAME: str = "VaaniPay"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"

    # Cryptography & Secrets (Default placeholder strictly for development)
    SECRET_KEY: str = "vaanipay-development-insecure-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Database
    DATABASE_URL: str = "sqlite:///./vaanipay.db"

    # =========================================================================
    # AUTHORITATIVE SECURITY & PAYMENT THRESHOLDS
    # =========================================================================
    # 1. Maximum voice transaction amount (ceiling per single voice transaction): ₹10,000
    MAX_VOICE_TX_AMOUNT: float = Field(
        default=10000.0,
        description="Maximum allowed amount in INR for a single voice-authorized transaction.",
    )

    # 2. Maximum cumulative voice payments allowed per rolling 24-hour period: ₹25,000
    MAX_DAILY_VOICE_PAYMENTS: float = Field(
        default=25000.0,
        description="Maximum cumulative voice payments in INR allowed in a 24-hour window.",
    )

    # 3. PIN step-up threshold: ₹2,000 (amounts strictly exceeding this trigger mandatory PIN step-up)
    PIN_STEP_UP_THRESHOLD: float = Field(
        default=2000.0,
        description="Transaction amount threshold in INR above which PIN verification is mandatory.",
    )

    # 4. PIN failure lockout limit: 3 attempts
    PIN_MAX_FAILED_ATTEMPTS: int = Field(
        default=3,
        description="Maximum consecutive failed PIN attempts allowed before session/account lockout.",
    )

    # 5. Challenge-response liveness validity window: 30 seconds
    LIVENESS_CHALLENGE_EXPIRY_SECONDS: int = Field(
        default=30,
        description="Time-to-live (TTL) in seconds for single-use randomized liveness challenge digits.",
    )

    # 6. Anti-spoof risk boundaries: Low Risk < 0.30, Grey Zone [0.30, 0.70], High Risk > 0.70
    ANTISPOOF_LOW_RISK_THRESHOLD: float = Field(
        default=0.30,
        description="Audio spoof score below which acoustic risk is considered low/clean.",
    )
    ANTISPOOF_HIGH_RISK_THRESHOLD: float = Field(
        default=0.70,
        description="Audio spoof score above which acoustic risk triggers automatic block and handoff.",
    )

    # CORS Configuration
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, str) and v.startswith("["):
            import json
            return json.loads(v)
        return v


@lru_cache
def get_settings() -> Settings:
    """Returns the cached singleton Settings instance."""
    return Settings()
