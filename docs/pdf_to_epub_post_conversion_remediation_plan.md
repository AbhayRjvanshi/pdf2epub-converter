# PDF → EPUB Converter --- Post-Conversion Structural, Semantic, Layout & Packaging Remediation Plan

## 1. Purpose

This document defines the ordered remediation work required to improve
the PDF → EPUB conversion pipeline after identifying shortcomings in
structural reconstruction, semantic normalization, chapter generation,
navigation, links, lists, code, tables, layout, and validation.

The objective is **not** to redesign the converter or replace its
existing architecture. The objective is to establish a clean, scalable
boundary between:

1.  PDF extraction
2.  semantic interpretation
3.  semantic normalization
4.  chapter/layout policy
5.  EPUB packaging
6.  validation

The fixes are deliberately ordered. Earlier fixes establish invariants
required by later fixes.

The target is a reflowable EPUB that preserves the source document's
meaning and reading structure without unnecessarily preserving PDF
pagination or geometry.

------------------------------------------------------------------------

# 2. Core Problems to Fix

The current pipeline has several architectural and quality shortcomings:

-   semantic headings can become chapter boundaries unintentionally;
-   PDF page boundaries can influence EPUB pagination or document
    segmentation;
-   semantic interpretation is not consistently normalized before
    packaging;
-   URLs are not always converted into hyperlinks;
-   lists are not consistently represented as semantic HTML lists;
-   nested lists can lose their hierarchy;
-   code-like content can remain ordinary paragraphs or be
    misclassified;
-   heading levels can be inconsistent;
-   navigation can become incomplete when it is not derived from the
    final normalized structure;
-   HTML entities can be escaped more than once;
-   empty blocks or forced breaks can create excessive blank space;
-   XHTML chapter boundaries are not governed by an explicit scalable
    policy;
-   CSS can introduce unnecessary vertical spacing or break behavior;
-   EPUB validity checks do not sufficiently test semantic quality;
-   structural quality is not measured independently from EPUBCheck
    validity.

These are related problems, but they should not be solved with one large
heuristic.

The correct approach is to establish explicit responsibilities between
pipeline stages.

------------------------------------------------------------------------

# 3. Target Architecture

The pipeline should follow this responsibility model:

``` text
PDF
 ↓
Extraction
 ↓
Structural Representation
 ↓
Tier Routing / Semantic Interpretation
 ↓
Semantic Normalization
 ↓
Chapter & Layout Policy
 ↓
EPUB Packaging
 ↓
Structural Quality Checks
 ↓
EPUBCheck
```

The critical design rule is:

``` text
PDF page boundary
    ≠ semantic heading
    ≠ EPUB chapter
    ≠ EPUB page break
```

These concepts must remain independent.

A semantic heading should describe document structure.

A chapter boundary should describe a meaningful EPUB reading unit.

A PDF page boundary should primarily remain extraction metadata unless
there is an explicit reason to preserve it.

------------------------------------------------------------------------

# 4. Fix 1 --- Establish a Canonical Intermediate Semantic Representation

## Problem

Different stages currently have too much freedom to interpret the same
content independently.

This makes it possible for:

-   extraction to represent something one way;
-   semantic interpretation to represent it another way;
-   packaging to reinterpret it again.

That increases inconsistency and makes edge cases difficult to control.

## Fix

Introduce or strengthen a canonical intermediate representation between
semantic interpretation and EPUB packaging.

Conceptually:

``` text
SemanticDocument
 ├── metadata
 ├── sections
 ├── blocks
 │    ├── heading
 │    ├── paragraph
 │    ├── list
 │    ├── list_item
 │    ├── table
 │    ├── code
 │    ├── image
 │    ├── quote
 │    └── separator
 └── relationships
```

Each block should contain enough information for the packager to produce
EPUB without having to rediscover meaning.

For example:

``` text
Heading
    text
    level
    source location
    confidence
    structural role

Paragraph
    inline runs
    source location

Link
    display text
    URL

List
    ordered/unordered
    items
    nesting

Table
    rows
    columns
    header information
```

## How

Make the semantic representation the contract between interpretation and
packaging.

The EPUB packager should consume this representation rather than infer
semantics from raw strings.

