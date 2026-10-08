# PDF → EPUB Converter --- Stabilization & Fix Sequencing Plan

## Purpose

This document defines the controlled remediation sequence for the
current PDF → EPUB converter after Stage 0 validation and the first real
NVIDIA-provider setup attempt.

The objective is **not** to redesign the converter. The objective is to
make the current architecture reliable enough to use a real multimodal
provider (NVIDIA-hosted Kimi K3), then improve semantic EPUB quality and
project hygiene without allowing changes in one area to contaminate
validation of another.

The sequence is intentionally dependency-aware:

-   provider/dependency correctness comes before real-provider testing;
-   catalog/model registration comes before model selection;
-   credential persistence is verified before long-running conversion;
-   the real Kimi path is validated before judging conversion-quality
    changes;
-   the Stage-0 EPUB remains a frozen regression baseline;
-   semantic/metadata changes happen only after the real-provider
    baseline is established;
-   validator and integration tests are strengthened before the project
    is declared mature.

------------------------------------------------------------------------

# 1. Current Baseline

## 1.1 Stage-0 conversion baseline

The current offline conversion of the six-page test PDF succeeded.

Observed routing:

``` text
tier1=4
tier2-digest=1
tier2-vision=1
```

Observed packaging:

``` text
79 stream elements
1 chapter
0 cross-page welds
0 furniture lines stripped
headings=0
images=1
alt_text=yes
```

The output EPUB was visually assessed at approximately **8.5/10**.

The strongest aspects were:

-   substantial text preservation;
-   good reading order;
-   lists and links preserved;
-   difficult visual/table page preserved rather than incorrectly
    reconstructed;
-   both Tier-2 digest and vision paths exercised.

The main quality weakness observed was semantic structure, especially:

``` text
a11y: headings=0
```

despite obvious headings in the source PDF.

The Stage-0 EPUB should therefore be treated as a **frozen regression
artifact**. Do not overwrite it while implementing the next stages.

------------------------------------------------------------------------

# 2. What Has Already Been Proven

The following are not hypothetical problems.

## 2.1 NVIDIA adapter exists

The project has a dedicated NVIDIA-style adapter using the NVIDIA
OpenAI-compatible endpoint:

``` text
https://integrate.api.nvidia.com/v1
```

The adapter uses:

``` text
NVIDIA_API_KEY
```

and can construct multimodal requests.

The engine/Tier-2 layer remains provider-neutral.

## 2.2 NVIDIA is visible in the current CLI

The actual interactive session showed:

``` text
/provider

Available providers:
  1. none (none)
  2. OpenAI (openai)
  3. Anthropic (anthropic)
  4. NVIDIA (nvidia)
```

Therefore the local working state has already moved beyond the earlier
catalog state observed in the uploaded ZIP.

## 2.3 The first real-provider setup attempt exposed a concrete defect

Selecting NVIDIA and verifying credentials produced:

``` text
verification failed:
the 'openai' package is required for provider 'nvidia':
pip install 'pdf2epub[openai]'
```

This is the immediate integration defect.

It is **not** an indication that an OpenAI API key is required.

The OpenAI package is being used as the Python client library for
NVIDIA's OpenAI-compatible API.

------------------------------------------------------------------------

# 3. Non-Negotiable Sequencing Rules

The following rules govern all remediation work.

## Rule A --- Freeze the Stage-0 baseline

Do not modify or overwrite the existing Stage-0 EPUB.

Every later conversion should use a different output filename.

## Rule B --- One architectural boundary at a time

Do not combine:

-   dependency changes;
-   provider registration;
-   model catalog changes;
-   credential-storage changes;
-   conversion-engine changes;
-   semantic EPUB changes

in one uncontrolled change set.

Each stage must reach a green state before the next stage starts.

## Rule C --- Do not modify Tier-2 for provider-specific behavior

Kimi K3 must enter through the existing provider abstraction.

Do not add:

``` text
if provider == "nvidia"
```

or:

``` text
if model == "moonshotai/kimi-k3"
```

inside the conversion engine merely to make Kimi work.

## Rule D --- Do not judge conversion quality until the provider path is proven

Otherwise a dependency/configuration problem can be mistaken for a
conversion problem.

## Rule E --- Preserve rollback boundaries

