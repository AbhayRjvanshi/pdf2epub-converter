"""Level 1 request validation: never opens the PDF.

Reports every problem at once rather than raising on the first (poor CLI
ergonomics). Callers map ``input_errors`` to exit code 2 and
``config_errors`` to exit code 1; ``warnings`` are advisory. Credential
resolution is local (Phase 5) and belongs here so a named provider with no
credential fails before any conversion work -- decision #5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..config.credentials import CredentialResolutionResult, resolve_for_profile
from ..providers.requirements import resolve_model
from .models import ConversionRequest


@dataclass(frozen=True)
class RequestAssessment:
    input_errors: list[str] = field(default_factory=list)  # exit-2 class
    config_errors: list[str] = field(default_factory=list)  # exit-1 class
    warnings: list[str] = field(default_factory=list)
    credential: CredentialResolutionResult | None = None

    @property
    def ok(self) -> bool:
        return not self.input_errors and not self.config_errors


def validate_request(
    request: ConversionRequest,
    *,
    registry,
    explicit_secret: str | None = None,
    environ: Mapping[str, str] | None = None,
    require_provider: bool = True,
) -> RequestAssessment:
    """Check everything that does not require opening the document.

    ``require_provider=False`` is used by report-only dry runs: provider,
    credential and model checks are skipped because a dry run never spends.
    Report-only also skips output validation entirely -- nothing is
    written, so validation stays side-effect free (no mkdir, no overwrite
    refusal). PDF input checks always run.
    """
    input_errors: list[str] = []
    config_errors: list[str] = []
    warnings: list[str] = []
    credential: CredentialResolutionResult | None = None

    # -- input: PDF --------------------------------------------------------
    pdf = request.pdf_path
    if not pdf.exists():
        input_errors.append(f"input not found: {pdf}")
    elif not pdf.is_file():
        input_errors.append(f"input is not a file: {pdf}")

    # -- input: output (skipped for report-only: nothing is written) -------
    if not request.options.report_only:
        out = request.output_path
        if out.is_dir():
            input_errors.append(f"output path is a directory: {out}")
        else:
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                input_errors.append(
                    f"cannot create output directory {out.parent}: {exc}"
                )
            if out.exists() and not request.options.overwrite:
                input_errors.append(
                    f"output already exists (pass --force to overwrite): {out}"
                )

    # -- scalar bounds -----------------------------------------------------
    options = request.options
    if options.batch_size < 1:
        config_errors.append("batch_size must be >= 1")
    if options.max_repair_attempts < 0:
        config_errors.append("max_repair_attempts must be >= 0")
    if options.font_sample_pages < 1:
        config_errors.append("font_sample_pages must be >= 1")
    if options.max_tier2_pages is not None and options.max_tier2_pages < 0:
        config_errors.append("max_tier2_pages must be >= 0")

    # -- provider / credentials / model (report-only skips all of this) ----
    adapter = None
    if require_provider:
        try:
            adapter = registry.get(request.provider_id)
        except KeyError as exc:
            config_errors.append(exc.args[0] if exc.args else str(exc))

        if adapter is not None:
            if request.provider_id == "none":
                if request.conversion_model:
                    warnings.append(
                        "conversion_model is ignored for the offline provider"
                    )
            else:
                profile = getattr(adapter, "profile", None)
                if profile is None:
                    warnings.append(
                        f"provider {request.provider_id!r} exposes no credential "
                        "profile; credentials were not resolved"
                    )
                else:
                    credential = resolve_for_profile(
                        profile, explicit_secret=explicit_secret, environ=environ
                    )
                    if credential.source == "unavailable":
                        config_errors.append(
                            f"no credential for provider {request.provider_id!r}: "
                            f"set {profile.credential_env_var} or configure it via "
                            "`pdf2epub`"
                        )
                    elif credential.warning:
                        warnings.append(credential.warning)

                if not request.conversion_model:
                    config_errors.append(
                        f"provider {request.provider_id!r} requires a conversion_model"
                    )
                else:
                    resolution = resolve_model(adapter, request.conversion_model)
                    if resolution.warning:
                        warnings.append(resolution.warning)

    return RequestAssessment(
        input_errors=input_errors,
        config_errors=config_errors,
        warnings=warnings,
        credential=credential,
    )
