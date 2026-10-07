"""Application-level validator abstraction.

Wraps the engine's independent validator methods (never re-implements
validation). ``detect()`` reports installation truth; the five-state enum
is the mapping layered with configuration; ``states_from`` owns that
mapping so detection and status can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ValidatorState(Enum):
    DISABLED = "disabled"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REQUIRED_BUT_MISSING = "required_but_missing"
    FAILED_TO_RUN = "failed_to_run"


@dataclass(frozen=True)
class DetectionOutcome:
    """Result of an installation probe.

    ``state`` is one of AVAILABLE / UNAVAILABLE / FAILED_TO_RUN --
    the config-layered states (DISABLED / REQUIRED_BUT_MISSING) are
    produced by :func:`states_from`.
    """

    state: ValidatorState
    version: str = ""
    detail: str = ""


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    detail: str = ""
    available: bool = True


class Validator(Protocol):
    id: str
    display_name: str

    def detect(self) -> DetectionOutcome: ...

    def validate(self, epub_path) -> ValidationResult: ...


def states_from(outcome: DetectionOutcome, *, enabled: bool) -> ValidatorState:
    """The single config+detection mapping (one concept, no divergence)."""
    if not enabled:
        return ValidatorState.DISABLED
    if outcome.state is ValidatorState.UNAVAILABLE:
        return ValidatorState.REQUIRED_BUT_MISSING
    return outcome.state


def status_for(validator: Validator, *, enabled: bool) -> ValidatorState:
    """Derive the full state for a validator (detect() runs only if enabled)."""
    if not enabled:
        return ValidatorState.DISABLED
    return states_from(validator.detect(), enabled=True)