Each phase should have:

1.  a focused implementation;
2.  focused tests;
3.  a clean commit;
4.  a documented validation command;
5.  no unrelated refactoring.

## Rule F --- Existing behavior must remain green

The offline provider must continue to work after every provider-layer
change.

The Stage-0 test PDF is the minimum regression case.

------------------------------------------------------------------------

# 4. Fix Sequence Overview

The recommended sequence is:

``` text
PHASE A
Freeze baseline + establish clean branch/checkpoint
        ↓
PHASE B
Fix dependency declaration and doctor detection
        ↓
PHASE C
Verify NVIDIA provider registration/user-facing behavior
        ↓
PHASE D
Register Kimi K3 in the model catalog
        ↓
PHASE E
Verify NVIDIA credential entry + verification
        ↓
PHASE F
Verify credential persistence/retrieval
        ↓
PHASE G
Run isolated real Kimi K3 request
        ↓
PHASE H
Run full six-page PDF through Kimi
        ↓
PHASE I
Compare Kimi EPUB against frozen Stage-0 baseline
        ↓
PHASE J
Install/run EPUBCheck + Ace
        ↓
PHASE K
Fix heading semantics
        ↓
PHASE L
Improve metadata/title extraction
        ↓
PHASE M
Improve TOC/navigation
        ↓
PHASE N
Normalize dependency metadata + requirements
        ↓
PHASE O
Clean README/user-facing provider documentation
        ↓
PHASE P
Add real-provider integration tests
        ↓
PHASE Q
Expand regression corpus with representative PDFs
        ↓
Maturity gate
```

The order is deliberate.

------------------------------------------------------------------------

# 5. Phase A --- Freeze the Baseline

## Problem

The project already has a successful offline conversion that provides
the only objective before/after comparison we currently have.

## Fix

Create/retain a known-good checkpoint containing:

-   current source tree;
-   passing test suite;
-   Stage-0 EPUB;
-   the exact six-page source PDF;
-   current CLI behavior;
-   current provider registry behavior.

Record:

``` text
provider: none
model: offline/default
input: six-page test PDF
output: frozen Stage-0 EPUB
```

## Edge cases

-   Do not regenerate the baseline after changing provider behavior.
-   Do not replace the baseline with a Kimi result.
-   If the baseline must be regenerated, treat it as a new baseline and
    explicitly document why.

## Validation

Run:

``` powershell
pdf2epub doctor
pdf2epub convert <test.pdf> -o stage0-regression.epub --provider none
```

Confirm the same broad routing and packaging behavior.

## Why first?

Every later quality change needs a stable comparison point.

------------------------------------------------------------------------

# 6. Phase B --- Fix Dependency Declaration and Doctor Detection

## Problem

NVIDIA's adapter imports the OpenAI Python SDK, but the dependency
relationship is not represented cleanly enough.

The user selected NVIDIA and reached credential verification before
discovering the missing package.

That is too late.

## Optimal scalable fix

Treat provider SDK requirements as provider metadata rather than
scattering dependency knowledge across CLI code.

Conceptually, each provider should expose information equivalent to:

``` text
provider_id
credential_env_var
base_url
client_dependency
install_extra
```

For NVIDIA:

``` text
provider_id: nvidia
credential_env_var: NVIDIA_API_KEY
client_dependency: openai
install_extra: openai
```

The exact internal representation should follow the project's existing
profile/registry architecture rather than introduce a second dependency
registry.

## Important distinction

The documentation must make clear:

``` text
openai package
≠
OpenAI provider
≠
OpenAI API key
```

NVIDIA uses the OpenAI-compatible Python client library, but
authentication remains:

``` text
NVIDIA_API_KEY
```

## Doctor behavior

`pdf2epub doctor` should report something equivalent to:

``` text
nvidia SDK      OPTIONAL/MISSING   openai package required for provider nvidia
```

when the package is absent.

When installed:

``` text
nvidia SDK      OK                openai
```

The exact display should match existing doctor conventions.

## Edge cases

### OpenAI installed, NVIDIA key absent

Doctor should not claim NVIDIA is fully configured.

It should separate:

-   dependency availability;
-   credential availability.

### NVIDIA key exists, SDK absent

Doctor should identify the missing SDK before provider verification.

