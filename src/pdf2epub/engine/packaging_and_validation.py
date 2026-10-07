"""
Module 4: Assembly, Packaging & Self-Repair Validation
======================================================

Turns the unified element stream into a reflowable EPUB3 publication.

* Strips running headers/footers by position + frequency, and kills orphan
  page numbers outright.
* Welds paragraphs severed by page seams (hyphen-aware).
* Segments chapters at logical heading nodes, not page boundaries.
* Asserts accessibility metadata only for features the output actually has.
* Parses EPUBCheck / Ace logs with correct severity keys, and ships an
  internal structural validator so the pipeline still has a quality signal
  when the external CLIs are not installed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from html import escape
from pathlib import Path

from ebooklib import epub

log = logging.getLogger("packaging")

from .tier1_classifier import ElementType, StreamElement, strip_tags

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

FURNITURE_FREQUENCY = 0.60      # appears on >60% of pages
FURNITURE_MAX_CHARS = 90
FURNITURE_BAND = 0.12           # top/bottom 12% of the page
MIN_PAGES_FOR_FURNITURE = 4     # below this, "every page" means nothing
MIN_PAGES_SEEN = 3              # and it must actually repeat
TERMINAL_PUNCT = ".!?:;\u2026\"'\u201d\u2019)"
CONFORMS_TO = "EPUB Accessibility 1.1 - WCAG 2.0 Level AA"

PAGE_NUMBER_RE = re.compile(r"^[\[\(]?\s*(?:\d{1,4}|[ivxlcdmIVXLCDM]{1,7})\s*[\]\)]?$")
HYPHEN_TAIL_RE = re.compile(r"(\w)-((?:</\w+>)*)\s*$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AccessibilityProfile:
    has_alt_text: bool = False
    has_structural_navigation: bool = False
    has_table_of_contents: bool = False
    has_reading_order: bool = True
    has_tables: bool = False
    image_count: int = 0
    heading_count: int = 0
    hazards: list[str] = field(default_factory=lambda: ["none"])
    access_modes: list[str] = field(default_factory=lambda: ["textual"])
    summary: str = ""

    def build_summary(self) -> str:
        bits = ["Reflowable text publication produced by automated PDF conversion."]
        if self.has_structural_navigation:
            bits.append("Headings provide structural navigation.")
        if self.image_count and self.has_alt_text:
            bits.append("All images carry alternative text.")
        elif self.image_count:
            bits.append("Some images lack alternative text.")
        else:
            bits.append("The publication contains no images.")
        return " ".join(bits)


@dataclass
class ChapterRecord:
    file_name: str
    title: str
    page_nums: set[int]
    element_indices: list[int]


@dataclass
class PublicationBuild:
    output_path: str
    a11y: AccessibilityProfile
    chapters: list[ChapterRecord]
    clean_stream: list[StreamElement]
    stripped_furniture: list[str]
    welded_pairs: int


@dataclass
class ValidationReport:
    epubcheck_passed: bool
    epubcheck_errors: int
    epubcheck_available: bool
    ace_passed: bool
    ace_violations: dict[str, int]
    ace_available: bool
    structural_passed: bool
    structural_errors: list[dict]
    raw_logs: str
    disabled: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.structural_passed and self.epubcheck_passed and self.ace_passed

    @property
    def summary_log(self) -> str:  # alias kept for driver compatibility
        return self.raw_logs

    def failing_files(self) -> set[str]:
        files = {e["file"] for e in self.structural_errors if e.get("file")}
        for match in re.finditer(r"([\w./-]+\.xhtml)", self.raw_logs):
            files.add(Path(match.group(1)).name)
        return files


# ---------------------------------------------------------------------------
# 1. Stream reassembly
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(text)).strip().lower()


def detect_running_furniture(
    elements: list[StreamElement], page_heights: dict[int, float] | None = None
) -> set[str]:
    """Text that repeats at the top/bottom of most pages is furniture.

    Two guards keep this from eating real content:

    * Real page geometry is required. Inferring page height from the extent of
      the extracted content puts the last paragraph of every page inside the
      "bottom band" by construction.
    * A short document has no meaningful frequency. On a two page PDF a single
      occurrence is 50% and on a one page PDF it is 100%, so a lone sentence
      near the foot of the page would be deleted as a running footer.
    """
    if not elements or not page_heights:
        return set()

    pages = {e.page_num for e in elements}
    total_pages = max(len(pages), 1)
    if total_pages < MIN_PAGES_FOR_FURNITURE:
        return set()

    seen: dict[str, set[int]] = defaultdict(set)
    for e in elements:
        if e.bbox == (0.0, 0.0, 0.0, 0.0):
            continue  # Tier 2 nodes carry synthetic bboxes; position is unknown
        plain = _normalise(e.content)
        if not plain or len(plain) > FURNITURE_MAX_CHARS:
            continue
        height = page_heights.get(e.page_num) or 0.0
        if height <= 0:
            continue
        top = e.bbox[1] / height
        bottom = e.bbox[3] / height
        if top <= FURNITURE_BAND or bottom >= (1.0 - FURNITURE_BAND):
            seen[plain].add(e.page_num)

    return {
        text
        for text, page_set in seen.items()
        if len(page_set) >= MIN_PAGES_SEEN
        and len(page_set) / total_pages > FURNITURE_FREQUENCY
    }


def _is_orphan_page_number(
    element: StreamElement, page_heights: dict[int, float]
) -> bool:
    plain = strip_tags(element.content).strip()
    if not plain or not PAGE_NUMBER_RE.match(plain):
        return False
    if element.bbox == (0.0, 0.0, 0.0, 0.0):
        return False  # no spatial evidence that this is furniture
    height = page_heights.get(element.page_num) or 0.0
    if height <= 0:
        return False  # without geometry, keep it: deleting content is worse
    top = element.bbox[1] / height
    bottom = element.bbox[3] / height
    return top <= FURNITURE_BAND or bottom >= (1.0 - FURNITURE_BAND)


def _should_weld(prev: StreamElement, nxt: StreamElement) -> bool:
    if prev.element_type is not ElementType.PARAGRAPH:
        return False
    if nxt.element_type is not ElementType.PARAGRAPH:
        return False
    if prev.page_num == nxt.page_num:
        return False
    prev_text = strip_tags(prev.content).rstrip()
    next_text = strip_tags(nxt.content).lstrip()
    if not prev_text or not next_text:
        return False
    if prev_text.endswith("-"):
        return True
    if prev_text[-1] in TERMINAL_PUNCT:
        return False
    return next_text[0].islower()


def _weld(prev: StreamElement, nxt: StreamElement) -> StreamElement:
    first = prev.content.rstrip()
    prev_plain = strip_tags(first).rstrip()
    if prev_plain.endswith("-") and HYPHEN_TAIL_RE.search(first):
        m = HYPHEN_TAIL_RE.search(first)
        assert m is not None
        first = HYPHEN_TAIL_RE.sub(lambda _m: m.group(1) + m.group(2), first)
        joined = first + nxt.content.lstrip()
    else:
        joined = first + " " + nxt.content.lstrip()
    return replace(prev, content=joined)


def _merge_split_headings(elements: list[StreamElement]) -> list[StreamElement]:
    out: list[StreamElement] = []
    for e in elements:
        if (
            out
            and e.element_type is ElementType.HEADING
            and out[-1].element_type is ElementType.HEADING
            and out[-1].level == e.level
            and out[-1].page_num == e.page_num
            and out[-1].block_id == e.block_id
        ):
            out[-1] = replace(out[-1], content=out[-1].content.rstrip() + " " + e.content.lstrip())
            continue
        out.append(e)
    return out


def process_element_stream(
    elements: list[StreamElement], page_heights: dict[int, float] | None = None
) -> tuple[list[StreamElement], list[str], int]:
    """Return (clean_stream, stripped_furniture_texts, welded_pair_count)."""
    if not elements:
        return [], [], 0

    page_heights = page_heights or {}
    furniture = detect_running_furniture(elements, page_heights)

    filtered = [
        e
        for e in elements
        if _normalise(e.content) not in furniture
        and not (
            e.element_type in (ElementType.PARAGRAPH, ElementType.SMALL_TEXT)
            and _is_orphan_page_number(e, page_heights)
        )
    ]

    filtered = _merge_split_headings(filtered)

    welded: list[StreamElement] = []
    welds = 0
    for e in filtered:
        if welded and _should_weld(welded[-1], e):
            welded[-1] = _weld(welded[-1], e)
            welds += 1
            continue
        welded.append(e)

    return welded, sorted(furniture), welds


# ---------------------------------------------------------------------------
# 2. Chapter segmentation
# ---------------------------------------------------------------------------


def choose_split_level(elements: list[StreamElement]) -> int:
    levels = sorted(
        {e.level for e in elements if e.element_type is ElementType.HEADING and e.level}
    )
    if not levels:
        return 0
    return levels[0]


def segment_chapters(
    elements: list[StreamElement],
) -> list[tuple[str, list[StreamElement]]]:
    """Split at the shallowest heading level present. Returns (title, elements)."""
    split_level = choose_split_level(elements)
    chapters: list[tuple[str, list[StreamElement]]] = []
    current: list[StreamElement] = []
    current_title = "Front Matter"

    for e in elements:
        starts_chapter = (
            split_level
            and e.element_type is ElementType.HEADING
            and e.level == split_level
        )
        if starts_chapter and current:
            chapters.append((current_title, current))
            current = []
            current_title = strip_tags(e.content).strip() or "Untitled"
        elif starts_chapter:
            current_title = strip_tags(e.content).strip() or "Untitled"
        current.append(e)

    if current:
        chapters.append((current_title, current))
    if not chapters:
        chapters = [("Content", [])]
    return chapters


def assign_anchor_ids(elements: list[StreamElement]) -> None:
    counter = 0
    for e in elements:
        if e.element_type is ElementType.HEADING:
            counter += 1
            if not e.anchor_id:
                e.anchor_id = f"sec{counter}"


# ---------------------------------------------------------------------------
# 3. EPUB assembly
# ---------------------------------------------------------------------------

DEFAULT_CSS = """
html, body { margin: 0; padding: 0; }
body { font-family: serif; line-height: 1.5; padding: 1em; }
h1, h2, h3, h4 { font-family: sans-serif; line-height: 1.25; margin: 1.2em 0 0.4em; }
h1 { font-size: 1.6em; }
h2 { font-size: 1.35em; }
h3 { font-size: 1.15em; }
p { margin: 0; text-indent: 1.2em; }
h1 + p, h2 + p, h3 + p, h4 + p, figure + p, pre + p { text-indent: 0; }
p.small { font-size: 0.85em; text-indent: 0; color: #444; }
pre { background: #f4f4f4; padding: 0.8em; overflow-x: auto; white-space: pre-wrap;
      font-family: monospace; font-size: 0.9em; }
code { font-family: monospace; }
.tbl { max-width: 100%; overflow-x: auto; }
figure { margin: 1em 0; text-align: center; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: 0.85em; color: #555; }
table { border-collapse: collapse; margin: 1em 0; width: 100%; }
th, td { border: 1px solid #999; padding: 0.3em 0.5em; text-align: left; }
blockquote { margin: 1em 2em; font-style: italic; }
"""

# ebooklib builds the <html>/<head>/<body> scaffold itself and sets lang,
# title and stylesheet links from the item. Handing it a full document with an
# XML declaration makes its internal lxml parse raise, which ebooklib swallows
# and turns into an EMPTY chapter - a silent, total content loss. Only body
# level markup is passed in.
CHAPTER_TEMPLATE = "<body>\n{body}\n</body>"


def _prepare_chapter_body(elements: list[StreamElement]) -> str:
    body = "\n".join(element.render() for element in elements) or "<p></p>"
    try:
        ET.fromstring(f"<root>{body}</root>")
        return body
    except ET.ParseError:
        from .tier2_llm_handler import sanitize_and_validate_xhtml

        recovered = sanitize_and_validate_xhtml(body)
        if elements and not recovered.strip():
            raise ValueError("XHTML sanitization emptied a non-empty chapter")
        try:
            ET.fromstring(f"<root>{recovered}</root>")
        except ET.ParseError as exc:
            raise ValueError(f"chapter body is not well-formed XHTML: {exc}") from exc
        return recovered


def relative_href(from_file: str, to_file: str) -> str:
    """Path of ``to_file`` as seen from ``from_file``.

    ebooklib's ``EpubHtml.add_item`` inserts the stylesheet's raw name with no
    relative-path computation, so any chapter that does not sit at the package
    root ends up with a dangling <link>. EPUBCheck reports this as RSC-007.
    """
    import posixpath

    base = posixpath.dirname(from_file)
    if not base:
        return to_file
    return posixpath.relpath(to_file, base)


def attach_stylesheet(item: epub.EpubHtml, css_item: epub.EpubItem) -> None:
    item.add_link(
        href=relative_href(item.file_name, css_item.file_name),
        rel="stylesheet",
        type="text/css",
    )


def analyse_accessibility(elements: list[StreamElement]) -> AccessibilityProfile:
    images = [e for e in elements if e.element_type is ElementType.IMAGE]
    headings = [e for e in elements if e.element_type is ElementType.HEADING]
    all_alt = bool(images) and all(
        e.image_data is not None and e.image_data.alt_text.strip() for e in images
    )
    has_tables = any(e.tag.lower() == "table" for e in elements)
    split_level = choose_split_level(elements)
    has_table_of_contents = bool(
        split_level
        and any(e.element_type is ElementType.HEADING and e.level == split_level for e in headings)
    )

    profile = AccessibilityProfile(
        has_alt_text=all_alt,
        has_structural_navigation=bool(headings),
        has_table_of_contents=has_table_of_contents,
        has_reading_order=True,
        has_tables=has_tables,
        image_count=len(images),
        heading_count=len(headings),
        access_modes=["textual", "visual"] if images else ["textual"],
    )
    profile.summary = profile.build_summary()
    return profile


def _inject_metadata(book: epub.EpubBook, a11y: AccessibilityProfile) -> None:
    book.add_metadata(None, "meta", CONFORMS_TO, {"property": "dcterms:conformsTo"})
    for mode in a11y.access_modes:
        book.add_metadata(None, "meta", mode, {"property": "schema:accessMode"})
    book.add_metadata(None, "meta", "textual", {"property": "schema:accessModeSufficient"})

    # Only assert what the emitted tree actually contains.
    if a11y.has_structural_navigation:
        book.add_metadata(
            None, "meta", "structuralNavigation", {"property": "schema:accessibilityFeature"}
        )
    if a11y.has_alt_text:
        book.add_metadata(
            None, "meta", "alternativeText", {"property": "schema:accessibilityFeature"}
        )
    if a11y.has_table_of_contents:
        book.add_metadata(
            None, "meta", "tableOfContents", {"property": "schema:accessibilityFeature"}
        )
    if a11y.has_reading_order:
        book.add_metadata(
            None, "meta", "readingOrder", {"property": "schema:accessibilityFeature"}
        )
    for hazard in a11y.hazards:
        book.add_metadata(None, "meta", hazard, {"property": "schema:accessibilityHazard"})
    book.add_metadata(
        None, "meta", a11y.summary, {"property": "schema:accessibilitySummary"}
    )


def build_epub_publication(
    stream: list[StreamElement],
    output_path: str,
    title: str = "Untitled Publication",
    author: str = "Unknown Author",
    language: str = "en",
    page_heights: dict[int, float] | None = None,
    preprocess: bool = True,
) -> PublicationBuild:
    if preprocess:
        clean_stream, furniture, welds = process_element_stream(stream, page_heights)
    else:
        clean_stream, furniture, welds = list(stream), [], 0

    assign_anchor_ids(clean_stream)
    a11y = analyse_accessibility(clean_stream)

    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)
    _inject_metadata(book, a11y)

    css_item = epub.EpubItem(
        uid="style_main",
        file_name="styles/stylesheet.css",
        media_type="text/css",
        content=DEFAULT_CSS,
    )
    book.add_item(css_item)

    # Images -------------------------------------------------------------
    seen_images: set[str] = set()
    for e in clean_stream:
        if e.element_type is not ElementType.IMAGE or e.image_data is None:
            continue
        img = e.image_data
        if img.filename in seen_images:
            continue  # content-hash filenames make repeated art a single item
        payload = img.load_bytes()
        if not payload:
            log.warning("image %s has no data; skipping", img.filename)
            continue
        seen_images.add(img.filename)
        book.add_item(
            epub.EpubImage(
                uid=f"img_{len(seen_images)}",
                file_name=f"images/{img.filename}",
                media_type=img.mime_type,
                content=payload,
            )
        )

    # Chapters -----------------------------------------------------------
    split_level = choose_split_level(clean_stream)
    segments = segment_chapters(clean_stream)
    chapters: list[epub.EpubHtml] = []
    records: list[ChapterRecord] = []
    toc: list = []

    for idx, (chap_title, elements) in enumerate(segments, start=1):
        file_name = f"XHTML/chapter_{idx:03d}.xhtml"
        body = _prepare_chapter_body(elements)
        chap = epub.EpubHtml(
            title=chap_title,
            file_name=file_name,
            lang=language,
            uid=f"chapter_{idx:03d}",
        )
        chap.set_content(CHAPTER_TEMPLATE.format(body=body))
        attach_stylesheet(chap, css_item)
        book.add_item(chap)
        chapters.append(chap)

        records.append(
            ChapterRecord(
                file_name=Path(file_name).name,
                title=chap_title,
                page_nums={e.page_num for e in elements},
                element_indices=[],
            )
        )

        sub_links = [
            epub.Link(
                f"{file_name}#{e.anchor_id}",
                strip_tags(e.content).strip() or "Section",
                f"{chap.id}_{e.anchor_id}",
            )
            for e in elements
            if e.element_type is ElementType.HEADING
            and split_level
            and e.level == split_level + 1
            and e.anchor_id
        ]
        if sub_links:
            toc.append((epub.Section(chap_title, href=file_name), tuple(sub_links)))
        else:
            toc.append(epub.Link(file_name, chap_title, chap.id))

    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    nav = epub.EpubNav()
    attach_stylesheet(nav, css_item)
    book.add_item(nav)
    book.spine = ["nav"] + chapters

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(output_path, book)

    return PublicationBuild(
        output_path=output_path,
        a11y=a11y,
        chapters=records,
        clean_stream=clean_stream,
        stripped_furniture=furniture,
        welded_pairs=welds,
    )


# ---------------------------------------------------------------------------
# 4. Validation
# ---------------------------------------------------------------------------


def internal_structure_check(epub_path: str) -> list[dict]:
    """Offline structural validation: runs with no Java and no Node."""
    errors: list[dict] = []
    path = Path(epub_path)
    if not path.exists():
        return [{"file": "", "message": "output file missing", "severity": "FATAL"}]

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        return [{"file": "", "message": f"not a zip container: {exc}", "severity": "FATAL"}]

    with zf:
        names = zf.namelist()
        if not names or names[0] != "mimetype":
            errors.append(
                {"file": "mimetype", "message": "mimetype must be the first entry",
                 "severity": "ERROR"}
            )
        else:
            info = zf.getinfo("mimetype")
            if info.compress_type != zipfile.ZIP_STORED:
                errors.append(
                    {"file": "mimetype", "message": "mimetype must be stored uncompressed",
                     "severity": "ERROR"}
                )
            if zf.read("mimetype") != b"application/epub+zip":
                errors.append(
                    {"file": "mimetype", "message": "wrong mimetype value",
                     "severity": "ERROR"}
                )

        if "META-INF/container.xml" not in names:
            errors.append(
                {"file": "META-INF/container.xml", "message": "missing container.xml",
                 "severity": "FATAL"}
            )

        opf_names = [n for n in names if n.endswith(".opf")]
        if not opf_names:
            errors.append({"file": "", "message": "no OPF package document",
                           "severity": "FATAL"})

        import xml.etree.ElementTree as ET

        available = set(names)
        for name in names:
            if not name.endswith((".xhtml", ".html", ".opf", ".ncx", ".xml")):
                continue
            data = zf.read(name)
            try:
                root = ET.fromstring(data)
            except ET.ParseError as exc:
                errors.append(
                    {"file": Path(name).name, "message": f"XML parse error: {exc}",
                     "severity": "ERROR"}
                )
                continue

            if name.endswith((".xhtml", ".html")):
                base = Path(name).parent
                for link in root.iter("{http://www.w3.org/1999/xhtml}link"):
                    href = link.get("href", "")
                    if not href or href.startswith(("http:", "https:", "data:")):
                        continue
                    if _zip_normalise(base, href.split("#")[0]) not in available:
                        errors.append(
                            {"file": Path(name).name,
                             "message": f"broken stylesheet/link reference: {href}",
                             "severity": "ERROR"}
                        )
                for anchor in root.iter("{http://www.w3.org/1999/xhtml}a"):
                    href = anchor.get("href", "")
                    if not href or href.startswith(("http:", "https:", "data:", "#")):
                        continue
                    if _zip_normalise(base, href.split("#")[0]) not in available:
                        errors.append(
                            {"file": Path(name).name,
                             "message": f"broken internal link: {href}",
                             "severity": "ERROR"}
                        )
                for img in root.iter("{http://www.w3.org/1999/xhtml}img"):
                    src = img.get("src", "")
                    if not img.get("alt"):
                        errors.append(
                            {"file": Path(name).name,
                             "message": f"img without alt text: {src}",
                             "severity": "ERROR"}
                        )
                    if src and not src.startswith(("http:", "https:", "data:")):
                        target = str((base / src).resolve()).lstrip("/")
                        norm = _zip_normalise(base, src)
                        if norm not in available and target not in available:
                            errors.append(
                                {"file": Path(name).name,
                                 "message": f"broken image reference: {src}",
                                 "severity": "ERROR"}
                            )
                if root.get("lang") is None and root.get(
                    "{http://www.w3.org/XML/1998/namespace}lang"
                ) is None:
                    errors.append(
                        {"file": Path(name).name, "message": "html element missing lang",
                         "severity": "ERROR"}
                    )
    return errors


def _zip_normalise(base: Path, src: str) -> str:
    # Zip entries are always POSIX-style. On Windows, str(base) yields
    # backslashes, so "/".split() never splits it - the whole path collapses
    # into one fake path segment and a leading "../" in src pops the wrong
    # thing entirely. as_posix() guarantees forward slashes on every platform.
    parts: list[str] = [p for p in base.as_posix().split("/") if p not in ("", ".")]
    for chunk in src.split("/"):
        if chunk in ("", "."):
            continue
        if chunk == "..":
            if parts:
                parts.pop()
        else:
            parts.append(chunk)
    return "/".join(parts)


def _extract_ace_impact(result: dict) -> str | None:
    """Ace puts impact under earl:test; older/newer shapes vary. Try them all."""
    for container_key in ("earl:test", "earl:result", None):
        node = result if container_key is None else result.get(container_key, {})
        if isinstance(node, dict):
            impact = node.get("earl:impact") or node.get("impact")
            if isinstance(impact, str):
                return impact.lower()
    return None


def _ace_outcome_is_fail(result: dict) -> bool:
    node = result.get("earl:result", {})
    if isinstance(node, dict):
        outcome = node.get("earl:outcome") or node.get("outcome")
        if isinstance(outcome, str):
            return outcome.lower() in ("fail", "failed", "earl:fail")
    return True  # Ace only lists violations by default


def resolve_tool(cmd: str) -> str | None:
    """The single command-resolution path for detection AND execution.

    ``shutil.which`` is PATHEXT-aware on Windows, so npm-style ``ace.cmd``
    shims resolve; executing the resolved absolute path avoids the
    CreateProcess .exe-only fallback that made bare names invisible.
    """
    return shutil.which(cmd)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Best-effort whole-tree termination (Java/Node spawn children)."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:  # pragma: no cover - fall back to the direct child
        try:
            proc.kill()
        except Exception:
            pass


def _run_with_tree_kill(
    cmd: list[str], timeout: int
) -> subprocess.CompletedProcess:
    """``subprocess.run`` with a timeout that kills the whole process tree.

    A plain timeout only reaps the direct child; EPUBCheck and Ace spawn
    Java and Node children that would otherwise survive. The tree kill is
    an implementation detail -- the visible contract is still
    ``TimeoutExpired`` and the runners' existing "timed out" results.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=(sys.platform != "win32"),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


class DualValidator:
    def __init__(
        self,
        epubcheck_cmd: str | Sequence[str] = "epubcheck",
        ace_cmd: str = "ace",
        timeout: int = 300,
    ) -> None:
        # epubcheck_cmd may be a bare name or an argv list such as
        # ["java", "-jar", "epubcheck.jar"]; the first token is what resolves.
        if isinstance(epubcheck_cmd, str):
            self._epubcheck_argv = [epubcheck_cmd]
        else:
            self._epubcheck_argv = list(epubcheck_cmd)
        self.epubcheck_cmd = epubcheck_cmd  # kept for messages/compat
        self.ace_cmd = ace_cmd
        self.timeout = timeout

    # -- resolution (the single detection+execution path) -------------------
    def resolved_epubcheck_argv(self) -> list[str] | None:
        """The resolvable EPUBCheck argv, or None when not installed."""
        resolved = resolve_tool(self._epubcheck_argv[0])
        if resolved is None:
            return None
        return [resolved, *self._epubcheck_argv[1:]]

    def resolved_ace_cmd(self) -> str | None:
        """The resolvable Ace command, or None when not installed."""
        return resolve_tool(self.ace_cmd)

    # -- EPUBCheck ---------------------------------------------------------
    def run_epubcheck(self, epub_path: str, work_dir: str | None = None
                      ) -> tuple[bool, int, str, bool]:
        argv = self.resolved_epubcheck_argv()
        if argv is None:
            return (
                True,
                0,
                f"EPUBCheck not installed ('{self._epubcheck_argv[0]}') - skipped.",
                False,
            )
        work = Path(work_dir or Path(epub_path).parent)
        work.mkdir(parents=True, exist_ok=True)
        report_file = work / f"epubcheck_{uuid.uuid4().hex[:8]}.json"
        cmd = [*argv, str(epub_path), "--json", str(report_file), "--quiet"]
        try:
            proc = _run_with_tree_kill(cmd, self.timeout)
        except FileNotFoundError:
            return True, 0, f"EPUBCheck not installed ('{self._epubcheck_argv[0]}') - skipped.", False
        except subprocess.TimeoutExpired:
            return False, -1, "EPUBCheck timed out.", True

        try:
            if report_file.exists():
                data = json.loads(report_file.read_text(encoding="utf-8"))
                report_file.unlink()
                errors = [
                    m
                    for m in data.get("messages", [])
                    if str(m.get("severity", "")).upper() in ("ERROR", "FATAL")
                ]
                detail = json.dumps(errors[:20], indent=2) if errors else "no ERROR/FATAL messages"
                return len(errors) == 0, len(errors), detail, True
        except (json.JSONDecodeError, OSError) as exc:
            return False, -1, f"could not read EPUBCheck report: {exc}", True

        return proc.returncode == 0, 0 if proc.returncode == 0 else 1, proc.stdout or proc.stderr, True

    # -- Ace by DAISY ------------------------------------------------------
    def run_daisy_ace(
        self, epub_path: str, out_dir: str | None = None
    ) -> tuple[bool, dict[str, int], str, bool]:
        resolved = self.resolved_ace_cmd()
        if resolved is None:
            return True, {}, f"Ace not installed ('{self.ace_cmd}') - skipped.", False
        out = Path(out_dir or (Path(epub_path).parent / "ace_report"))
        out.mkdir(parents=True, exist_ok=True)
        cmd = [resolved, "--outdir", str(out), "--silent", str(epub_path)]
        try:
            proc = _run_with_tree_kill(cmd, self.timeout)
        except FileNotFoundError:
            return True, {}, f"Ace not installed ('{self.ace_cmd}') - skipped.", False
        except subprocess.TimeoutExpired:
            return False, {"error": -1}, "Ace timed out.", True

        report_file = out / "report.json"
        if not report_file.exists():
            return proc.returncode == 0, {}, proc.stdout or proc.stderr, True

        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return False, {"error": -1}, f"could not read Ace report: {exc}", True

        violations = parse_ace_violations(data)
        passed = violations["critical"] == 0 and violations["serious"] == 0
        return passed, violations, json.dumps(violations), True

    # -- combined ----------------------------------------------------------
    def validate(
        self,
        epub_path: str,
        enabled: Iterable[str] | None = None,
        reports_dir: str | None = None,
    ) -> ValidationReport:
        """Structural check plus the selected external validators.

        ``enabled=None`` runs every external validator (current behavior);
        a tuple/list selects a subset -- ``("epubcheck",)`` runs EPUBCheck
        only, ``()`` runs the internal check only. The internal structural
        check always runs; disabled tools are recorded in ``disabled`` and
        contribute ``passed=True, available=False`` so ``passed`` stays
        coherent (decision D1).

        Report ownership: with ``reports_dir=None`` reports go to a
        temporary directory that is removed afterwards; a supplied
        ``reports_dir`` is caller-owned -- the directory (and anything the
        caller put in it) is never deleted. Per-runner file behaviour is
        unchanged: the EPUBCheck JSON is unlinked after a successful parse,
        the Ace ``report.json`` remains.
        """
        structural = internal_structure_check(epub_path)
        hard = [e for e in structural if e["severity"] in ("ERROR", "FATAL")]

        run_all = enabled is None
        selected = set() if run_all else set(enabled)
        disabled = (
            []
            if run_all
            else [name for name in ("epubcheck", "ace") if name not in selected]
        )

        tmp = None
        if reports_dir is None:
            tmp = tempfile.TemporaryDirectory(prefix="pdf2epub_reports_")
            root = Path(tmp.name)
        else:
            root = Path(reports_dir)
            root.mkdir(parents=True, exist_ok=True)

        try:
            if run_all or "epubcheck" in selected:
                ep_passed, ep_errs, ep_log, ep_avail = self.run_epubcheck(
                    epub_path, work_dir=str(root)
                )
            else:
                ep_passed, ep_errs, ep_avail = True, 0, False
                ep_log = "EPUBCheck disabled for this run."

            if run_all or "ace" in selected:
                ace_passed, ace_viols, ace_log, ace_avail = self.run_daisy_ace(
                    epub_path, out_dir=str(root / "ace")
                )
            else:
                ace_passed, ace_viols, ace_avail = True, {}, False
                ace_log = "Ace disabled for this run."
        finally:
            if tmp is not None:
                try:
                    tmp.cleanup()
                except OSError:  # pragma: no cover - Windows file locks
                    pass

        disabled_note = f" (disabled: {', '.join(disabled)})" if disabled else ""
        logs = (
            f"=== Internal structural check ===\n"
            f"{json.dumps(structural[:20], indent=2) if structural else 'clean'}\n\n"
            f"=== EPUBCheck ===\n{ep_log}\n\n"
            f"=== Ace by DAISY ===\n{ace_log}{disabled_note}"
        )
        return ValidationReport(
            epubcheck_passed=ep_passed,
            epubcheck_errors=ep_errs,
            epubcheck_available=ep_avail,
            ace_passed=ace_passed,
            ace_violations=ace_viols,
            ace_available=ace_avail,
            structural_passed=not hard,
            structural_errors=structural,
            raw_logs=logs,
            disabled=disabled,
        )


def parse_ace_violations(data: dict) -> dict[str, int]:
    violations = Counter({"critical": 0, "serious": 0, "moderate": 0, "minor": 0})
    for assertion in data.get("assertions", []) or []:
        inner = assertion.get("assertions", []) or []
        for result in inner:
            if not _ace_outcome_is_fail(result):
                continue
            impact = _extract_ace_impact(result)
            if impact in violations:
                violations[impact] += 1
            elif impact:
                violations["minor"] += 1
    return dict(violations)
