"""Opt-in onboarding for the external validators.

Detect-and-instruct only: the notice never installs anything. Choice 3
persists ``validators_notice = "never"``; choice 2 is session-only, so the
notice returns on the next launch (pinned by test). Phase 14's REPL calls
``show_onboarding`` at startup; the headless CLI never prompts.
"""

from __future__ import annotations

from .base import ValidatorState

INSTALL_INSTRUCTIONS = {
    "epubcheck": (
        "EPUBCheck (requires Java): download from "
        "https://github.com/w3c/epubcheck/releases and put an 'epubcheck' "
        "wrapper on PATH."
    ),
    "ace": "Ace by DAISY (requires Node.js): npm install -g @daisy/ace",
}


def _enabled(validator_id: str, config) -> bool:
    return {
        "epubcheck": config.epubcheck_enabled,
        "ace": config.ace_enabled,
    }.get(validator_id, False)


def missing_validators(validator_registry, config) -> list[str]:
    """Enabled validators that are not installed."""
    missing = []
    for validator in validator_registry.list():
        if not _enabled(validator.id, config):
            continue
        if validator.detect().state is ValidatorState.UNAVAILABLE:
            missing.append(validator.id)
    return missing


def should_show_notice(config) -> bool:
    return config.validators_notice != "never"


def show_onboarding(io, config_manager, validator_registry) -> None:
    """The three-option notice; entirely ScriptedIO-testable."""
    config = config_manager.load()
    if not should_show_notice(config):
        return
    missing = missing_validators(validator_registry, config)
    if not missing:
        return

    while True:
        io.write("Optional validators are not installed:")
        for validator_id in missing:
            io.write(f"  - {validator_id}")
        io.write("1. Show install instructions")
        io.write("2. Skip for this session")
        io.write("3. Don't show again")
        choice = io.read_line("Select (1/2/3): ").strip()
        if choice == "1":
            for validator_id in missing:
                io.write(
                    f"{validator_id}: "
                    f"{INSTALL_INSTRUCTIONS.get(validator_id, 'see project docs')}"
                )
            continue
        if choice == "2":
            return
        if choice == "3":
            config_manager.save(
                {"application": {"validators_notice": "never"}}
            )
            return
        io.write("please choose 1, 2 or 3")
