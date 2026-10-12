"""Environment diagnostics for the CLI, REPL and CI.

Every system probe goes through one mockable seam; doctor performs **no
network operations** unless ``verify_credentials=True`` is passed
explicitly (the only path that contacts a provider).

States: ``OK`` / ``WARN`` (informational problem) / ``FAIL`` (hard problem)
/ ``OPTIONAL`` (not installed and not required). A missing Java/Node or
external validator is never a FAIL -- optional tooling must not fail CI.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ..config.credentials import resolve_for_profile
from ..config.manager import CURRENT_SCHEMA_VERSION
from ..engine import packaging_and_validation as pk
from ..providers.requirements import check_model_for_routes, resolve_model
from ..validators.base import ValidatorState, states_from
from ..validators.onboarding import validator_enabled
from ..validators.registry import build_validator_registry

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"
OPTIONAL = "OPTIONAL"

_VERSION_TIMEOUT = 10


@dataclass(frozen=True)
class CheckResult:
    name: str
    state: str
    detail: str = ""


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(check.state == FAIL for check in self.checks)

    def render(self) -> str:
        return "\n".join(
            f"{check.name:<22} {check.state:<8} {check.detail}"
            for check in self.checks
        )


# -- mockable probes ---------------------------------------------------------


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _probe_version(cmd: list[str], timeout: int = _VERSION_TIMEOUT) -> tuple[bool, str]:
    """Best-effort version probe; tests mock this, never Java/Node."""
    try:
        proc = pk._run_with_tree_kill(cmd, timeout)
    except Exception as exc:
        return False, type(exc).__name__
    lines = (proc.stdout or proc.stderr or "").strip().splitlines()
    if proc.returncode != 0:
        return False, lines[0] if lines else f"exit {proc.returncode}"
    return True, lines[0] if lines else ""


# -- the checks --------------------------------------------------------------


def run_doctor(
    *,
    registry,
    config_manager,
    environ=None,
    session=None,
    validator_registry=None,
    verify_credentials: bool = False,
) -> DoctorReport:
    checks: list[CheckResult] = []
    validators = (
        validator_registry
        if validator_registry is not None
        else build_validator_registry()
    )
    config = config_manager.load()

    # -- runtime -----------------------------------------------------------
    py = sys.version_info
    checks.append(
        CheckResult(
            "python",
            OK if py >= (3, 10) else WARN,
            f"{py.major}.{py.minor}.{py.micro}",
        )
    )

    missing_core = [
        name for name in ("pymupdf", "ebooklib", "lxml") if not _module_available(name)
    ]
    checks.append(
        CheckResult(
            "core packages",
            FAIL if missing_core else OK,
            "missing: " + ", ".join(missing_core) if missing_core else "pymupdf, ebooklib, lxml",
        )
    )

    # Provider SDK requirements are derived from the registry (profile
    # metadata), never a hardcoded module list: one SDK shared by several
    # providers gets a single grouped row naming every consumer, and each
    # consumer keeps its own install extra. Dependency availability is a
    # separate concept from credential availability (checked below).
    sdk_consumers: dict[str, list[str]] = {}
    sdk_extras: dict[str, set[str]] = {}
    for adapter in registry.list():
        profile = getattr(adapter, "profile", None)
        dep = getattr(profile, "client_dependency", None) if profile else None
        if dep is None:
            continue
        sdk_consumers.setdefault(dep, []).append(adapter.provider_id)
        extra = getattr(profile, "install_extra", None)
        if extra is not None:
            sdk_extras.setdefault(dep, set()).add(extra)
    for dep, provider_ids in sdk_consumers.items():
        present = _module_available(dep)
        if present:
            detail = f"installed (providers: {', '.join(provider_ids)})"
        else:
            install = " or ".join(
                f"pdf2epub[{extra}]" for extra in sorted(sdk_extras.get(dep, ()))
            )
            detail = (
                f"not installed (needed for providers: {', '.join(provider_ids)})"
                + (f"; install: {install}" if install else "")
            )
        checks.append(CheckResult(f"{dep} SDK", OK if present else OPTIONAL, detail))

    keyring_present = _module_available("keyring")
    checks.append(
        CheckResult(
            "keyring",
            OK if keyring_present else OPTIONAL,
            "installed"
            if keyring_present
            else "not installed (needed for OS keyring persistence)",
        )
    )

    # -- system tools ------------------------------------------------------
    for name, probe in (("java", "-version"), ("node", "--version")):
        resolved = pk.resolve_tool(name)
        if resolved is None:
            checks.append(CheckResult(name, OPTIONAL, "not installed"))
            continue
        ok, version = _probe_version([resolved, probe])
        checks.append(CheckResult(name, OK if ok else WARN, version or resolved))

    # -- external validators ----------------------------------------------
    for validator in validators.list():
        enabled = validator_enabled(validator.id, config)
        outcome = validator.detect()
        state = states_from(outcome, enabled=enabled)
        display = {
            ValidatorState.AVAILABLE: OK,
            ValidatorState.DISABLED: OPTIONAL,
            ValidatorState.UNAVAILABLE: OPTIONAL,
            ValidatorState.REQUIRED_BUT_MISSING: WARN,
            ValidatorState.FAILED_TO_RUN: WARN,
        }[state]
        if not enabled:
            detail = "disabled in configuration"
        else:
            detail = outcome.version or outcome.detail or state.value
        checks.append(CheckResult(validator.display_name, display, detail))

    # -- configuration -----------------------------------------------------
    config_path = Path(config_manager.path())
    if not config_path.exists():
        checks.append(CheckResult("config", OK, "no file yet (defaults in use)"))
    else:
        try:
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            checks.append(
                CheckResult("config", WARN, f"invalid TOML ({type(exc).__name__})")
            )
        else:
            version = data.get("schema_version", 0)
            if isinstance(version, int) and version > CURRENT_SCHEMA_VERSION:
                checks.append(
                    CheckResult(
                        "config", WARN, "written by a newer pdf2epub"
                    )
                )
            else:
                checks.append(CheckResult("config", OK, str(config_path)))

    output_dir = Path(config.output_directory or ".")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        checks.append(CheckResult("output directory", OK, str(output_dir)))
    except OSError as exc:
        checks.append(CheckResult("output directory", WARN, f"not writable: {exc}"))

    # -- provider credential environment variables (state 1) ---------
    # A key set in the environment is a fact *independent* of provider
    # selection. "NVIDIA_API_KEY is set" and "no provider configured"
    # are different states: a user who exported a key must see it
    # registered even while the tool runs offline, and must never be
    # told "no provider configured (offline)" as if the key did not
    # exist. One row per distinct credential variable, never per
    # provider, so a variable shared by two providers is listed once.
    env_map = environ if environ is not None else os.environ
    seen_vars: set[str] = set()
    for adapter in registry.list():
        profile = getattr(adapter, "profile", None)
        var = getattr(profile, "credential_env_var", None) if profile else None
        if not var or var in seen_vars:
            continue
        seen_vars.add(var)
        present = bool(str(env_map.get(var, "")).strip())
        checks.append(
            CheckResult(
                f"env {var}",
                OK if present else OPTIONAL,
                "set" if present else "not set",
            )
        )

    # -- credentials (local only unless verify_credentials) ----------------
    provider_id = session.provider_id if session is not None else config.provider_name
    explicit_secret = session.explicit_secret if session is not None else None
    # The configured provider's SDK is checked before any credential claim:
    # a missing dependency must not first surface at verification time,
    # and it is reported as its own check so a missing key stays distinct
    # from a missing package.
    if provider_id not in (None, "none"):
        try:
            adapter = registry.get(provider_id)
        except KeyError:
            adapter = None
        if adapter is not None:
            profile = getattr(adapter, "profile", None)
            dep = getattr(profile, "client_dependency", None) if profile else None
            if dep is not None and not _module_available(dep):
                extra = getattr(profile, "install_extra", None)
                hint = (
                    f"pip install 'pdf2epub[{extra}]'" if extra else f"pip install {dep}"
                )
                checks.append(
                    CheckResult(
                        "provider SDK",
                        WARN,
                        f"the {dep!r} package is required for provider "
                        f"{provider_id!r}: {hint}",
                    )
                )
    if provider_id in (None, "none"):
        checks.append(
            CheckResult("credentials", OPTIONAL, "no provider configured (offline)")
        )
    elif explicit_secret:
        checks.append(CheckResult("credentials", OK, "manual key (this session)"))
        if verify_credentials:
            try:
                adapter = registry.get(provider_id)
            except KeyError:
                adapter = None
            if adapter is not None:
                try:
                    ok = adapter.validate_credentials(explicit_secret)
                except Exception as exc:
                    checks.append(
                        CheckResult("credential verification", WARN, str(exc))
                    )
                else:
                    checks.append(
                        CheckResult(
                            "credential verification",
                            OK if ok else FAIL,
                            "verified" if ok else "rejected by the provider",
                        )
                    )
                    _append_model_request_check(
                        checks,
                        adapter,
                        _selected_model(session, config),
                        explicit_secret,
                    )
    else:
        try:
            adapter = registry.get(provider_id)
        except KeyError:
            adapter = None
        if adapter is None:
            checks.append(
                CheckResult("credentials", WARN, f"unknown provider {provider_id!r}")
            )
        else:
            profile = getattr(adapter, "profile", None)
            if profile is None:
                checks.append(
                    CheckResult("credentials", WARN, "provider exposes no credential profile")
                )
            else:
                resolved = resolve_for_profile(profile, environ=environ)
                if resolved.source == "unavailable":
                    checks.append(
                        CheckResult(
                            "credentials", WARN, f"missing (set {profile.credential_env_var})"
                        )
                    )
                else:
                    checks.append(
                        CheckResult("credentials", OK, f"from {resolved.source}")
                    )
                    if verify_credentials:
                        try:
                            ok = adapter.validate_credentials(resolved.credential)
                        except Exception as exc:
                            checks.append(
                                CheckResult("credential verification", WARN, str(exc))
                            )
                        else:
                            checks.append(
                                CheckResult(
                                    "credential verification",
                                    OK if ok else FAIL,
                                    "verified" if ok else "rejected by the provider",
                                )
                            )
                            _append_model_request_check(
                                checks,
                                adapter,
                                _selected_model(session, config),
                                resolved.credential,
                            )

    # -- model vs last routing (session-aware) -----------------------------
    if (
        session is not None
        and session.provider_id not in (None, "none")
        and session.conversion_model
        and session.last_routing is not None
    ):
        try:
            adapter = registry.get(session.provider_id)
        except KeyError:
            adapter = None
        if adapter is not None:
            resolution = resolve_model(adapter, session.conversion_model)
            if resolution.definition is None:
                checks.append(
                    CheckResult("model fit", WARN, resolution.warning or "unknown model")
                )
            else:
                problems = check_model_for_routes(
                    resolution.definition, session.last_routing.required_routes
                )
                checks.append(
                    CheckResult(
                        "model fit",
                        WARN if problems else OK,
                        "; ".join(problems) if problems else "compatible with last routing",
                    )
                )

    return DoctorReport(checks)


def _selected_model(session, config) -> str | None:
    """The model the user actually selected: session overrides config."""
    if session is not None and getattr(session, "conversion_model", None):
        return session.conversion_model
    return getattr(config, "conversion_model", None) or None


def _append_model_request_check(
    checks: list[CheckResult], adapter, model: str | None, credential: str
) -> None:
    """State 4: can the selected model actually complete a request?

    Credential validation (state 3) proves the key; only a completed
    request proves the model id, the endpoint and the quota together.
    Opt-in by design -- this is a real network call, so it runs only
    under ``--verify-credentials``, exactly like credential
    verification itself.
    """
    if not model:
        checks.append(
            CheckResult(
                "model request",
                WARN,
                "no model selected (pass --model or configure one)",
            )
        )
        return
    try:
        client = adapter.create_llm_callable(model, credential)
        reply = client(
            "You are a connectivity probe.",
            "Reply with the single word: ready",
            None,
        )
    except Exception as exc:
        checks.append(
            CheckResult("model request", FAIL, f"request failed: {exc}")
        )
        return
    if reply and str(reply).strip():
        checks.append(
            CheckResult("model request", OK, f"{model} completed a request")
        )
    else:
        checks.append(
            CheckResult("model request", FAIL, "model returned an empty response")
        )
