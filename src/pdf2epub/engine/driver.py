"""End-to-end conversion driver: PDF in, validated EPUB3 out.

This module is the engine's pipeline, not an entry point -- the product
CLIs (``pdf2epub`` and ``pdf2epub interactive``) drive it through
``application.ConversionService``.

Phases
------
  1  Document open + global font profiling
  2  Per-page triage (Module 2)
  3  Tier 1 heuristic extraction / Tier 2 AI extraction
  4  Timeline merge into one unified element stream
  5  Reassembly, chapter segmentation, EPUB3 packaging (Module 4)
  6  Validation gate + self-repair loop
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from collections import Counter
from dataclasses import replace
from html import escape, unescape
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

from . import confidence_router
from . import packaging_and_validation as packaging
from . import tier1_classifier
from . import tier2_llm_handler
from .confidence_router import PageConfidenceReport, RoutingTarget
from .packaging_and_validation import DualValidator, ValidationReport
from .tier1_classifier import ElementType, StreamElement
from .tier2_llm_handler import Tier2Handler, Tier2Request
from .cancellation import CancellationToken, PipelineCancelled
from .events import PipelineEvent

log = logging.getLogger("pdf2epub")

BLOCK_TAG_TYPES = {
    "h1": (ElementType.HEADING, 1),
    "h2": (ElementType.HEADING, 2),
    "h3": (ElementType.HEADING, 3),
    "h4": (ElementType.HEADING, 4),
    "h5": (ElementType.HEADING, 5),
    "h6": (ElementType.HEADING, 6),
    "p": (ElementType.PARAGRAPH, 0),
    "pre": (ElementType.CODE_BLOCK, 0),
    "small": (ElementType.SMALL_TEXT, 0),
}
PASSTHROUGH_BLOCKS = {
    "table", "blockquote", "aside", "ul", "ol", "dl", "figure", "section", "div", "hr"
}

# Tier-2 routing policy (which pages reach the model) lives in
# confidence_router.plan_tier2_routing -- one source shared with preflight.
MIN_REPAIR_TEXT_RETENTION = 0.60


# ---------------------------------------------------------------------------
# 1. Tier 2 XHTML -> StreamElement normaliser
# ---------------------------------------------------------------------------


def _inner_xhtml(element: Any) -> str:
    from lxml import etree

    # lxml parses entities into DECODED text; the stream content contract
    # is escaped inner XHTML. Serialised children re-escape themselves,
    # but the leading text node must be re-escaped explicitly or raw
    # angle brackets from code snippets (Popen(<your_command>, ...))
    # leak into chapter bodies and EPUBCheck rejects the file.
    parts = [escape(element.text or "", quote=False)]
    for child in element:
        parts.append(etree.tostring(child, encoding="unicode", method="xml"))
    return "".join(parts).strip()


def parse_xhtml_to_stream_elements(
    xhtml_page: str, page_index: int
) -> list[StreamElement]:
    """Turn a Tier 2 XHTML fragment back into stream primitives."""
    if not xhtml_page or not xhtml_page.strip():
        return []

    elements: list[StreamElement] = []
    try:
        from lxml import html as lhtml

        root = lhtml.fragment_fromstring(xhtml_page, create_parent="div")
        for idx, child in enumerate(root):
            # Comments and processing instructions carry a callable .tag in
            # lxml, not a string; serialising them raises.
            if not isinstance(child.tag, str):
                continue
            tag = child.tag.lower()
            inner = _inner_xhtml(child)
            if tag in BLOCK_TAG_TYPES:
                elem_type, level = BLOCK_TAG_TYPES[tag]
                out_tag = "p" if tag == "small" else tag
                css = "small" if tag == "small" else ""
                if not inner.strip():
                    continue
                elements.append(
                    StreamElement(
                        element_type=elem_type,
                        tag=out_tag,
                        content=inner,
                        page_num=page_index,
                        block_id=idx,
                        level=level,
                        css_class=css,
                    )
                )
            elif tag in PASSTHROUGH_BLOCKS:
                from lxml import etree

                whole = etree.tostring(child, encoding="unicode", method="xml").strip()
                m = re.match(r"^<\s*([a-zA-Z0-9]+)[^>]*>(.*)</\s*\1\s*>$", whole, re.DOTALL)
                inner_all = m.group(2) if m else inner
                # An empty table/ul/section is fixed-layout noise: drop it
                # (remediation Fix 13). <hr> is void by definition and is
                # an intentional separator -- it survives the emptiness
                # test on purpose.
                if tag != "hr" and not inner_all.strip():
                    continue
                elements.append(
                    StreamElement(
                        element_type=ElementType.BLOCK,
                        tag=tag,
                        content=inner_all,
                        page_num=page_index,
                        block_id=idx,
                    )
                )
            else:
                text = (child.text_content() or "").strip()
                if text:
                    # text_content() is lxml-decoded raw text; the stream
                    # contract requires escaped inner XHTML
                    elements.append(
                        StreamElement(
                            element_type=ElementType.PARAGRAPH,
                            tag="p",
                            content=escape(text, quote=False),
                            page_num=page_index,
                            block_id=idx,
                        )
                    )
    except Exception as exc:  # tolerant regex fallback
        log.warning("lxml normalisation failed on page %s (%s)", page_index + 1, exc)
        for idx, (tag, content) in enumerate(
            re.findall(r"<(p|h1|h2|h3|h4|pre|small)[^>]*>(.*?)</\1>", xhtml_page, re.DOTALL)
        ):
            if not content.strip():
                continue  # empty blocks never reach the stream (Fix 13)
            elem_type, level = BLOCK_TAG_TYPES.get(tag, (ElementType.PARAGRAPH, 0))
            elements.append(
                StreamElement(
                    element_type=elem_type,
                    tag="p" if tag == "small" else tag,
                    content=content.strip(),
                    page_num=page_index,
                    block_id=idx,
                    level=level,
                )
            )
    return elements


def _strip_unpacked_image_refs(xhtml: str, packaged_images: set[str]) -> str:
    """Remove model-generated image references that packaging cannot resolve."""
    from lxml import etree
    from lxml import html as lhtml

    root = lhtml.fragment_fromstring(xhtml, create_parent="div")
    for image in list(root.iter("img")):
        src = image.get("src", "")
        image_prefix = "../images/"
        filename = src[len(image_prefix) :] if src.startswith(image_prefix) else ""
        if filename and "/" not in filename and "\\" not in filename and filename in packaged_images:
            continue
        parent = image.getparent()
        if parent is None:
            continue
        parent.remove(image)
        if (
            isinstance(parent.tag, str)
            and parent.tag.lower() == "figure"
            and not "".join(parent.itertext()).strip()
            and not parent.xpath(".//img")
            and parent.getparent() is not None
        ):
            parent.getparent().remove(parent)
    return "".join(
        etree.tostring(child, encoding="unicode", method="xml") for child in root
    )


def _visible_word_counts(elements: list[StreamElement]) -> Counter[str]:
    text = " ".join(
        unescape(re.sub(r"<[^>]*>", " ", element.content))
        for element in elements
        if element.element_type is not ElementType.IMAGE
    )
    return Counter(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))


def _repair_preserves_content(
    original: list[StreamElement], candidate: list[StreamElement]
) -> bool:
    if not candidate:
        return False
    had_headings = any(e.element_type is ElementType.HEADING for e in original)
    has_headings = any(e.element_type is ElementType.HEADING for e in candidate)
    if had_headings and not has_headings:
        return False

    original_words = _visible_word_counts(original)
    total_words = sum(original_words.values())
    if not total_words:
        return bool(_visible_word_counts(candidate))
    candidate_words = _visible_word_counts(candidate)
    retained_words = sum((original_words & candidate_words).values())
    return retained_words / total_words >= MIN_REPAIR_TEXT_RETENTION


def _embed_visual_page(
    report: PageConfidenceReport, page: "fitz.Page", spool_dir: str | None
) -> list[StreamElement]:
    """Bypass Tier 2 OCR for a genuinely visual (no-text-layer) page.

    Builds the ImageElement/StreamElement directly rather than routing through
    Tier 2's XHTML path. A <figure> produced from parsed XHTML would
    reference a PNG that packaging never wrote into the zip - EPUBCheck
    rejects that as RSC-007. Constructing the element here guarantees the
    raster is registered with the same mechanism Tier 1's own
    extract_images() uses.
    """
    data = report.raster_bytes or confidence_router.render_page_raster(page)
    if not data:
        return []
    digest = hashlib.sha1(data).hexdigest()[:16]
    filename = f"page_{report.page_num:04d}_{digest[:8]}.png"
    img = tier1_classifier.ImageElement(
        ext="png",
        mime_type="image/png",
        bbox=(0.0, 0.0, float(page.rect.width), float(page.rect.height)),
        page_num=report.page_index,
        block_id=0,
        alt_text=f"Page {report.page_num} (image-only page, no text layer)",
        filename=filename,
    )
    if spool_dir:
        path = os.path.join(spool_dir, filename)
        if not os.path.exists(path):
            with open(path, "wb") as fh:
                fh.write(data)
        img.source_path = path
    else:
        img.image_bytes = data
    return [
        StreamElement(
            element_type=ElementType.IMAGE,
            tag="figure",
            content="",
            page_num=report.page_index,
            block_id=0,
            image_data=img,
        )
    ]


# ---------------------------------------------------------------------------
# 2. Pipeline
# ---------------------------------------------------------------------------


def format_routing_table(reports: Sequence[PageConfidenceReport]) -> str:
    """Pure per-page routing table shared by the legacy printer and the
    application layer's CLI/REPL formatters."""
    lines = [
        "  page | score | target        | sigma | order | columns | vectors | reason",
        "  -----+-------+---------------+-------+-------+---------+---------+-------------------",
    ]
    for r in reports:
        target = {
            RoutingTarget.TIER1_HEURISTIC: "tier1",
            RoutingTarget.TIER2_LLM_DIGEST: "tier2-digest",
            RoutingTarget.TIER2_VISION_OCR: "tier2-vision",
        }[r.target]
        lines.append(
            f"  {r.page_num:>4} | {r.score:>5} | {target:<13} | "
            f"{r.font_variance:>5.2f} | {r.order_violations:>5} | "
            f"{r.columnar_pairs:>7} | {r.vector_count:>7} | {','.join(r.reasons)}"
        )
    return "\n".join(lines)


