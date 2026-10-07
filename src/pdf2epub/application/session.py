"""Interactive session state and readiness.

Pure state, no I/O: the command layer (Phase 12) and the REPL (Phase 14)
mutate a Session through its methods -- which carry the invalidation
rules -- and read its deterministic readiness. Nothing here opens files,
prints, or touches the network.

Secret hygiene: ``explicit_secret`` is an in-session manual key. It never
reaches logs, prompts, or disk, and it is cleared whenever the provider
changes (a key for one provider must never be offered to another).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..config.credentials import CredentialResolutionResult, resolve_for_profile
from ..providers.requirements import check_model_for_routes, resolve_model
from .models import ConversionOptions, ConversionRequest
from .preflight import PreflightResult


class Readiness(Enum):
    READY = "ready"
    READY_WITH_PREFLIGHT_REQUIRED = "ready_with_preflight_required"
    NOT_READY = "not_ready"


@dataclass(frozen=True)
class ReadinessReport:
    state: Readiness
    missing: list[str] = field(default_factory=list)


@dataclass
class Session:
    pdf_path: Path | None = None
    title: str | None = None        # None -> PDF metadata -> engine default
    author: str | None = None
    output_path: Path | None = None
    output_auto: bool = False       # True while the output name is derived from the PDF
    provider_id: str | None = None  # None -> not chosen; "none" -> explicit offline
    credential: CredentialResolutionResult | None = None
    explicit_secret: str | None = None  # in-session only
    conversion_model: str | None = None
    overwrite: bool = False
    quiet: bool = False  # transcript-only switch: options.quiet, never warnings
    last_routing: PreflightResult | None = None

    @classmethod
    def from_config(cls, config) -> "Session":
        """Seed the provider/model tier of the precedence chain (CLI > session > config > default)."""
        return cls(
            provider_id=config.provider_name,
            conversion_model=config.conversion_model,
        )

    # -- mutators carrying the invalidation rules --------------------------
    def select_pdf(self, path, *, title, author, output_dir=".") -> None:
        self.pdf_path = Path(path)
        self.title = title
        self.author = author
        if self.output_path is None or self.output_auto:
            directory = Path(output_dir) if output_dir else Path(".")
            self.output_path = directory / f"{self.pdf_path.stem}.epub"
            self.output_auto = True
        self.last_routing = None  # routing belongs to the previous document

    def set_output(self, path, *, overwrite: bool = False) -> None:
        self.output_path = Path(path)
        self.output_auto = False
        self.overwrite = overwrite

    def select_provider(self, provider_id: str) -> None:
        """Changing provider invalidates everything provider-specific.

        Clears the model, the resolved credential, the in-session manual
        secret (so a key for one provider can never leak to another), and
        the routing plan (online/offline flips change required routes).
        """
        self.provider_id = provider_id
        self.conversion_model = None
        self.credential = None
        self.explicit_secret = None
        self.last_routing = None

    def select_model(self, model_id: str) -> None:
        self.conversion_model = model_id

    def set_explicit_secret(self, secret: str | None) -> None:
        self.explicit_secret = secret
        self.credential = None  # refreshed lazily by refresh_credential

    def refresh_credential(self, registry, *, environ=None) -> CredentialResolutionResult | None:
        """Resolve the credential for the current provider (local only)."""
        self.credential = None
        if self.provider_id in (None, "none"):
            return None
        if self.explicit_secret:
            self.credential = CredentialResolutionResult(
                self.explicit_secret, "explicit", self.provider_id, None
            )
            return self.credential
        try:
            adapter = registry.get(self.provider_id)
        except KeyError:
            return None
        profile = getattr(adapter, "profile", None)
        if profile is None:
            return None
        self.credential = resolve_for_profile(profile, environ=environ)
        return self.credential

    # -- readiness ---------------------------------------------------------
    def _credential_available(self) -> bool:
        if self.explicit_secret:
            return True
        return (
            self.credential is not None
            and self.credential.source != "unavailable"
        )

    def readiness(self, registry) -> ReadinessReport:
        """Deterministic readiness; never a false green."""
        gaps: list[str] = []
        if self.pdf_path is None:
            gaps.append("PDF not selected (/select)")
        if self.output_path is None:
            gaps.append("output path not set (/export)")
        if self.provider_id is None:
            gaps.append("provider not chosen (/provider)")
        elif self.provider_id != "none":
            if not self._credential_available():
                env_hint = self._credential_env_var(registry)
                suffix = f" (set {env_hint} or use /provider)" if env_hint else " (use /provider)"
                gaps.append(f"no credential for {self.provider_id!r}{suffix}")
            if not self.conversion_model:
                gaps.append("model not selected (/model)")
            elif self.last_routing is not None:
                definition = self._model_definition(registry)
                if definition is not None:
                    gaps.extend(
                        check_model_for_routes(
                            definition, self.last_routing.required_routes
                        )
                    )
        if gaps:
            return ReadinessReport(Readiness.NOT_READY, gaps)
        if self.provider_id != "none" and self.last_routing is None:
            return ReadinessReport(Readiness.READY_WITH_PREFLIGHT_REQUIRED, [])
        return ReadinessReport(Readiness.READY, [])

    def _credential_env_var(self, registry) -> str | None:
        if not self.provider_id:
            return None
        try:
            adapter = registry.get(self.provider_id)
        except KeyError:
            return None
        profile = getattr(adapter, "profile", None)
        return profile.credential_env_var if profile else None

    def _model_definition(self, registry):
        if not self.conversion_model:
            return None
        try:
            adapter = registry.get(self.provider_id)
        except KeyError:
            return None
        return resolve_model(adapter, self.conversion_model).definition

    # -- request -----------------------------------------------------------
    def build_request(self) -> ConversionRequest:
        if self.pdf_path is None or self.output_path is None:
            raise ValueError("session is not ready: PDF and output are required")
        return ConversionRequest(
            pdf_path=self.pdf_path,
            output_path=self.output_path,
            title=self.title,
            author=self.author,
            provider_id=self.provider_id or "none",
            conversion_model=self.conversion_model,
            options=ConversionOptions(overwrite=self.overwrite, quiet=self.quiet),
        )
