"""The application's validator registry (two residents, by design)."""

from __future__ import annotations

from .ace import AceValidator
from .base import Validator
from .epubcheck import EpubcheckValidator


class ValidatorRegistry:
    def __init__(self) -> None:
        self._validators: dict[str, Validator] = {}

    def register(self, validator: Validator) -> None:
        if validator.id in self._validators:
            raise ValueError(f"duplicate validator registration: {validator.id!r}")
        self._validators[validator.id] = validator

    def get(self, validator_id: str) -> Validator:
        try:
            return self._validators[validator_id]
        except KeyError:
            raise KeyError(
                f"unknown validator {validator_id!r}; "
                f"known: {sorted(self._validators)}"
            ) from None

    def list(self) -> list[Validator]:
        return list(self._validators.values())


def build_validator_registry() -> ValidatorRegistry:
    registry = ValidatorRegistry()
    registry.register(EpubcheckValidator())
    registry.register(AceValidator())
    return registry
