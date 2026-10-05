"""The ConversionService: one typed door to the engine.

Composes the application layers from Phases 5-8 -- credential resolution,
provider adapters, two-level validation and the engine's additive seams --
into a single ``convert(request)`` call that always returns a structured
result and never lets an exception escape.

The service routes exactly once: preflight produces payload-free reports
and the engine consumes them through the S5 seam. Nothing here touches
engine internals; the legacy result dict is read back into a typed
``ConversionResult`` during the transition.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..config import AppConfig
from ..engine import driver
from ..engine.cancellation import CancellationToken
from ..engine.events import PipelineEvent
from ..providers.errors import ProviderError
from ..providers.registry import build_registry
from .models import ConversionRequest
from .preflight import PreflightResult, preflight
from .request import validate_request

_TITLE_SENTINEL = "Untitled Publication"
_AUTHOR_SENTINEL = "Unknown Author"


@dataclass
class ConversionResult:
    """Structured outcome of one conversion attempt.

    Error buckets map to CLI exit codes: ``input_errors`` -> 2,
    ``cancelled`` -> 130 (conventional SIGINT), everything else -> 1,
    success -> 0.
    """

    success: bool
    output_path: Path | None = None
    cancelled: bool = False
    input_errors: list[str] = field(default_factory=list)
    config_errors: list[str] = field(default_factory=list)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    preflight: PreflightResult | None = None
    chapter_count: int = 0
    validation_report: object | None = None
    elapsed_seconds: float = 0.0
    events: list[PipelineEvent] = field(default_factory=list)
    raw: dict | None = None  # legacy engine result, attached in transition
    report_only: bool = False

    @property
    def exit_code(self) -> int:
        """0 success, 130 cancelled, 2 input error, 1 any other failure."""
        if self.success:
            return 0
        if self.cancelled:
            return 130
        return 2 if self.input_errors else 1

    @property
    def all_errors(self) -> list[str]:
        """Aggregated error list for one-pass user reporting."""
        errors = list(self.input_errors) + list(self.config_errors)
        if self.error:
            errors.append(self.error)
        return errors


class ConversionService:
    """Drives one request through validation, preflight and the engine."""

    def __init__(
        self,
        *,
        registry=None,
        config: AppConfig | None = None,
        environ: Mapping[str, str] | None = None,
        event_cb=None,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        self._registry = registry if registry is not None else build_registry()
        self._config = config if config is not None else AppConfig()
        self._environ = environ
        self._event_cb = event_cb
        self._cancel_token = cancel_token

    # -- public API --------------------------------------------------------
    def convert(
        self, request: ConversionRequest, *, explicit_secret: str | None = None
    ) -> ConversionResult:
        started = time.monotonic()
        events: list[PipelineEvent] = []

        def collect(event: PipelineEvent) -> None:
            events.append(event)
            if self._event_cb is not None:
                self._event_cb(event)

        report_only = request.options.report_only

        # -- L1: never opens the PDF --------------------------------------
        assessment = validate_request(
            request,
            registry=self._registry,
            explicit_secret=explicit_secret,
            environ=self._environ,
            require_provider=not report_only,
        )
        if not assessment.ok:
            return ConversionResult(
                success=False,
                input_errors=list(assessment.input_errors),
                config_errors=list(assessment.config_errors),
                warnings=list(assessment.warnings),
                elapsed_seconds=time.monotonic() - started,
            )

        # -- L2: routes once, holds no payloads ---------------------------
        try:
            pre = preflight(request, registry=self._registry)
        except Exception as exc:  # a routing crash is an input-level problem
            return ConversionResult(
                success=False,
                input_errors=[f"preflight failed: {type(exc).__name__}: {exc}"],
                warnings=list(assessment.warnings),
                elapsed_seconds=time.monotonic() - started,
            )

        warnings = list(assessment.warnings) + list(pre.warnings)

        if report_only:
            if pre.document_error is not None:
                return ConversionResult(
                    success=False,
                    input_errors=[pre.document_error],
                    warnings=warnings,
                    preflight=pre,
                    report_only=True,
                    elapsed_seconds=time.monotonic() - started,
                )
            # a dry run cannot spend, so capability mismatches are advisory
            return ConversionResult(
                success=True,
                warnings=warnings + list(pre.problems),
                preflight=pre,
                report_only=True,
                elapsed_seconds=time.monotonic() - started,
            )

        if pre.document_error is not None:
            return ConversionResult(
                success=False,
                input_errors=[pre.document_error],
                warnings=warnings,
                preflight=pre,
                elapsed_seconds=time.monotonic() - started,
            )
        if pre.problems:
            return ConversionResult(
                success=False,
                config_errors=list(pre.problems),
                warnings=warnings,
                preflight=pre,
                elapsed_seconds=time.monotonic() - started,
            )

        # -- provider callable (offline maps to None, never a fake) -------
        llm_adapter = None
        if request.provider_id != "none":
            try:
                adapter = self._registry.get(request.provider_id)
                credential = (
                    assessment.credential.credential
                    if assessment.credential is not None
                    else None
                )
                llm_adapter = adapter.create_llm_callable(
                    request.conversion_model, credential
                )
            except ProviderError as exc:
                return ConversionResult(
                    success=False,
                    error=str(exc),
                    warnings=warnings,
                    preflight=pre,
                    elapsed_seconds=time.monotonic() - started,
                )

        # -- engine --------------------------------------------------------
        cache_dir = str(request.options.cache_dir or self._config.resolved_cache_dir)
        try:
            raw = driver.run_pipeline(
                pdf_path=str(request.pdf_path),
                output_epub=str(request.output_path),
                title=(
                    request.title if request.title is not None else _TITLE_SENTINEL
                ),
                author=(
                    request.author if request.author is not None else _AUTHOR_SENTINEL
                ),
                llm_adapter=llm_adapter,
                model_id=request.conversion_model or "gpt-4o",
                batch_size=request.options.batch_size,
                skip_validation=request.options.skip_validation,
                max_repair_attempts=request.options.max_repair_attempts,
                cache_dir=cache_dir,
                report_only=False,
                verbose=not request.options.quiet,
                font_sample_pages=request.options.font_sample_pages,
                spool_images=request.options.spool_images,
                validators=self._validators(),
                event_cb=collect,
                cancel_token=self._cancel_token,
                precomputed_reports=pre.reports,
            )
        except Exception as exc:
            return ConversionResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                warnings=warnings,
                preflight=pre,
                events=events,
                elapsed_seconds=time.monotonic() - started,
            )

        return self._from_raw(raw, request, pre, warnings, events, started)

    # -- internals ---------------------------------------------------------
    def _validators(self) -> tuple[str, ...] | None:
        """Config prefs -> the engine's S1 selector (None = both enabled)."""
        enabled = tuple(
            name
            for name, on in (
                ("epubcheck", self._config.epubcheck_enabled),
                ("ace", self._config.ace_enabled),
            )
            if on
        )
        return None if len(enabled) == 2 else enabled

    @staticmethod
    def _from_raw(
        raw: dict,
        request: ConversionRequest,
        pre: PreflightResult,
        warnings: list[str],
        events: list[PipelineEvent],
        started: float,
    ) -> ConversionResult:
        build = raw.get("build")
        return ConversionResult(
            success=bool(raw.get("success")),
            output_path=(
                request.output_path if build is not None else None
            ),
            cancelled=bool(raw.get("cancelled")),
            warnings=warnings,
            preflight=pre,
            chapter_count=len(build.chapters) if build is not None else 0,
            validation_report=raw.get("validation"),
            elapsed_seconds=time.monotonic() - started,
            events=events,
            raw=raw,
        )
