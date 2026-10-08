# Stage-0 Frozen Regression Baseline

Offline conversion baseline recorded 2026-10-08 (Phase A of the original
stabilization sequence; the sequencing plan itself has since been
retired — its outcome lives in
[kimi_k3_conversion_record.md](kimi_k3_conversion_record.md) and
[remediation_record.md](remediation_record.md)).

## Freeze rule

The baseline EPUB is frozen. It is never overwritten; later conversions
use different output names. If it must ever be regenerated, the
regeneration is a *new* baseline and must be recorded here with new
hashes and the reason for the change.

## Artifacts (kept outside the repository)

Neither artifact is committed (`.gitignore` excludes `*.pdf` / `*.epub`).
The SHA-256 hashes are the artifact identity; filesystem locations are
intentionally not recorded because they are machine-specific. Keep any
local-only path notes in an uncommitted file.

Source PDF

- logical name: `Artificial_Intelligence_Projects.pdf`
- location: external to repository (not committed)
- SHA-256: `369B95FE20C4511B2BB29A6C3A66EE7FE561991273B5320DF65461544AA9638D`
- pages: 6
- embedded PDF title metadata: absent

Baseline EPUB

- logical name: `stage0.epub`
- location: external to repository (not committed)
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

```powershell
Get-FileHash -Algorithm SHA256 <baseline-epub> <source-pdf>
pdf2epub doctor
pdf2epub convert <source-pdf> -o stage0-regression.epub --provider none
```