### NVIDIA SDK dependency is shared with OpenAI

Do not install two separate client libraries merely because there are
two providers.

### User installs only the NVIDIA extra

The resulting environment must work.

### User installs the existing OpenAI extra

NVIDIA should also become technically usable if that extra provides the
shared SDK.

## Tests

Add/adjust tests for:

1.  NVIDIA dependency present.
2.  NVIDIA dependency missing.
3.  NVIDIA doctor output.
4.  OpenAI and NVIDIA sharing the same client dependency.
5.  Missing credential remains distinguishable from missing dependency.

## Exit condition

No provider verification should fail merely because the user was unaware
of a documented SDK dependency.

------------------------------------------------------------------------

# 7. Phase C --- Verify NVIDIA User-Facing Provider Registration

## Problem

The provider must be consistently represented as user-selectable.

Earlier project inspection showed a profile state equivalent to:

``` text
user_facing=False
models=()
```

while the actual local CLI now shows NVIDIA.

This discrepancy must be resolved against the actual working tree.

## Fix

Make the authoritative provider registry/profile state explicitly
support:

``` text
NVIDIA
```

as a normal selectable provider.

Do not hard-code NVIDIA into the interactive CLI.

The CLI should derive provider choices from the registry.

## Edge cases

-   NVIDIA must appear only once.
-   Provider IDs must remain stable: `nvidia`.
-   Display name can be `NVIDIA`.
-   Internal API style can remain `nvidia`.
-   `none` must remain selectable for offline operation.
-   Adding NVIDIA must not reorder or break existing provider selection
    unexpectedly unless the registry explicitly defines ordering.

## Validation

``` text
/provider
```

must list NVIDIA.

Existing OpenAI, Anthropic, and offline behavior must remain intact.

------------------------------------------------------------------------

# 8. Phase D --- Register `moonshotai/kimi-k3`

## Problem

A provider without a catalog model is incomplete for the intended
workflow.

## Fix

Add exactly the model information required by the existing catalog
architecture:

``` text
provider: nvidia
model_id: moonshotai/kimi-k3
```

Mark its capabilities according to the actual supported modality used by
the project.

Do not add Kimi-specific engine logic.

## Important principle

The catalog should describe capabilities, not implementation tricks.

The engine should ask the catalog/registry:

``` text
Can this model handle the requested route?
```

rather than:

``` text
Is this Kimi K3?
```

## Edge cases

-   Model ID must be passed exactly as expected by NVIDIA.
-   Do not strip the provider namespace from `moonshotai/kimi-k3`.
-   Do not silently translate it to `kimi-k3`.
-   Do not register multiple aliases unless the project has a deliberate
    alias mechanism.
-   Do not mark the model as vision-capable unless the request path
    actually supports image input.
-   Do not make it the default model merely because it is the first
    newly-added model.

## Validation

The model selection path should show Kimi K3 under NVIDIA.

A provider/model resolution test should resolve:

``` text
nvidia + moonshotai/kimi-k3
```

to the correct adapter/model combination.

------------------------------------------------------------------------

# 9. Phase E --- Verify Credential Entry and Verification

## Problem

The credential UI now reaches NVIDIA, but the path has not yet been
proven end-to-end.

## Fix

Use the existing generic credential mechanism.

The workflow should be:

``` text
/provider
→ NVIDIA
→ hidden API-key prompt
→ verify
→ optional persistence
```

Do not create a special NVIDIA credential command.

## Security requirements

-   Never echo the key.
-   Never print the full key in errors.
-   Never write it to ordinary config files.
-   Never include it in reports.
-   Never include it in exception strings.
-   Never include it in test logs.
-   Never commit it.
-   Never place it in the model catalog.

## Verification behavior

A successful verification should prove actual NVIDIA authentication, not
merely that the key is non-empty.

A failed verification should distinguish useful classes such as:

-   missing credential;
-   authentication failure;
-   dependency missing;
-   network failure;
-   timeout;
-   provider/API error.

## Edge cases

### Invalid key

Should fail cleanly without storing it as a valid credential.

### Network unavailable

Should not misreport the key as invalid if the provider cannot be
reached.

### Provider rate limit

Should be reported as provider/rate-limit failure, not credential
failure.

### User declines verification

The tool should preserve the existing semantics for deferred
verification.

