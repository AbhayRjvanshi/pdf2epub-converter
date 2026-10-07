"""Phase 13: the validator state mapping - one concept, no divergence."""

from pdf2epub.validators.base import (
    DetectionOutcome,
    ValidatorState,
    states_from,
    status_for,
)


class _FakeValidator:
    id = "fake"
    display_name = "Fake"

    def __init__(self, state):
        self._state = state
        self.detect_calls = 0

    def detect(self):
        self.detect_calls += 1
        return DetectionOutcome(self._state, version="1.0")

    def validate(self, epub_path):
        raise NotImplementedError


def test_disabled_short_circuits_without_detecting():
    validator = _FakeValidator(ValidatorState.AVAILABLE)
    assert status_for(validator, enabled=False) is ValidatorState.DISABLED
    assert validator.detect_calls == 0


def test_enabled_available_maps_to_available():
    assert (
        status_for(_FakeValidator(ValidatorState.AVAILABLE), enabled=True)
        is ValidatorState.AVAILABLE
    )


def test_enabled_unavailable_becomes_required_but_missing():
    assert (
        status_for(_FakeValidator(ValidatorState.UNAVAILABLE), enabled=True)
        is ValidatorState.REQUIRED_BUT_MISSING
    )


def test_failed_to_run_propagates_distinct_from_absence():
    assert (
        status_for(_FakeValidator(ValidatorState.FAILED_TO_RUN), enabled=True)
        is ValidatorState.FAILED_TO_RUN
    )


def test_states_from_is_the_single_mapping():
    outcome = DetectionOutcome(ValidatorState.UNAVAILABLE)
    assert states_from(outcome, enabled=False) is ValidatorState.DISABLED
    assert states_from(outcome, enabled=True) is ValidatorState.REQUIRED_BUT_MISSING
