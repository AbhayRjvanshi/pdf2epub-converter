"""Phase 13: the validator registry."""

import pytest

from pdf2epub.validators import ValidatorRegistry, build_validator_registry


def test_build_registers_both_validators():
    registry = build_validator_registry()
    assert {v.id for v in registry.list()} == {"epubcheck", "ace"}
    assert registry.get("epubcheck").display_name == "EPUBCheck"
    assert registry.get("ace").display_name == "Ace by DAISY"


def test_duplicate_registration_fails():
    registry = build_validator_registry()
    with pytest.raises(ValueError):
        registry.register(registry.get("ace"))


def test_unknown_validator_names_the_known_ones():
    registry = build_validator_registry()
    with pytest.raises(KeyError) as excinfo:
        registry.get("nope")
    assert "epubcheck" in str(excinfo.value)
