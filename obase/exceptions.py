from __future__ import annotations

from typing import Any


class OBaseError(Exception):
    retryable: bool = False


class StageContractViolation(OBaseError):
    retryable = False


class PauseRequested(OBaseError):
    retryable = False

    def __init__(self, reason: str = "", resume_data: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.resume_data: dict[str, Any] = resume_data or {}


class BudgetExceeded(OBaseError):
    retryable = False


class PricingNotConfiguredError(OBaseError):
    retryable = False

    def __init__(
        self,
        category: str,
        provider: str,
        model_or_tier: str,
        unit: str,
    ) -> None:
        super().__init__(
            f"No pricing for category={category!r} provider={provider!r} "
            f"model_or_tier={model_or_tier!r} unit={unit!r}"
        )
        self.category = category
        self.provider = provider
        self.model_or_tier = model_or_tier
        self.unit = unit


class EnvLoadError(OBaseError):
    retryable = False


class CacheError(OBaseError):
    retryable = True


class RateLimitExceeded(OBaseError):
    retryable = True


class ProviderNotFoundError(OBaseError):
    retryable = False


class ProviderDiscoveryError(OBaseError):
    retryable = False


class FSError(OBaseError):
    retryable = False


class ObaseAuthError(OBaseError):
    retryable = False


class ObaseSecretsError(OBaseError):
    retryable = False


class OBaseConnectionError(OBaseError):
    retryable = True


class OBaseNotFoundError(OBaseError):
    retryable = False


class OBaseValidationError(OBaseError):
    retryable = False
