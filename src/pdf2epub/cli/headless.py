"""Headless CLI: the shipped product surface.

Commands: ``pdf2epub convert`` and ``pdf2epub --version``. Every legacy
flag maps 1:1 onto ConversionRequest/ConversionOptions; the exit code
comes from ConversionResult.exit_code (0 success, 2 input, 1 other,
130 interrupted).

CLI omission means "no override": --provider/--model fall back to the
saved AppConfig and then to the default (offline / the provider's first
catalog model); an omitted --cache-dir stays None and the service applies
the same config -> platform layering.

``KeyboardInterrupt -> 130`` here is a CLI-level guard only; cooperative
cancellation (CancellationToken) belongs to the REPL/session work of
Phase 14. The ``doctor``/``validators`` subcommands arrive with their
logic in Phase 13.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .. import __version__
from ..application import (
    ConversionOptions,
    ConversionRequest,
    ConversionService,
    format_routing_table,
    run_doctor,
)
from ..config import AppConfig, ConfigManager
from ..providers.registry import build_registry
from ..validators import build_validator_registry, status_for, validator_enabled


def build_parser(provider_choices: Sequence[str] | None = None) -> argparse.ArgumentParser:
    """The public parser; Phase 13 extends it with doctor/validators."""
    parser = argparse.ArgumentParser(
        prog="pdf2epub",
        description="Hybrid PDF to EPUB3 converter.",
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"pdf2epub {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="convert a PDF into an EPUB3")
    convert.add_argument("pdf_path", help="input PDF")
    convert.add_argument(
        "-o", "--output", default="output.epub",
        help="output EPUB path (default: output.epub)",
    )
    convert.add_argument(
        "--title", default=None,
        help="override the publication title (default: PDF metadata)",
    )
    convert.add_argument(
        "--author", default=None,
        help="override the author (default: PDF metadata)",
    )
    convert.add_argument(
        "--provider", default=None, choices=provider_choices,
        help="AI provider for complex pages (default: none / saved config)",
    )
    convert.add_argument(
        "--model", default=None,
        help="model id (default: saved config or the provider's first catalog model)",
    )
    convert.add_argument("--batch-size", type=int, default=4)
    convert.add_argument(
        "--cache-dir", default=None,
        help="LLM response cache directory (default: saved config or platform cache)",
    )
    convert.add_argument("--max-repair-attempts", type=int, default=2)
    convert.add_argument("--skip-validation", action="store_true")
    convert.add_argument(
        "--report-only", action="store_true",
        help="print the routing table and exit without converting",
    )
    convert.add_argument("--font-sample-pages", type=int, default=160)
    convert.add_argument(
        "--no-spool-images", action="store_true",
        help="keep extracted images in RAM instead of a temp directory",
    )
    convert.add_argument("--quiet", action="store_true")
    convert.add_argument(
        "--force", action="store_true",
        help="overwrite an existing output file",
    )
    convert.add_argument(
        "--max-tier2-pages", type=int, default=None,
        help="refuse to convert when more pages than this need the model",
    )

    doctor_parser = sub.add_parser("doctor", help="inspect the local environment")
    doctor_parser.add_argument(
        "--verify-credentials", action="store_true",
        help="contact the configured provider to verify the credential (network)",
    )
    sub.add_parser("validators", help="show the external validator states")
    return parser


def request_from_args(
    args: argparse.Namespace, *, registry, config: AppConfig
) -> ConversionRequest:
    """CLI namespace + config layering -> ConversionRequest (pure).

    Model resolution lives here (or an equivalent composition layer):
    provider -> registry -> first non-retired catalog model. A provider
    with an empty catalog resolves to ``None`` and fails later with a
    clean configuration error, never an indexing exception.
    """
    provider_id = args.provider or config.provider_name or "none"
    model = args.model or config.conversion_model
    if model is None and provider_id != "none":
        model = _first_catalog_model(registry, provider_id)
    return ConversionRequest(
        pdf_path=Path(args.pdf_path),
        output_path=Path(args.output),
        title=args.title,
        author=args.author,
        provider_id=provider_id,
        conversion_model=model,
        options=ConversionOptions(
            batch_size=args.batch_size,
            cache_dir=args.cache_dir,
            max_repair_attempts=args.max_repair_attempts,
            skip_validation=args.skip_validation,
            report_only=args.report_only,
            font_sample_pages=args.font_sample_pages,
            spool_images=not args.no_spool_images,
            quiet=args.quiet,
            overwrite=args.force,
            max_tier2_pages=args.max_tier2_pages,
        ),
    )


def _first_catalog_model(registry, provider_id: str) -> str | None:
    try:
        models = registry.get(provider_id).resolve_models()
    except KeyError:
        return None
    for model in models:
        if getattr(model, "status", "active") != "retired":
            return model.model_id
    return None


def _run_convert(args: argparse.Namespace, *, registry) -> int:
    config = ConfigManager().load()  # the service receives configuration,
    request = request_from_args(args, registry=registry, config=config)
    service = ConversionService(registry=registry, config=config)
    result = service.convert(request)

    if result.report_only and result.preflight is not None:
        print(format_routing_table(result.preflight.reports))
        if result.preflight.cost_advisory:
            print(result.preflight.cost_advisory)

    if not args.quiet:
        for warning in result.warnings:
            print(f"[WARNING] {warning}", file=sys.stderr)
    for error in result.all_errors:
        print(f"[ERROR] {error}", file=sys.stderr)
    return result.exit_code


def _run_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(
        registry=build_registry(),
        config_manager=ConfigManager(),
        verify_credentials=args.verify_credentials,
    )
    print(report.render())
    return 1 if report.failed else 0


def _run_validators(args: argparse.Namespace) -> int:
    config = ConfigManager().load()
    for validator in build_validator_registry().list():
        state = status_for(
            validator, enabled=validator_enabled(validator.id, config)
        )
        print(f"  {validator.display_name:<14} {state.value}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    registry = build_registry()
    parser = build_parser(sorted(a.provider_id for a in registry.list()))
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse errors, --version, --help
        return int(exc.code or 0)

    try:
        if args.command == "convert":
            return _run_convert(args, registry=registry)
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "validators":
            return _run_validators(args)
    except KeyboardInterrupt:
        # CLI-level guard only; token-based cooperative cancellation is
        # the REPL/session work of Phase 14.
        print("cancelled", file=sys.stderr)
        return 130
    return 2