## Edge cases

The representation should permit:

-   uncertain classification;
-   missing metadata;
-   empty-but-invalid blocks to be rejected;
-   nested structures;
-   inline formatting;
-   source provenance;
-   multiple source pages contributing to one semantic block.

## Acceptance criteria

No packaging decision should require guessing whether arbitrary text is
a heading, list, URL, or code block.

------------------------------------------------------------------------

# 5. Fix 2 --- Separate Semantic Headings from Chapter Boundaries

## Problem

A detected heading can unintentionally become an EPUB chapter boundary.

This causes documents with many headings to fragment into many small
XHTML documents.

That creates:

-   excessive chapter count;
-   unnecessary navigation entries;
-   excessive transitions;
-   poor reading continuity;
-   possible blank space;
-   larger and less coherent navigation structures.

## Fix

Treat these as independent concepts:

``` text
Heading
    → semantic hierarchy

Chapter boundary
    → EPUB packaging decision
```

Never derive chapter boundaries simply from:

``` text
"every heading"
```

or:

``` text
"the shallowest detected heading"
```

## How

Create an explicit `ChapterPolicy`.

Conceptually:

``` text
ChapterPolicy
    determine_chapter_boundaries(document)
```

The policy should consider:

1.  major structural headings;
2.  document-level hierarchy;
3.  section size;
4.  semantic continuity;
5.  explicit source structure;
6.  model-provided major-section information where available.

It should not use PDF page boundaries as a default chapter rule.

## Recommended policy

For small and medium documents:

``` text
one document
→ one XHTML file
```

unless there are clearly identifiable major sections.

For larger documents:

``` text
major semantic sections
→ bounded XHTML chapters
```

Avoid one XHTML file per heading.

## Edge cases

A document with:

``` text
H1
 H2
  H3
 H3
 H2
 H3
```

should not automatically produce five chapters.

Likewise, a document containing only many H3 headings should not become
dozens of XHTML files.

## Acceptance criteria

Chapter count is determined by explicit policy and remains stable when
ordinary subsection headings are added.

------------------------------------------------------------------------

# 6. Fix 3 --- Remove PDF Page Boundaries from EPUB Pagination

## Problem

PDF pages are fixed-layout artifacts. EPUB is normally reflowable.

Treating source-page boundaries as EPUB page breaks can produce:

-   blank-looking gaps;
-   unnatural transitions;
-   large unused areas;
-   fragmented reading;
-   artificial separation between paragraphs.

## Fix

Preserve source-page information as metadata where useful, but do not
convert it into an EPUB page break by default.

Use:

``` text
PDF page boundary
    → source provenance
```

rather than:

``` text
PDF page boundary
    → CSS page break
```

## How

Audit and remove unintended generation of:

``` css
page-break-before
page-break-after
break-before
break-after
```

and equivalent markup.

Only semantic chapter boundaries should cause intentional separation.

## Edge cases

A deliberate source-page break may matter when:

-   the source explicitly marks a new major section;
-   a title page must remain distinct;
-   a legal or publishing convention requires separation.

Such cases should be represented as semantic policy, not as automatic
preservation of every PDF page.

## Acceptance criteria

Converting a six-page PDF does not inherently create six EPUB pages, six
XHTML files, or six chapter breaks.

------------------------------------------------------------------------

# 7. Fix 4 --- Add a Dedicated Semantic Normalization Stage

## Problem

Semantic interpretation can produce structurally valid but inconsistent
HTML.

Examples of normalization failures include:

-   URLs remaining plain text;
-   bullets represented as literal characters;
-   numbered lists remaining paragraphs;
-   code represented as ordinary text;
-   inconsistent heading levels;
-   malformed nested structures.

## Fix

Add a deterministic `SemanticNormalizer` after semantic interpretation
and before EPUB packaging.

``` text
Semantic interpretation
        ↓
SemanticNormalizer
        ↓
NormalizedDocument
        ↓
EPUB packager
```

The normalizer should enforce the document contract.

## Responsibilities

It should normalize:

-   headings;
-   links;
-   lists;
-   nested lists;
-   tables;
-   code;
-   inline emphasis;
-   whitespace;
-   escaping;
-   invalid empty blocks;
-   structural relationships.

