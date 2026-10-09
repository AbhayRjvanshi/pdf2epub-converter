# Stage-0 Frozen Regression Baseline

Offline conversion baseline recorded 2026-10-08 (Phase A of the original
stabilization sequence; the sequencing plan itself has since been
retired — its outcome lives in
[kimi_k3_conversion_record.md](kimi_k3_conversion_record.md) and
[remediation_record.md](remediation_record.md)).

## Freeze rule

The baseline EPUB is frozen. It is never overwritten; later conversions
use different output names. If it must ever be regenerated, the
regeneration is a *new* baseline and must be recorded **separately**
with its own hashes, provenance and the reason for the change — this
record keeps the historical Stage-0 measurements untouched.

## Artifact status: retired, record preserved (2026-10-09)

The baseline EPUB (`stage0.epub`) and the later Kimi comparison EPUB
(`stage-kimi-k3.epub`) were removed from local storage during a
workspace cleanup and are **no longer available**. They have not been
recovered. This record is therefore historical evidence, not a live
artifact pointer:

- the hashes and metrics below are the measurements taken while the
  artifacts existed, and remain the authoritative record of what
  Stage 0 produced;
- the *source PDF* still exists and is unchanged (its hash was
  re-verified against this record on 2026-10-09);
- any future conversion of that source is a **new baseline** with its
  own hash and provenance — it must never be written into this record
  or presented as a reproduction of Stage 0. The current converter's
  behavior is documented in
  [remediation_record.md](remediation_record.md).

## Artifacts (kept outside the repository)

Neither artifact is committed (`.gitignore` excludes `*.pdf` / `*.epub`).
The SHA-256 hashes are the artifact identity; filesystem locations are
intentionally not recorded because they are machine-specific. Keep any
local-only path notes in an uncommitted file.

Source PDF — **still present, unchanged**

- logical name: `Artificial_Intelligence_Projects.pdf`
- location: external to repository (not committed)
- SHA-256: `369B95FE20C4511B2BB29A6C3A66EE7FE561991273B5320DF65461544AA9638D`
- pages: 6
- embedded PDF title metadata: absent

Baseline EPUB — **no longer on disk; hash retained for identity**

- logical name: `stage0.epub`
- location: external to repository (not committed); removed from local
  storage before this note — retirement recorded above
- SHA-256: `6EA59E6174FAC41705A31260DC9134F55D1C769165C69477D7E7A432124E2834`
- `dc:title`: `Untitled Publication`

## Provenance

```text
provider: none
model: offline/default
input:   six-page source PDF above
output:  baseline EPUB above
```

## Observed Stage-0 metrics

Recorded at conversion time and verified against the artifact:

```text
routing:      tier1=4, tier2-digest=1, tier2-vision=1
packaging:    79 stream elements, 1 chapter,
              0 cross-page welds, 0 furniture lines stripped
accessibility: headings=0, images=1, alt_text=yes
validation:   PASS (not installed - skipped)   [pre-Phase-J rendering]
```

## Verification commands

The baseline EPUB can no longer be hashed; what can still be verified:

```powershell
# source PDF identity (still valid)
Get-FileHash -Algorithm SHA256 <source-pdf>
pdf2epub doctor
```

A fresh conversion is a *new* baseline, never a reproduction of this
one:

```powershell
pdf2epub convert <source-pdf> -o <new-name>.epub --provider none
```
