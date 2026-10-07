"""EPUBCheck wrapper: delegates to the engine's ``run_epubcheck`` only.

The wrapper never touches ``run_daisy_ace`` (pinned by test) and shares the
engine's single command-resolution path, so detection and execution can
never disagree about whether the tool exists.
"""

from __future__ import annotations

import subprocess

from ..engine import packaging_and_validation as pk
from .base import DetectionOutcome, ValidationResult, ValidatorState

_VERSION_TIMEOUT = 10


def _probe(argv: list[str]) -> DetectionOutcome:
    try:
        proc = pk._run_with_tree_kill([*argv, "--version"], _VERSION_TIMEOUT)
    except subprocess.TimeoutExpired:
        return DetectionOutcome(ValidatorState.FAILED_TO_RUN, detail="version probe timed out")
    except Exception as exc:  # probe machinery failed, distinct from absence
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


class EpubcheckValidator:
    id = "epubcheck"
    display_name = "EPUBCheck"

    def __init__(self, epubcheck_cmd="epubcheck") -> None:
        self._validator = pk.DualValidator(epubcheck_cmd=epubcheck_cmd)

    def detect(self) -> DetectionOutcome:
        argv = self._validator.resolved_epubcheck_argv()
        if argv is None:
            return DetectionOutcome(ValidatorState.UNAVAILABLE)
        return _probe(argv)

    def validate(self, epub_path) -> ValidationResult:
        passed, errors, log, available = self._validator.run_epubcheck(str(epub_path))
        detail = log if available else "not installed - skipped"
        if available and not passed:
            detail = f"{errors} error(s): {log[:500]}"
        return ValidationResult(passed=passed, detail=detail, available=available)
