"""The application conversion contract.

Explicit by design: no credentials (resolved separately, Phase 5) and no
config merging (Phase 9/10 compose defaults). The option set keeps full
parity with the legacy CLI so nothing disappears in the migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ConversionOptions:
    batch_size: int = 4
    cache_dir: str | None = None  # None -> platform default (Phase 9)
    max_repair_attempts: int = 2
    skip_validation: bool = False
    report_only: bool = False
    font_sample_pages: int = 160
    spool_images: bool = True
    quiet: bool = False  # presentation concern, accepted here in v1
    overwrite: bool = False  # decision A1: refuse to clobber by default
    max_tier2_pages: int | None = None  # spend cap; None = uncapped


@dataclass(frozen=True)
class ConversionRequest:
    pdf_path: Path
    output_path: Path
    title: str | None = None  # None -> PDF metadata -> engine default
    author: str | None = None
    language: str | None = None  # None -> PDF /Lang -> 'und' (engine policy)
    provider_id: str = "none"  # decision #5
    conversion_model: str | None = None
    options: ConversionOptions = field(default_factory=ConversionOptions)

    def __post_init__(self) -> None:
        # frozen-safe coercion so callers may pass str paths
        object.__setattr__(self, "pdf_path", Path(self.pdf_path))
        object.__setattr__(self, "output_path", Path(self.output_path))