### User cancels

The operation should leave existing valid credentials unchanged.

------------------------------------------------------------------------

# 10. Phase F --- Verify Credential Persistence/Retrieval

## Problem

The generic keyring mechanism exists, but NVIDIA-specific persistence
must be demonstrated.

## Fix

Test the complete lifecycle:

``` text
session 1
  enter NVIDIA key
  verify
  store

exit

session 2
  select NVIDIA
  retrieve stored key
  verify/use
```

## Security

Prefer OS keyring storage where supported.

Do not silently downgrade to plaintext storage.

If the environment lacks keyring support, the CLI should clearly tell
the user what persistence behavior is available.

## Edge cases

-   Existing credential should not be overwritten without intentional
    replacement.
-   Invalid replacement key should not destroy a known-good stored
    credential.
-   Keyring unavailable should not crash the CLI.
-   Multiple providers must have separate credential namespaces.
-   NVIDIA credentials must not collide with OpenAI credentials.
-   Environment variable precedence must be deterministic if both
    environment and keyring credentials exist.

## Validation

Restart the CLI process.

Do not consider persistence proven while testing within one process.

------------------------------------------------------------------------

# 11. Phase G --- Isolated Real Kimi K3 Request

## Problem

Before running an entire PDF, prove that the provider stack itself
works.

## Fix

Send a minimal request through the project's actual provider
abstraction.

Do not bypass the adapter with an ad-hoc script for the final
verification.

The test should prove:

``` text
credential
→ registry
→ adapter
→ SDK
→ NVIDIA endpoint
→ Kimi K3
→ response
```

## Test cases

At minimum:

1.  text-only request;
2.  image request;
3.  malformed/empty response handling;
4.  authentication failure;
5.  timeout;
6.  rate-limit handling;
7.  provider error;
8.  credential redaction.

## Why isolate this?

If the full PDF conversion fails, we need to know whether the problem
is:

-   provider transport;
-   Kimi model;
-   routing;
-   page rendering;
-   prompt;
-   response parsing;
-   EPUB packaging.

An isolated request removes most of those variables.

------------------------------------------------------------------------

# 12. Phase H --- Real Six-Page Kimi Conversion

## Problem

The offline baseline proved the pipeline can work, but it did not prove
real AI inference.

## Fix

Run the exact same six-page PDF with:

``` text
provider = nvidia
model = moonshotai/kimi-k3
```

Do not change unrelated conversion settings.

Use a new filename, for example:

``` text
stage-kimi-k3.epub
```

## Record

Capture:

-   provider;
-   model;
-   routing counts;
-   elapsed time;
-   Tier-2 pages;
-   warnings;
-   validation results;
-   output size;
-   failures/retries if any.

## Edge cases

-   Kimi failure on one Tier-2 page.
-   API timeout.
-   rate limit.
-   empty response.
-   malformed model output.
-   one vision page succeeds while another fails.
-   provider returns text but not expected structured information.
-   retry behavior.

## Important

Do not silently fall back from Kimi to offline or another provider
unless the application's routing policy explicitly says so.

A real-provider failure should remain diagnosable.

------------------------------------------------------------------------

# 13. Phase I --- Compare Kimi EPUB Against Frozen Stage 0

## Problem

A successful API call does not prove better conversion quality.

## Fix

Compare:

``` text
Stage-0 offline EPUB
vs.
Kimi K3 EPUB
```

using the same source PDF.

Evaluate separately:

### Content fidelity

-   missing text;
-   duplicated text;
-   altered text;
-   reading order.

### Visual fidelity

-   images;
-   diagrams;
-   tables;
-   page composition.

### Semantic fidelity

-   headings;
-   lists;
-   links;
-   captions;
-   document structure.

### Accessibility

-   heading count;
-   alt text;
-   landmarks;
-   table semantics.

### Stability

-   deterministic output where expected;
-   malformed output;
-   provider failures.

## Important principle

Do not automatically declare Kimi "better" because it uses AI.

The goal is:

``` text
better semantic/reflow result
without sacrificing reliable content preservation.
```

------------------------------------------------------------------------

# 14. Phase J --- EPUBCheck and Ace

## Problem

Stage 0 reported:

``` text
PASS (not installed - skipped)
```

That is not an actual external validation result.

