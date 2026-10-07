"""Ace by DAISY wrapper: delegates to the engine's ``run_daisy_ace`` only.

The wrapper never touches ``run_epubcheck`` (pinned by test) and resolves
its command through the engine's single path -- which is what makes an
npm-installed ``ace.cmd`` shim detectable and runnable on Windows.
"""

from __future__ import annotations

import json
import subprocess

from ..engine import packaging_and_validation as pk
from .base import DetectionOutcome, ValidationResult, ValidatorState

_VERSION_TIMEOUT = 10


def _probe(argv: list[str]) -> DetectionOutcome:
    try:
        proc = pk._run_with_tree_kill([*argv, "--version"], _VERSION_TIMEOUT)
    except subprocess.TimeoutExpired:
        return DetectionOutcome(ValidatorState.FAILED_TO_RUN, detail="version probe timed out")
    except Exception as exc:
        return DetectionOutcome(ValidatorState.FAILED_TO_RUN, detail=type(exc).__name__)
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        return DetectionOutcome(
            ValidatorState.FAILED_TO_RUN,
            detail=lines[0] if lines else f"exit {proc.returncode}",
        )
    lines = (proc.stdout or proc.stderr or "").strip().splitlines()
    return DetectionOutcome(
        ValidatorState.AVAILABLE, version=lines[0] if lines else ""
    )


class AceValidator:
    id = "ace"
    display_name = "Ace by DAISY"

    def __init__(self, ace_cmd: str = "ace") -> None:
        self._validator = pk.DualValidator(ace_cmd=ace_cmd)

    def detect(self) -> DetectionOutcome:
        resolved = self._validator.resolved_ace_cmd()
        if resolved is None:
            return DetectionOutcome(ValidatorState.UNAVAILABLE)
        return _probe([resolved])

    def validate(self, epub_path) -> ValidationResult:
        passed, violations, log, available = self._validator.run_daisy_ace(str(epub_path))
        detail = "not installed - skipped" if not available else json.dumps(violations)
        return ValidationResult(passed=passed, detail=detail, available=available)
