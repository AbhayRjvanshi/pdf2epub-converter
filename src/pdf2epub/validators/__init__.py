"""Application-level validator integration (wrap, never re-implement)."""

from .ace import AceValidator
from .base import (
    DetectionOutcome,
    ValidationResult,
    Validator,
    ValidatorState,
    states_from,
    status_for,
)
from .epubcheck import EpubcheckValidator
from .onboarding import (
    INSTALL_INSTRUCTIONS,
    missing_validators,
    should_show_notice,
    show_onboarding,
    validator_enabled,
)
from .registry import ValidatorRegistry, build_validator_registry

__all__ = [
    "AceValidator",
    "DetectionOutcome",
    "EpubcheckValidator",
    "INSTALL_INSTRUCTIONS",
    "ValidationResult",
    "Validator",
    "ValidatorRegistry",
    "ValidatorState",
    "build_validator_registry",
    "missing_validators",
    "should_show_notice",
    "show_onboarding",
    "states_from",
    "status_for",
    "validator_enabled",
]