## Fix

Install the external validators in the development environment and run
them against:

1.  Stage-0 EPUB;
2.  Kimi EPUB.

## Validation semantics

The system should distinguish:

``` text
PASS
SKIPPED
WARN
FAIL
```

rather than representing "not installed" as a true validation pass.

## Edge cases

-   Java missing.
-   EPUBCheck missing.
-   Ace missing.
-   validator timeout.
-   malformed validator output.
-   non-zero exit code.
-   validator unavailable in CI.

## Why before semantic changes?

Because we need to know whether the existing EPUB structure is valid
before changing heading/metadata/navigation behavior.

------------------------------------------------------------------------

# 15. Phase K --- Fix Heading Semantics

## Problem

The source contains clear headings, while the generated EPUB reports
zero headings.

## Optimal scalable fix

Do not hard-code headings based on this one PDF.

Build on the existing document stream and style/structure information.

A scalable heading decision should combine available signals such as:

-   font size relative to body baseline;
-   font weight;
-   spacing before/after;
-   line length;
-   capitalization patterns;
-   isolated-line behavior;
-   repeated structural patterns;
-   PDF text-block geometry;
-   existing source metadata when available.

The result should map into semantic EPUB heading levels.

## Edge cases

### False positives

Do not turn:

-   short emphasized sentences;
-   table headers;
-   running headers;
-   page furniture

into document headings automatically.

### Deep hierarchy

Avoid generating arbitrary `h1`--`h6` jumps without a coherent
hierarchy.

### No confidence

Prefer paragraph semantics over a bad heading guess.

### Running headers

Repeated page-top text should not become dozens of headings.

## Validation

The test PDF should produce nonzero meaningful headings.

Add regression tests for:

-   true heading;
-   body text;
-   running header;
-   table header;
-   bold sentence;
-   nested headings.

------------------------------------------------------------------------

# 16. Phase L --- Improve Metadata and Title Extraction

## Problem

The converted EPUB was initially labeled:

``` text
Untitled Publication
```

despite meaningful title information being present in the source.

## Optimal scalable fix

Create a metadata extraction priority chain rather than relying on one
heuristic.

Possible priority:

``` text
embedded PDF metadata
→ document-level title signals
→ first-page title candidates
→ conservative fallback
```

Keep title extraction separate from heading extraction.

A title is not automatically an H1, and an H1 is not automatically the
publication title.

## Edge cases

-   Missing metadata.
-   Generic PDF metadata.
-   Incorrect metadata.
-   Multiple title candidates.
-   Cover page.
-   Title split across lines.
-   Author present but title absent.
-   Scanned first page.

## Fallback

If confidence is low:

``` text
Untitled Publication
```

is preferable to inventing a title.

------------------------------------------------------------------------

# 17. Phase M --- Improve TOC/Navigation

## Problem

The EPUB navigation currently reflects weak semantic structure.

## Fix

Generate EPUB navigation from validated semantic headings rather than
raw visual lines.

Conceptually:

``` text
document title
  ↓
H1
  ↓
H2
  ↓
H3
```

Only sufficiently confident structural headings should enter the
navigation.

## Edge cases

-   No headings.
-   One heading.
-   Duplicate headings.
-   Very deep nesting.
-   Repeated running headers.
-   Front matter.
-   Appendix.
-   Captions mistaken for headings.

## Dependency

This phase must happen **after heading semantics**.

Otherwise TOC work would encode the same bad classification logic a
second time.

------------------------------------------------------------------------

# 18. Phase N --- Normalize Dependency Metadata and Requirements

## Problem

Earlier inspection found `requirements.txt` and `pyproject.toml` were
not completely synchronized, including dependencies such as:

``` text
platformdirs
tomli
tomli-w
```

and the NVIDIA/OpenAI SDK relationship.

## Optimal fix

Establish one authoritative dependency declaration in the packaging
metadata.

Generate or maintain secondary requirement files from that source when
practical.

Do not maintain two independently editable dependency lists.

## Edge cases

-   Python-version-specific dependencies.
-   Optional provider extras.
-   Development/test dependencies.
-   Distribution install.
-   Clean virtual environment.
-   Editable install.
-   Wheel installation.
-   sdist installation.

## Important sequencing