## Important rule

The normalizer should **not invent content**.

It should normalize evidence already present in the extracted or
interpreted structure.

------------------------------------------------------------------------

# 8. Fix 5 --- Deterministic URL and Hyperlink Detection

## Problem

URLs can remain ordinary text even when they are unambiguous hyperlinks.

## Fix

Add a URL normalization pass.

Example:

``` text
https://example.com/path
```

becomes:

``` html
<a href="https://example.com/path">
    https://example.com/path
</a>
```

## How

Detect:

-   `https://...`
-   `http://...`

and safely strip only sentence punctuation that is clearly outside the
URL.

Validate the URL before emitting an anchor.

## Edge cases

Handle:

``` text
https://example.com.
https://example.com/path)
https://example.com?q=1&x=2
```

without corrupting the actual URL.

Do not treat arbitrary strings containing dots as URLs.

## Acceptance criteria

Every unambiguous source URL becomes a semantic link exactly once.

------------------------------------------------------------------------

# 9. Fix 6 --- Semantic List Reconstruction

## Problem

Lists may remain paragraphs containing:

``` text
1. Item
2. Item
3. Item
```

or:

``` text
• Item
• Item
```

This preserves appearance but loses semantics.

## Fix

Convert clear list structures into:

``` html
<ol>
    <li>Item</li>
</ol>
```

or:

``` html
<ul>
    <li>Item</li>
</ul>
```

## How

Use multiple signals:

-   list marker;
-   indentation;
-   consecutive numbering;
-   vertical proximity;
-   shared formatting;
-   semantic interpretation.

Do not convert isolated occurrences automatically.

## Nested lists

Preserve nesting when the source clearly indicates it:

``` html
<ul>
    <li>
        Parent
        <ul>
            <li>Child</li>
        </ul>
    </li>
</ul>
```

## Edge cases

Handle:

-   numbered lists starting at values other than 1;
-   alphabetic lists;
-   roman numerals;
-   bullet glyph variants;
-   wrapped list items;
-   list items spanning source pages.

Do not merge unrelated paragraphs merely because they begin with similar
characters.

------------------------------------------------------------------------

# 10. Fix 7 --- Normalize Heading Hierarchy

## Problem

Heading levels can be structurally inconsistent.

A document can end up with excessive use of one heading level or with
headings that do not reflect the actual hierarchy.

## Fix

Create a heading normalization pass.

The normalizer should consider:

-   existing detected level;
-   document hierarchy;
-   heading sequence;
-   indentation/position;
-   typography;
-   semantic role;
-   parent heading context.

## Rules

Avoid unnecessary level jumps such as:

``` text
H1 → H4
```

when the document clearly represents an intermediate structure.

Do not flatten every heading to one level.

Do not promote ordinary short text merely because it resembles a
heading.

## Edge cases

The normalizer must conservatively handle:

-   title pages;
-   repeated running headers;
-   captions;
-   table headers;
-   short labels;
-   code identifiers;
-   sentence fragments.

Uncertain content should remain ordinary content rather than being
aggressively promoted.

------------------------------------------------------------------------

# 11. Fix 8 --- Prevent False Heading Promotion

## Problem

Technical tokens and short lines can resemble headings.

Examples include:

``` text
MultinomialNB(alpha=0.5)
```

or isolated labels.

## Fix

Extend the existing heading safeguards rather than replacing the heading
detector.

Add negative signals for:

-   code syntax;
-   function calls;
-   assignment expressions;
-   URLs;
-   table cells;
-   list markers;
-   sentence punctuation;
-   inline technical expressions.

## Acceptance criteria

A technical expression should only become a heading when there is
independent structural evidence supporting that interpretation.

------------------------------------------------------------------------

# 12. Fix 9 --- Normalize Code Blocks

## Problem

Code can be emitted as ordinary paragraphs or split into several
unrelated blocks.

## Fix

Represent code explicitly:

``` html
<pre><code>...</code></pre>
```

for genuine multi-line code.

Use inline:

``` html
<code>...</code>
```

for short code fragments.

## Detection signals

Use:

-   source typography;
-   indentation;
-   consecutive lines;
-   programming syntax;
-   surrounding labels;
-   semantic classification.

