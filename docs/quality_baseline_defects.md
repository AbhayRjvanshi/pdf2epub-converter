# Conversion Quality Baseline — Defect Register

Date: 2026-10-15
Baseline commit: `95aabbb` on `main`
Branch: `quality-baseline` (read-only with respect to production code)
Corpus: 4 representative documents converted with the unchanged baseline

---

## Corpus and conversion results

| Document | Category | Pages | Links (URI) | Links (internal) | Conversion |
|---|---|---|---|---|---|
| LinuxNotesForProfessionals | text-heavy, link-rich | 65 | 93 unique | 208 | PASS |
| Artificial_Intelligence_Projects | mixed, some links | 6 | 3 unique | 0 | PASS |
| architecture-reference | technical, internal links, footnotes | 97 | 0 | 30 | PASS |
| THE FLOWER GARDEN | children's picture book (control) | 32 | 0 | 0 | PASS |

All EPUBs pass the internal structural check. The Flower Garden is the control case — no links expected or lost.

## Confirmed defects

### LINK-001 — PDF URI annotations are not extracted

**Severity**: High — users lose clickable web links present in the source PDF.

**Evidence**:
- LinuxNotesForProfessionals: **89 of 93** unique URI annotations missing from the EPUB.
  Only 4 URIs appear (via text URL linkification, not annotation extraction).
- Artificial_Intelligence_Projects: **2 of 3** unique URIs missing.
- Example missing: `https://en.wikipedia.org/wiki/Cat_(Unix)`, `http://www.ietf.org/rfc/rfc0952.txt`

**Root cause**: The converter never calls `page.get_links()` during extraction. The only
links in the EPUB output come from `semantic_normalizer.py::linkify_urls`, which
converts plain-text URLs into anchors — but does not read PDF annotation metadata.

**Scope**: Any PDF with clickable hyperlink annotations (common in born-digital
technical documents, web-archived pages, and reference manuals).

**Reproducibility**: Confirmed on repeated conversion with the same source.

**Proposed fix direction**: Call `page.get_links()` during Tier 1 extraction; map
each URI annotation's bounding rectangle to overlapping text elements; emit `<a href>`
wrappers on the matched text. Must handle duplicate-link avoidance (annotation +
already-linkified text URL → single anchor, not nested).

---

### LINK-002 — PDF internal links are not extracted

**Severity**: Medium — readers lose in-document navigation (table of contents
links, cross-references, "see page X" references).

**Evidence**:
- LinuxNotesForProfessionals: **208** internal links completely absent.
- architecture-reference: **30** internal links completely absent.

**Root cause**: Same as LINK-001 — no `page.get_links()` call. Internal links
(LINK_GOTO pointing to another page) require a mapping from the target PDF page
to the corresponding EPUB chapter/anchor, which the current pipeline does not
build.

**Scope**: Any PDF with internal cross-references or a clickable table of contents.

**Reproducibility**: Confirmed.

**Proposed fix direction**: Extract LINK_GOTO annotations; map the target page
number to the EPUB chapter containing that page; emit internal `<a href="chapter.xhtml#anchor">`.
Requires a page-to-chapter mapping table built during packaging.

---

### NOTE-001 — Footnote/supplementary text is extracted as disconnected body paragraphs

**Severity**: Medium-high — small-font text at page bottoms (footnotes, endnotes,
supplementary detail) is extracted as ordinary paragraphs with no marker-to-note
linking, no superscript preservation, and no separation from body content.

**Evidence**:
- architecture-reference: 32 of 97 sampled pages have small-font (8.6pt) text in the
  bottom 15% of the page. This text IS extracted into the EPUB (content preserved)
  but appears as regular paragraphs with no relationship to the body text it annotates.
- No superscript markers detected via MuPDF's FLAG_SUPERSCRIPT in the sampled pages
  (this particular document may use a different footnote convention — numbers or
  inline references rather than superscript digits).
- In the EPUB, the note text appears as body paragraphs like any other content.

**Root cause**: The converter has no concept of footnotes or endnotes. No detection
of small-font bottom-zone text, no marker-to-note association, no `<aside>` or
`epub:footnote` semantics.

**Scope**: Any PDF with footnotes, endnotes, or page-bottom supplementary text.

**Reproducibility**: Confirmed.

**Proposed fix direction**: Two-phase: (1) detect footnote candidates by font size,
page position, and content patterns; (2) associate markers with notes via numbering
or spatial proximity. This is a larger design than LINK-001/LINK-002 and should
follow the link extraction work.

---

## Known limitations (observed, documented in previous rounds)

| ID | Description | Disposition |
|---|---|---|
| TABLE-001 | Cleanly-aligned two-column content stays as prose (no-fabrication rule) | Documented; needs a dedicated table fixture to tighten |
| SCAN-001 | Scanned pages are full-page images with no OCR | Out of scope for the deterministic engine |
| DIGEST-001 | Digest-page furniture below the position-evidence guard | Deferred (corpus record) |

## No defect observed

| Dimension | Evidence |
|---|---|
| Text fidelity | All corpus documents' text content preserved (verified in prior corpus sessions and e2e tests) |
| Heading/structure | Headings, chapters, lists, code correctly detected across all corpus documents |
| Image presence | All images present and correctly referenced in all outputs |
| EPUB validity | All outputs pass the internal structural check; EPUBCheck verified in prior runs |
| Cross-page welding | Paragraph welding works correctly across page boundaries |

## Link gap summary

| Document | PDF URI annotations | In EPUB | Missing | PDF internal links | In EPUB |
|---|---|---|---|---|---|
| LinuxNotesForProfessionals | 93 unique | 4 | **89** | 208 | **0** |
| Artificial_Intelligence_Projects | 3 unique | 1 | **2** | 0 | 0 |
| architecture-reference | 0 | 0 | 0 | 30 | **30** |
| THE FLOWER GARDEN | 0 | 0 | 0 | 0 | 0 |

**Total confirmed missing external URI links: 91. Total confirmed missing internal links: 238.**
