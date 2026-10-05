"""Level 2 preflight: opens the PDF, routes it, checks model capabilities.

This is the only level that touches the document. Capability checking runs
online only and always before any API spend. Payloads are never built
(``build_payloads=False``), so preflight holds zero raster/digest bytes on
any document size; the resulting payload-free reports feed the Phase 8
``precomputed_reports`` seam so routing happens once end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - legacy alias
    import fitz

from ..engine import confidence_router
from ..providers.requirements import check_model_for_routes, resolve_model
from .models import ConversionRequest


@dataclass(frozen=True)
class PreflightResult:
    total_pages: int
    routing_summary: dict[str, int]
    required_routes: frozenset[str]
    bypassed_vision: int
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cost_advisory: str = ""
    reports: tuple = ()  # payload-free; feeds Phase 8 S5

    @property
    def ok(self) -> bool:
        return not self.problems


def _failure(message: str) -> PreflightResult:
    return PreflightResult(0, {}, frozenset(), 0, problems=[message])


def preflight(request: ConversionRequest, *, registry) -> PreflightResult:
    """Route the document and verify the selected model can handle it."""
    try:
        doc = fitz.open(str(request.pdf_path))
    except Exception as exc:
        return _failure(f"cannot open PDF: {exc}")
    try:
        if doc.needs_pass:
            return _failure("PDF is password protected; decrypt it first.")
        total_pages = len(doc)
        if total_pages == 0:
            return _failure("PDF contains no pages.")

        reports = confidence_router.route_document(doc, build_payloads=False)
        summary = confidence_router.summarise(reports)
        online = request.provider_id != "none"
        plan = confidence_router.plan_tier2_routing(reports, total_pages, online)

        problems: list[str] = []
        warnings: list[str] = []
        if online and request.conversion_model:
            try:
                adapter = registry.get(request.provider_id)
            except KeyError:
                adapter = None
            if adapter is not None:
                resolution = resolve_model(adapter, request.conversion_model)
                if resolution.warning:
                    warnings.append(resolution.warning)
                if resolution.definition is not None:
                    problems.extend(
                        check_model_for_routes(
                            resolution.definition, plan.required_routes
                        )
                    )

        tier2 = summary["tier2_digest"] + summary["tier2_vision"]
        cost = (
            f"~{tier2} Tier-2 page(s) "
            f"({summary['tier2_digest']} digest, {summary['tier2_vision']} vision)"
        )
        return PreflightResult(
            total_pages=total_pages,
            routing_summary=summary,
            required_routes=plan.required_routes,
            bypassed_vision=plan.bypassed_vision,
            problems=problems,
            warnings=warnings,
            cost_advisory=cost,
            reports=tuple(reports),
        )
    finally:
        doc.close()