Do not classify every technical term as code.

## Edge cases

Preserve:

-   indentation;
-   whitespace;
-   punctuation;
-   line breaks.

Avoid HTML escaping that changes the displayed code.

------------------------------------------------------------------------

# 13. Fix 10 --- Preserve Structured Tables

## Problem

Table content can lose semantic structure and become ordinary paragraphs
or images.

## Fix

Represent reconstructable tables as:

``` html
<table>
    <thead>...</thead>
    <tbody>...</tbody>
</table>
```

## How

The structural representation should contain:

-   rows;
-   columns;
-   cell boundaries;
-   header status;
-   merged-cell information where available.

The EPUB layer should render the table rather than rediscover its
structure.

## Edge cases

Support:

-   merged cells;
-   multiline cells;
-   wide tables;
-   tables crossing source pages;
-   missing headers.

If a table cannot be reconstructed reliably, preserve its content safely
rather than fabricating cell relationships.

------------------------------------------------------------------------

# 14. Fix 11 --- Make Navigation a Derived Artifact

## Problem

Navigation can become incomplete or inconsistent with the actual EPUB
content.

## Fix

Generate navigation only after semantic normalization and heading
validation.

``` text
NormalizedDocument
       ↓
validated heading tree
       ↓
navigation
```

Navigation should never be independently inferred from raw extraction.

## Requirements

Navigation must:

-   include intended navigable headings;
-   preserve hierarchy;
-   point to existing anchors;
-   exclude invalid or empty entries;
-   match final XHTML structure.

## Edge cases

If a heading is removed or merged during normalization, its navigation
entry must disappear or be updated automatically.

------------------------------------------------------------------------

# 15. Fix 12 --- Enforce Single-Pass HTML Escaping

## Problem

Text can become double-escaped.

For example:

``` text
&
→ &amp;
→ &amp;amp;
```

## Fix

Define one ownership rule for escaping.

Recommended:

``` text
internal representation
    → raw text
    → HTML serializer escapes exactly once
```

Do not pre-escape strings before passing them to an HTML serializer that
escapes them again.

## Acceptance criteria

Regression tests must cover:

-   `&`;
-   `<`;
-   `>`;
-   quotes;
-   URLs;
-   table content;
-   heading text.

------------------------------------------------------------------------

# 16. Fix 13 --- Eliminate Empty Blocks and Artificial Spacing

## Problem

Blank areas can result from:

-   empty paragraphs;
-   empty XHTML sections;
-   repeated `<br>`;
-   forced page breaks;
-   excessive CSS margins;
-   empty chapter containers.

## Fix

Add a normalization rule that removes meaningless empty blocks.

Do not remove intentional structural spacing represented by CSS.

## Rules

Remove:

``` html
<p></p>
```

and equivalent empty structures unless they carry an explicit semantic
purpose.

Collapse redundant whitespace and line-break elements.

## Edge cases

Do not remove:

-   meaningful whitespace inside `<pre>`;
-   required table-cell content;
-   intentional separators;
-   semantic empty containers required by EPUB structure.

------------------------------------------------------------------------

# 17. Fix 14 --- Introduce Explicit XHTML Chapter Sizing Policy

## Problem

XHTML document boundaries can become accidental consequences of heading
detection.

## Fix

Create a chapter segmentation policy with configurable constraints.

Possible inputs:

``` text
minimum semantic weight
maximum approximate content size
major heading level
document section boundaries
semantic continuity
```

The policy should prefer:

``` text
logical completeness
```

over:

``` text
arbitrary file size
```

## Edge cases

A huge chapter may need to be divided.

A short chapter should not be divided merely to satisfy an artificial
size threshold.

A subsection should remain attached to its parent when splitting would
damage comprehension.

------------------------------------------------------------------------

# 18. Fix 15 --- Rework EPUB CSS for Reflowable Reading

## Problem

Presentation can introduce unnecessary vertical space and make the
document feel fragmented.

## Fix

Use a restrained, document-oriented stylesheet.

The CSS should define consistent:

-   body typography;
-   line height;
-   paragraph spacing;
-   heading spacing;
-   list indentation;
-   table wrapping;
-   code formatting;
-   image sizing;
-   link presentation.