def _print_routing_table(reports: list[PageConfidenceReport]) -> None:
    print("\n" + format_routing_table(reports))


def run_pipeline(
    pdf_path: str,
    output_epub: str,
    title: str = "Untitled Publication",
    author: str = "Unknown Author",
    llm_adapter: Callable | None = None,
    model_id: str = "gpt-4o",
    batch_size: int = 4,
    skip_validation: bool = False,
    max_repair_attempts: int = 2,
    cache_dir: str = ".cache_llm_epub",
    report_only: bool = False,
    verbose: bool = True,
    font_sample_pages: int = 160,
    spool_images: bool = True,
    validators: tuple[str, ...] | None = None,
    event_cb: Callable[[PipelineEvent], None] | None = None,
    cancel_token: CancellationToken | None = None,
    precomputed_reports: Sequence[PageConfidenceReport] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"success": False, "output": output_epub}
    started = time.monotonic()

    def say(msg: str) -> None:
        if verbose:
            print(msg)

    def progress(done: int, total: int, label: str) -> None:
        step = max(1, total // 20)
        if verbose and (done % step == 0 or done == total):
            pct = 100 * done / total
            say(f"            {label}: {done}/{total} ({pct:.0f}%)")

    total_pages: int | None = None

    def emit(
        event_type: str,
        phase: int,
        *,
        page_index: int | None = None,
        message: str = "",
        metadata: dict | None = None,
    ) -> None:
        if event_cb is None:
            return
        event = PipelineEvent(
            type=event_type,
            phase=phase,
            page_index=page_index,
            total_pages=total_pages,
            message=message,
            metadata=metadata or {},
        )
        try:
            event_cb(event)
        except Exception as exc:  # a UI bug must never abort a conversion
            log.warning(
                "event callback raised (%s); continuing", type(exc).__name__
            )

    def _check_cancel() -> None:
        if cancel_token is not None and cancel_token.cancelled:
            raise PipelineCancelled()

    # -- Phase 1/2 ---------------------------------------------------------
    say(f"\n[PHASE 1-2] Opening {pdf_path}")
    emit("phase_started", 2, message="opening document")
    doc = fitz.open(pdf_path)
    spool: tempfile.TemporaryDirectory | None = None
    try:
        _check_cancel()
        if doc.needs_pass:
            raise RuntimeError("PDF is password protected; decrypt it first.")
        total_pages = len(doc)
        if total_pages == 0:
            raise RuntimeError("PDF contains no pages.")

        meta = doc.metadata or {}
        if title == "Untitled Publication" and meta.get("title"):
            title = meta["title"].strip() or title
        if author == "Unknown Author" and meta.get("author"):
            author = meta["author"].strip() or author
        say(f"            '{title}' by {author} - {total_pages} page(s)")

        try:
            profile = tier1_classifier.DocumentFontProfile.build(
                doc, max_sample_pages=font_sample_pages
            )
            say(
                f"            baseline: {profile.main_font} "
                f"{profile.body_size}pt, line height {profile.line_height}pt "
                f"(sampled {profile.sampled_pages}/{total_pages} pages)"
            )
        except ValueError:
            # Fully scanned document: no text layer anywhere.
            profile = tier1_classifier.DocumentFontProfile(
                body_size=10.0, line_height=12.0, main_font="unknown"
            )
            say("            no text layer found - every page will go to vision/OCR")

        if title == "Untitled Publication":
            candidate = _first_page_title_candidate(doc, profile)
            if candidate:
                title = candidate
                say(f"            title from first-page heading: {title!r}")

        # -- Phase 3 -------------------------------------------------------
        say("\n[PHASE 3] Triage & routing")
        emit("phase_started", 3)
        if precomputed_reports is not None:
            reports = list(precomputed_reports)
            if len(reports) != total_pages:
                raise ValueError(
                    f"precomputed_reports has {len(reports)} pages but the "
                    f"document has {total_pages}"
                )
        else:

            def _triage_progress(done: int, total: int) -> None:
                _check_cancel()
                progress(done, total, "triage")
                emit("page_progress", 3, page_index=done - 1)

            reports = confidence_router.route_document(
                doc, progress=_triage_progress
            )
        summary = confidence_router.summarise(reports)
        say(
            f"            tier1={summary['tier1']}  "
            f"tier2-digest={summary['tier2_digest']}  "
            f"tier2-vision={summary['tier2_vision']}"
        )
        result["routing"] = summary
        result["reports"] = reports

        if report_only:
            _print_routing_table(reports)
            emit("completed", 7, message="report only", metadata={"report_only": True})
            result["success"] = True
            return result

        page_heights = {i: float(doc[i].rect.height) for i in range(total_pages)}

        # -- Phase 4 -------------------------------------------------------
        page_elements: dict[int, list[StreamElement]] = {}
        tier1_indices = [r.page_index for r in reports if r.is_tier1]
        tier2_reports = [r for r in reports if not r.is_tier1]

        if spool_images:
            spool = tempfile.TemporaryDirectory(prefix="pdf2epub_img_")
        spool_dir = spool.name if spool else None

        if tier1_indices:
            say(f"\n[PHASE 4A] Tier 1 deterministic engine ({len(tier1_indices)} pages)")
            emit("phase_started", 4, message="tier1")
            for n, idx in enumerate(tier1_indices, start=1):
                _check_cancel()
                page_elements[idx] = tier1_classifier.build_page_stream(
                    doc[idx], profile, idx, spool_dir
                )
                progress(n, len(tier1_indices), "tier1")
                emit("page_progress", 4, page_index=idx, metadata={"label": "tier1"})

        handler = Tier2Handler(
            llm_client_fn=llm_adapter, model_id=model_id, cache_dir=cache_dir
        )
        tier2_requests: dict[int, Tier2Request] = {}

        if tier2_reports:
            say(f"\n[PHASE 4B] Tier 2 AI engine ({len(tier2_reports)} pages)")
            emit("phase_started", 4, message="tier2")

            # The routing decision lives in confidence_router so the engine
            # and the application preflight cannot drift apart.
            is_online = llm_adapter is not None
            plan = confidence_router.plan_tier2_routing(
                reports, total_pages, is_online
            )

            for r in plan.bypass:
                confidence_router.attach_payload(doc[r.page_index], r)
                page_elements[r.page_index] = _embed_visual_page(
                    r, doc[r.page_index], spool_dir
                )
                confidence_router.release_payload(r)
            llm_reports = list(plan.handler)
            bypassed = plan.bypassed_vision
            if bypassed:
                say(f"            {bypassed} visual page(s) embedded directly (no OCR)")
            result["tier2_bypassed"] = bypassed

            for r in llm_reports:
                tier2_requests[r.page_index] = Tier2Request(
                    page_num=r.page_num,
                    layout_digest=r.layout_digest,
                    raster_bytes=r.raster_bytes,
                    page_width=float(doc[r.page_index].rect.width),
                    vision=r.target is RoutingTarget.TIER2_VISION_OCR,
                )
            for start in range(0, len(llm_reports), batch_size):
                _check_cancel()
                window = llm_reports[start : start + batch_size]
                emit(
                    "tier2_batch_started",
                    4,
                    metadata={"start": start, "count": len(window)},
                )
                # Build payloads only for this window, then drop them. Holding
                # every raster for a 500 page scan is what kills the process.
                batch = []
                for rep in window:
                    confidence_router.attach_payload(doc[rep.page_index], rep)
                    req = tier2_requests[rep.page_index]
                    req.layout_digest = rep.layout_digest
                    req.raster_bytes = rep.raster_bytes
                    batch.append(req)

                outputs = handler.process_batch(batch)
                if len(outputs) != len(batch):  # belt and braces
                    outputs = list(outputs) + [""] * (len(batch) - len(outputs))
                for req, xhtml in zip(batch, outputs):
                    idx = req.page_num - 1
                    elems = parse_xhtml_to_stream_elements(xhtml, idx)
                    if not req.is_vision:
                        # build_layout_digest() skips image blocks entirely, so
                        # a diagram in the corner of an otherwise-complex text
                        # page would silently vanish without this. Skipped for
                        # vision requests: there the raster *is* the whole
                        # page, so re-attaching it would duplicate content the
                        # model already transcribed.
                        elems.extend(
                            tier1_classifier.extract_images(doc[idx], idx, [], spool_dir)
                        )
                    page_elements[idx] = elems
                    req.raster_bytes = None
                    req.layout_digest = None
                for rep in window:
                    confidence_router.release_payload(rep)
                progress(
                    min(start + batch_size, len(llm_reports)),
                    len(llm_reports),
                    "tier2",
                )
                emit(
                    "page_progress",
                    4,
                    page_index=window[-1].page_index,
                    metadata={"label": "tier2"},
                )
            result["tier2_stats"] = dict(handler.stats)

        # -- Phase 5 -------------------------------------------------------
        say("\n[PHASE 5] Merging unified document stream")
        emit("phase_started", 5)
        unified: list[StreamElement] = []
        for idx in range(total_pages):
            unified.extend(page_elements.get(idx, []))
        say(f"            {len(unified)} stream elements")
        result["element_count"] = len(unified)

        if not unified:
            raise RuntimeError(
                "No content extracted. The PDF may be a pure scan with no OCR "
                "model configured - set an API key and re-run."
            )

        # -- Phase 6 -------------------------------------------------------
        say("\n[PHASE 6] Packaging EPUB3")
        emit("phase_started", 6)
        build = packaging.build_epub_publication(
            stream=unified,
            output_path=output_epub,
            title=title,
            author=author,
            page_heights=page_heights,
        )
        say(
            f"            {len(build.chapters)} chapter(s), "
            f"{build.welded_pairs} cross-page weld(s), "
            f"{len(build.stripped_furniture)} furniture line(s) stripped"
        )
        say(
            f"            a11y: headings={build.a11y.heading_count} "
            f"images={build.a11y.image_count} "
            f"alt_text={'yes' if build.a11y.has_alt_text else 'n/a'}"
        )
        m = build.metrics
        say(
            f"            structure: lists={m.lists} items={m.list_items} "
            f"tables={m.tables} links={m.links} code={m.code_blocks} | "
            f"nav={m.nav_entries} unresolved={m.unresolved_nav_targets} "
            f"empty_paragraphs={m.empty_paragraphs}"
        )
        result["build"] = build
        result["chapters"] = len(build.chapters)

        # -- Phase 7 -------------------------------------------------------
        if skip_validation:
            say("\n[PHASE 7] Validation skipped")
            emit("completed", 7, message="validation skipped", metadata={"skipped": True})
            result["success"] = True
            return result

        say("\n[PHASE 7] Validation gate")
        emit("validation_started", 7)
        validator = DualValidator()

        def _validate(path: str) -> ValidationReport:
            # default None keeps the original call signature exactly, so
            # existing monkeypatched validators keep working unchanged
            if validators is None:
                return validator.validate(path)
            return validator.validate(path, enabled=validators)

        report = _validate(output_epub)

        for attempt in range(1, max_repair_attempts + 1):
            _print_validation(report, attempt, say)
            if report.passed:
                break
            _check_cancel()
            say(f"            self-repair pass {attempt}/{max_repair_attempts}")
            emit("repair_started", 7, metadata={"attempt": attempt})
            unified = _repair_stream(
                unified,
                report,
                handler,
                tier2_requests,
                say,
                doc=doc,
                page_reports={r.page_index: r for r in reports},
            )
            build = packaging.build_epub_publication(
                stream=unified,
                output_path=output_epub,
                title=title,
                author=author,
                page_heights=page_heights,
            )
            result["build"] = build
            report = _validate(output_epub)
        else:
            _print_validation(report, max_repair_attempts + 1, say)

        result["validation"] = report
        result["success"] = report.passed
        if not report.passed:
            say("\n[WARNING] Validation still failing after repair attempts.")
            say(report.raw_logs[:4000])
            emit("failed", 7, message="validation failed")
        else:
            say(f"\n[SUCCESS] {output_epub}  ({time.monotonic() - started:.1f}s)")
            emit("completed", 7, message="success")
        return result
    except PipelineCancelled:
        result["cancelled"] = True
        result["success"] = False
        emit("cancelled", 0, message="conversion cancelled")
        return result
    finally:
        if spool is not None:
            try:
                spool.cleanup()
            except OSError:  # pragma: no cover
                pass
        doc.close()


def _first_page_title_candidate(doc, profile) -> str | None:
    """The document's opening heading on page one, or None (Phase L).

    Tier three of the title chain (explicit -> embedded metadata ->
    this -> the sentinel): a PDF without an embedded title usually
    names itself in its first heading. Deliberately conservative --

    * furniture-scale text above the heading is ignored, but body text
      above it disqualifies: that heading names a section, not the
      publication;
    * a heading crammed into the top 8% of the page is a running
      header, not a title;
    * a 120-character cap has the final word. Titles that wrap are
      already one classified line (same-block heading lines merge
      upstream), so the candidate is the first heading alone: joining
      what cannot be told apart from the next section heading is how
      "Artificial Intelligence Minor Project" happens.

    The heading stays in the content stream untouched: a title is
    metadata, never an instruction to re-tag an h1.
    """
    try:
        lines = tier1_classifier.classify_page(doc[0], profile)
    except Exception:
        return None
    if not lines:
        return None
    page_height = float(doc[0].rect.height or 0.0)

    def _plain(line) -> str:
        # Content is escaped XHTML: unescape exactly once, because
        # book.set_title() hands the string to ebooklib, which escapes
        # again at serialisation (remediation Fix 12).
        return re.sub(r"\s+", " ", unescape(packaging.strip_tags(line.text))).strip()

    seen_body = False
    for ln in lines:
        text = _plain(ln)
        if not text:
            continue
        if ln.tag == "small":
            continue  # furniture-scale text is never a title candidate
        if not ln.tag.startswith("h"):
            seen_body = True
            continue
        # the first heading decides, for better or worse
        if seen_body:
            return None
        if page_height and (ln.bbox[1] / page_height) < 0.08:
            return None
        return text if 0 < len(text) <= 120 else None
    return None


def _print_validation(report: ValidationReport, attempt: int, say: Callable) -> None:
    def status(name: str, passed: bool, available: bool) -> str:
        # A tool that never ran cannot pass: absence and disablement are
        # honest skips, not verdicts. The report's own *_passed/*_available
        # fields and the exit semantics are unchanged by this rendering.
        if name in report.disabled:
            return "SKIPPED (disabled)"
        if not available:
            return "SKIPPED (not installed)"
        return "PASS" if passed else "FAIL"

    say(f"\n            --- validation attempt {attempt} ---")
    say(
        f"            structural : {'PASS' if report.structural_passed else 'FAIL'} "
        f"({len([e for e in report.structural_errors if e['severity'] in ('ERROR','FATAL')])} errors)"
    )
    say(
        f"            epubcheck  : "
        f"{status('epubcheck', report.epubcheck_passed, report.epubcheck_available)}"
        f" errors={report.epubcheck_errors}"
    )
    say(
        f"            daisy ace  : "
        f"{status('ace', report.ace_passed, report.ace_available)}"
        f" {report.ace_violations or ''}"
    )


def _repair_stream(
    unified: list[StreamElement],
    report: ValidationReport,
    handler: Tier2Handler,
    tier2_requests: dict[int, Tier2Request],
    say: Callable,
    doc: Any = None,
    page_reports: dict[int, PageConfidenceReport] | None = None,
) -> list[StreamElement]:
    """Re-sanitise the stream and safely replace only affected Tier 2 pages."""
    repaired = [
        replace(e, content=tier2_llm_handler.sanitize_and_validate_xhtml(e.content))
        if e.element_type is not ElementType.IMAGE
        else e
        for e in unified
    ]

    failing_chapters: set[int] = set()
    for err in report.structural_errors:
        match = re.search(r"chapter_(\d+)", err.get("file", ""))
        if match:
            failing_chapters.add(int(match.group(1)))

    chapters = packaging.segment_chapters(repaired)
    failing_pages = {
        element.page_num
        for chapter_num in failing_chapters
        if 1 <= chapter_num <= len(chapters)
        for element in chapters[chapter_num - 1][1]
        if element.page_num in tier2_requests
    }

    if not failing_pages or handler.llm_client_fn is None:
        return repaired

    say(f"            re-prompting Tier 2 pages: {sorted(p + 1 for p in failing_pages)}")
    packaged_images = {
        element.image_data.filename
        for element in repaired
        if element.element_type is ElementType.IMAGE and element.image_data is not None
    }
    replacements: dict[int, list[StreamElement]] = {}
    page_reports = page_reports or {}

    for page_idx in sorted(failing_pages):
        req = tier2_requests.get(page_idx)
        if req is None:
            continue
        page_report = page_reports.get(page_idx)
        try:
            if doc is not None and page_report is not None:
                confidence_router.attach_payload(doc[page_idx], page_report)
                req.layout_digest = page_report.layout_digest
                req.raster_bytes = page_report.raster_bytes

            fixed = handler.repair_page(req, report.raw_logs)
            fixed = _strip_unpacked_image_refs(fixed, packaged_images)
            if not fixed.strip() or not tier2_llm_handler.is_well_formed(fixed)[0]:
                say(f"            keeping original page {page_idx + 1}: empty/invalid repair")
                continue

            new_elems = parse_xhtml_to_stream_elements(fixed, page_idx)
            original_text = [
                element
                for element in repaired
                if element.page_num == page_idx and element.element_type is not ElementType.IMAGE
            ]
            if not _repair_preserves_content(original_text, new_elems):
                say(f"            keeping original page {page_idx + 1}: repair lost content")
                continue

            page_images = [
                element
                for element in repaired
                if element.page_num == page_idx and element.element_type is ElementType.IMAGE
            ]
            replacements[page_idx] = new_elems + page_images
        except Exception as exc:
            say(f"            keeping original page {page_idx + 1}: repair failed ({exc})")
        finally:
            req.layout_digest = None
            req.raster_bytes = None
            if page_report is not None:
                confidence_router.release_payload(page_report)

    if not replacements:
        return repaired

    rebuilt: list[StreamElement] = []
    inserted_pages: set[int] = set()
    for element in repaired:
        replacement = replacements.get(element.page_num)
        if replacement is None:
            rebuilt.append(element)
        elif element.page_num not in inserted_pages:
            rebuilt.extend(replacement)
            inserted_pages.add(element.page_num)
    return rebuilt