This happens after the provider path has been proven, because changing
packaging metadata before understanding the real dependency graph risks
obscuring the initial NVIDIA debugging.

------------------------------------------------------------------------

# 19. Phase O --- Clean README and User-Facing Provider Documentation

## Problem

The actual workflow is now more sophisticated than the old
documentation.

The documentation should explain:

``` text
pdf2epub convert
pdf2epub interactive
pdf2epub doctor
pdf2epub validators
/provider
/model
```

and the distinction between:

``` text
provider
model
SDK dependency
API credential
```

## NVIDIA example

The documentation should clearly say:

``` text
Provider: NVIDIA
Model: moonshotai/kimi-k3
Credential: NVIDIA_API_KEY
Client dependency: OpenAI Python SDK
```

It should not imply that users need an OpenAI API key.

## Edge cases

Document:

-   missing optional SDKs;
-   missing validators;
-   keyring unavailable;
-   offline mode;
-   provider verification;
-   model selection;
-   exit codes;
-   network failures.

## Why after implementation?

Documentation should describe verified behavior, not intended behavior.

------------------------------------------------------------------------

# 20. Phase P --- Real-Provider Integration Tests

## Problem

Adapter unit tests are not enough.

The system needs tests around the actual user workflow.

## Test layers

### Layer 1 --- unit

Provider adapter construction.

### Layer 2 --- registry

Provider/model resolution.

### Layer 3 --- credential

Credential retrieval and redaction.

### Layer 4 --- CLI

Interactive provider/model selection.

### Layer 5 --- integration

Real provider request.

### Layer 6 --- conversion

Real provider through Tier 2.

### Layer 7 --- regression

Output quality against known PDFs.

## Real API tests

Real-provider tests should be environment-gated.

For example:

``` text
NVIDIA_API_KEY present
```

means the live test can run.

Without it:

``` text
SKIPPED
```

not failed.

## Important

Never put a real API key in CI configuration committed to the
repository.

------------------------------------------------------------------------

# 21. Phase Q --- Expand the Regression Corpus

## Problem

The six-page PDF is valuable but insufficient.

## Recommended corpus

### A. Text-heavy PDF

Tests deterministic extraction.

### B. Multi-column PDF

Tests reading order.

### C. Scanned PDF

Tests image/OCR strategy.

### D. Complex tables

Tests table preservation.

### E. Diagrams/charts

Tests vision routing.

### F. Academic paper

Tests headings, references, footnotes.

### G. Magazine-style PDF

Tests furniture, columns, mixed media.

### H. Long document

Tests performance and memory.

### I. Poor-quality PDF

Tests failure handling.

### J. Mixed document

Tests Tier 1 + Tier 2 interaction.

## Regression rule

Every significant conversion change should be evaluated against the
corpus.

Do not optimize against only the original six-page PDF.

------------------------------------------------------------------------

# 22. Dependency/Contamination Control

The following changes should remain separated.

  -----------------------------------------------------------------------
  Change                  Must happen before      Must not be combined
                                                  with
  ----------------------- ----------------------- -----------------------
  SDK dependency metadata provider verification   semantic EPUB changes

  Doctor detection        provider verification   model-quality changes

  NVIDIA registry         Kimi selection          heading redesign

  Kimi catalog            real request            metadata redesign

  Credential persistence  full conversion         unrelated packaging
                                                  cleanup

  Real provider request   full Kimi conversion    heading changes

  Kimi conversion         quality comparison      metadata redesign

  External validators     semantic changes        provider refactor

  Heading semantics       TOC                     dependency refactor

  Metadata extraction     TOC                     provider refactor

  TOC                     documentation           provider refactor

  Dependency              final packaging         conversion-engine
  normalization                                   redesign

  Documentation           release/maturity        speculative features

  Integration tests       maturity gate           broad refactor

  Regression corpus       maturity gate           untested architecture
                                                  rewrite
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 23. Recommended Commit Boundaries

A clean implementation can use approximately these commits:

``` text
1. Fix provider SDK dependency metadata and doctor detection

2. Normalize NVIDIA provider registration

3. Register NVIDIA Kimi K3 catalog model

4. Verify/fix NVIDIA credential lifecycle

5. Add isolated real NVIDIA/Kimi integration coverage

6. Establish Kimi K3 end-to-end conversion regression

7. Enable and record EPUBCheck/Ace validation

8. Improve semantic heading extraction

9. Improve publication metadata extraction

10. Improve EPUB navigation/TOC

11. Normalize dependency declarations and installation metadata

12. Refresh README/provider documentation

13. Add gated real-provider integration tests

14. Expand PDF regression corpus
```

The exact number of commits can differ, but the **logical boundaries
should remain**.

------------------------------------------------------------------------

# 24. Definition of Done

The Kimi/NVIDIA milestone is complete only when all of these are true:

-   [ ] NVIDIA dependency is correctly declared.
-   [ ] `doctor` detects NVIDIA's dependency state.
-   [ ] NVIDIA is a normal user-facing provider.
-   [ ] `moonshotai/kimi-k3` resolves from the catalog.
-   [ ] NVIDIA API key can be entered through the tool.
-   [ ] Credential verification succeeds with a valid key.
-   [ ] Invalid credentials fail safely.
-   [ ] Credentials can persist through the supported mechanism.
-   [ ] A new CLI process can retrieve the stored credential.
-   [ ] A real Kimi K3 request succeeds.
-   [ ] A multimodal request succeeds.
-   [ ] The six-page PDF completes through Kimi.
-   [ ] No provider-specific Kimi logic has leaked into Tier 2/engine
    code.
-   [ ] Stage-0 remains unchanged as the regression baseline.
-   [ ] Kimi output is compared against Stage 0.
-   [ ] EPUBCheck is actually run.
-   [ ] Ace is actually run where supported.
-   [ ] Validation distinguishes PASS from SKIPPED.
-   [ ] No credential is exposed in logs/reports/tests.

The semantic-quality milestone is complete only after:

-   [ ] meaningful headings are represented semantically;
-   [ ] publication title metadata is extracted conservatively;
-   [ ] navigation derives from validated headings;
-   [ ] dependency declarations are consistent;
-   [ ] documentation matches verified behavior;
-   [ ] real-provider integration tests are gated and safe;
-   [ ] the regression corpus contains multiple PDF classes.

------------------------------------------------------------------------

# 25. Final Recommended Work Order

The cleanest practical sequence is therefore:

## Stage 1 --- Infrastructure correctness

``` text
Freeze baseline
→ fix SDK dependency metadata
→ fix doctor
→ verify provider registry
→ register Kimi
```

Stop and test.

## Stage 2 --- Credential correctness

``` text
Enter NVIDIA key
→ verify
→ persist
→ restart
→ retrieve
→ verify again
```

Stop and test.

## Stage 3 --- Provider correctness

``` text
isolated Kimi request
→ multimodal Kimi request
→ error handling
```

Stop and test.

## Stage 4 --- Conversion correctness

``` text
six-page PDF
→ Kimi conversion
→ frozen Stage-0 comparison
```

Stop and evaluate.

## Stage 5 --- EPUB validation

``` text
EPUBCheck
→ Ace
→ classify actual failures
```

Stop before semantic changes.

## Stage 6 --- Semantic quality

``` text
heading extraction
→ metadata
→ TOC/navigation
```

Each separately tested.

## Stage 7 --- Project maturity

``` text
dependency normalization
→ documentation
→ integration tests
→ broader PDF corpus
→ final regression
```

------------------------------------------------------------------------

# 26. Principle Behind the Sequence

The most important design principle is:

> **First prove that the system can reliably call the intended model.
> Then prove that the model improves or preserves conversion quality.
> Only after that improve semantic EPUB quality.**

This prevents three kinds of contamination:

### Provider contamination

A Kimi API problem is not mistaken for a PDF-conversion problem.

### Conversion contamination

A heading/metadata refactor does not obscure whether Kimi itself works.

### Packaging contamination

Dependency cleanup does not obscure whether the provider adapter works.

The result is a controlled progression:

``` text
Stable offline baseline
        ↓
Correct provider infrastructure
        ↓
Correct credentials
        ↓
Correct model resolution
        ↓
Real Kimi request
        ↓
Real Kimi conversion
        ↓
Measured comparison
        ↓
Validated EPUB
        ↓
Semantic improvements
        ↓
Documentation + tests
        ↓
Mature release candidate
```

That is the recommended path for the current project.