Avoid styling that imitates fixed PDF pages.

## Recommended principles

``` text
Body
    readable width
    comfortable line height

H1
    strong separation

H2
    moderate separation

H3/H4
    compact separation

Paragraph
    consistent small spacing

List
    compact but readable indentation

Table
    responsive width
    controlled cell padding
```

## Edge cases

The stylesheet must remain usable when:

-   font size is increased;
-   viewport width changes;
-   the reader uses a different default font;
-   a table is wider than the viewport;
-   a paragraph wraps to many lines.

------------------------------------------------------------------------

# 19. Fix 16 --- Add Structural Quality Validation

## Problem

EPUBCheck validates EPUB conformance but cannot establish whether the
conversion is semantically good.

## Fix

Add converter-specific structural validation.

Check:

``` text
chapter count
empty XHTML files
empty bodies
heading hierarchy
navigation consistency
broken internal links
external URL validity
list semantics
table semantics
code structure
duplicate escaping
unexpected page breaks
empty paragraphs
```

## Example report

``` text
Structural validation

chapters              PASS
empty XHTML           PASS
heading hierarchy     PASS
navigation            PASS
links                 PASS
lists                 PASS
tables                PASS
code blocks           PASS
escaping              PASS
forced page breaks    PASS
```

The existing EPUBCheck result should remain separate.

------------------------------------------------------------------------

# 20. Fix 17 --- Add Regression Fixtures for Structural Failures

Create small deterministic fixtures for each previously observed class
of defect.

Required fixture categories:

1.  multiple headings;
2.  many subsections;
3.  URL paragraphs;
4.  nested lists;
5.  numbered lists;
6.  code blocks;
7.  tables;
8.  mixed headings and code;
9.  special characters;
10. source-page transitions;
11. large sections;
12. empty/near-empty blocks.

Each fixture should have explicit expected structural properties.

This is more scalable than relying on one large PDF to test everything.

------------------------------------------------------------------------

# 21. Fix 18 --- Add Visual Regression Verification

After structural fixes are stable, add visual verification.

The visual check should inspect:

-   blank areas;
-   heading spacing;
-   list indentation;
-   table wrapping;
-   code presentation;
-   hyperlink visibility;
-   image sizing;
-   chapter transitions.

Visual validation should not replace structural validation.

It complements it.

------------------------------------------------------------------------

# 22. Fix 19 --- Add Conversion Quality Metrics

The converter should internally be able to report measurable structural
properties.

Example:

``` text
Semantic structure
    headings: 17
    lists: 4
    tables: 1
    links: 3
    code blocks: 1

Packaging
    chapters: 2
    empty chapters: 0
    forced page breaks: 0
    empty paragraphs: 0

Navigation
    entries: 17
    unresolved targets: 0

Validation
    structural: PASS
    EPUBCheck: PASS
```

The exact values should depend on the document.

The important point is that quality becomes observable rather than being
judged only by opening the EPUB manually.

------------------------------------------------------------------------

# 23. Fix 20 --- Keep the Responsibilities Strict

The final architecture should enforce these boundaries:

## Extraction owns

-   text;
-   geometry;
-   source-page information;
-   images;
-   raw structural evidence.

## Semantic interpretation owns

-   meaning;
-   structural classification;
-   ambiguous document understanding.

## Semantic normalization owns

-   consistent HTML semantics;
-   links;
-   lists;
-   heading hierarchy;
-   tables;
-   code;
-   escaping;
-   structural cleanup.

## Chapter policy owns

-   XHTML boundaries;
-   major reading units.

## EPUB packager owns

-   XHTML serialization;
-   CSS;
-   OPF;
-   spine;
-   navigation;
-   resources.

## Validation owns

-   structural invariants;
-   EPUB conformance;
-   regression checks.

No layer should silently take over another layer's responsibility.

------------------------------------------------------------------------

# 24. Ordered Implementation Sequence

The implementation should proceed in this order.

## Phase 1 --- Structural foundation

### 1. Define the canonical semantic representation

Create the normalized intermediate contract.

### 2. Separate headings from chapters

Remove any implicit `heading → chapter` coupling.

