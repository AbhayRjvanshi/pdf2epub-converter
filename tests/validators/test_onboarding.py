"""Phase 13: validator onboarding - detect and instruct, never install."""

from pdf2epub.config.manager import ConfigManager
from pdf2epub.validators.base import DetectionOutcome, ValidatorState
from pdf2epub.validators.onboarding import (
    missing_validators,
    show_onboarding,
)
from pdf2epub.validators.registry import ValidatorRegistry


class _FakeValidator:
    def __init__(self, validator_id, state):
        self.id = validator_id
        self.display_name = validator_id
        self._state = state

    def detect(self):
        return DetectionOutcome(self._state)

    def validate(self, epub_path):
        raise NotImplementedError


class _ScriptedIO:
    def __init__(self, lines=()):
        self._lines = list(lines)
        self.output = []
        self.prompts = []

    def read_line(self, prompt):
        self.prompts.append(prompt)
        return self._lines.pop(0) if self._lines else ""

    def write(self, text):
        self.output.append(text)

    @property
    def text(self):
        return "\n".join(self.output)


def _registry(*specs):
    registry = ValidatorRegistry()
    for validator_id, state in specs:
        registry.register(_FakeValidator(validator_id, state))
    return registry


def _manager(tmp_path, **validator_prefs):
    manager = ConfigManager(tmp_path / "config.toml")
    if validator_prefs:
        manager.save({"validator": validator_prefs})
    return manager


def test_missing_lists_only_enabled_and_unavailable(tmp_path):
    registry = _registry(
        ("epubcheck", ValidatorState.UNAVAILABLE),
        ("ace", ValidatorState.AVAILABLE),
    )
    assert missing_validators(registry, _manager(tmp_path).load()) == ["epubcheck"]


def test_disabled_validators_are_not_reported_missing(tmp_path):
    registry = _registry(("epubcheck", ValidatorState.UNAVAILABLE))
    config = _manager(tmp_path, epubcheck=False).load()
    assert missing_validators(registry, config) == []


def test_dont_show_again_persists(tmp_path):
    registry = _registry(("ace", ValidatorState.UNAVAILABLE))
    manager = _manager(tmp_path)
    show_onboarding(_ScriptedIO(lines=["3"]), manager, registry)
    assert manager.load().validators_notice == "never"

    # suppressed on the next launch
    io = _ScriptedIO(lines=[])
    show_onboarding(io, ConfigManager(tmp_path / "config.toml"), registry)
    assert io.prompts == []


def test_skip_this_session_does_not_persist(tmp_path):
    registry = _registry(("ace", ValidatorState.UNAVAILABLE))
    manager = _manager(tmp_path)
    show_onboarding(_ScriptedIO(lines=["2"]), manager, registry)
    assert manager.load().validators_notice == "always"

    # the notice returns next launch
    io = _ScriptedIO(lines=["2"])
    show_onboarding(io, ConfigManager(tmp_path / "config.toml"), registry)
    assert io.prompts  # it asked again


def test_instructions_are_shown_then_reprompted(tmp_path):
    registry = _registry(("ace", ValidatorState.UNAVAILABLE))
    manager = _manager(tmp_path)
    io = _ScriptedIO(lines=["1", "2"])
    show_onboarding(io, manager, registry)
    assert "npm install" in io.text  # detect-and-instruct, nothing installed
    assert len(io.prompts) == 2  # reprompted after the instructions


def test_no_notice_when_nothing_is_missing(tmp_path):
    registry = _registry(("ace", ValidatorState.AVAILABLE))
    io = _ScriptedIO(lines=[])
    show_onboarding(io, _manager(tmp_path), registry)
    assert io.prompts == []