### 3. Separate PDF pages from EPUB pagination

Prevent source-page boundaries from generating EPUB page breaks.

### 4. Audit empty blocks and forced breaks

Remove structural causes of artificial blank space.

These four changes establish the foundation.

------------------------------------------------------------------------

## Phase 2 --- Semantic normalization

### 5. Add the SemanticNormalizer

Create the deterministic post-semantic normalization boundary.

### 6. Normalize heading hierarchy

Preserve the document's actual hierarchy while remaining conservative.

### 7. Add URL detection

Convert unambiguous URLs into links.

### 8. Normalize unordered and ordered lists

Convert clear list structures to semantic lists.

### 9. Preserve nested lists

Do not flatten meaningful list hierarchy.

### 10. Normalize code

Distinguish inline code from blocks.

### 11. Preserve/reconstruct tables

Use semantic tables whenever structural evidence supports them.

### 12. Enforce single-pass escaping

Eliminate double-escaping.

------------------------------------------------------------------------

## Phase 3 --- Packaging

### 13. Implement explicit chapter policy

Create logical XHTML boundaries.

### 14. Generate navigation from the normalized heading tree

Navigation becomes a derived artifact.

### 15. Generate the spine from final chapters

The spine must reflect actual packaged content.

### 16. Remove empty XHTML documents

Reject or eliminate empty chapter artifacts.

------------------------------------------------------------------------

## Phase 4 --- Presentation

### 17. Tune EPUB CSS

Optimize for reflowable reading.

### 18. Tune heading/list/table spacing

Remove excessive vertical fragmentation.

### 19. Tune links and code presentation

Make semantic structures visibly readable.

### 20. Tune responsive table/image behavior

Prevent overflow and clipping.

------------------------------------------------------------------------

## Phase 5 --- Validation

### 21. Add structural validation

Test the EPUB's semantic contract.

### 22. Add regression fixtures

Lock down every repaired failure class.

### 23. Run EPUBCheck

Continue standards validation separately.

### 24. Add visual regression checks

Verify actual reader presentation.

### 25. Add quality metrics

Make structural quality measurable.

------------------------------------------------------------------------

# 25. Definition of Done

The remediation is complete when the converter satisfies all of the
following:

### Structure

-   headings do not automatically create chapters;
-   PDF page boundaries do not automatically create EPUB page breaks;
-   chapters are produced by explicit policy;
-   XHTML files contain meaningful content;
-   no artificial blank sections are generated.

### Semantics

-   headings have coherent hierarchy;
-   URLs become hyperlinks;
-   ordered content becomes `<ol>/<li>` where justified;
-   unordered content becomes `<ul>/<li>` where justified;
-   nested lists remain nested;
-   code has appropriate semantic representation;
-   reconstructable tables remain semantic tables;
-   inline emphasis is preserved.

### Navigation

-   navigation is derived from final normalized structure;
-   every navigation target exists;
-   navigation hierarchy matches heading hierarchy;
-   removed/merged headings do not leave stale entries.

### Serialization

-   HTML entities are escaped exactly once;
-   empty meaningless blocks are removed;
-   internal links are valid;
-   CSS does not introduce unnecessary page breaks;
-   CSS supports reflow.

### Validation

-   structural validation passes;
-   regression tests pass;
-   EPUBCheck passes;
-   visual regression checks show no major blank-page, spacing,
    clipping, or overflow defects.

------------------------------------------------------------------------

# 26. Final Design Principle

The converter should not attempt to make a PDF look like a PDF inside an
EPUB.

The correct objective is:

``` text
Preserve meaning
    +
Preserve reading structure
    +
Preserve important semantics
    +
Preserve useful visual hierarchy
    -
Discard fixed-page constraints that do not belong in reflowable EPUB
```

The most important architectural change is therefore:

``` text
Semantic interpretation
        ↓
Semantic normalization
        ↓
Chapter/layout policy
        ↓
EPUB packaging
```

rather than allowing semantic interpretation, chapter generation,
pagination, and HTML serialization to influence one another directly.

This gives the converter a scalable design in which future
improvements---better heading detection, better table extraction,
additional providers, better code detection, or new document types---can
improve one stage without destabilizing the rest of the EPUB pipeline.
