"""Interactive command layer: parser x command x session.

UI-independent: every command reads and writes through an injected IO
object, so the whole layer is testable with scripted input and no TTY.
The REPL (Phase 14) supplies ConsoleIO and a loop; Phase 13 registers
/validators and /doctor into the same dispatch table.

Secret hygiene: a manual key flows from ``read_secret()`` into the session
and into ``service.convert(explicit_secret=...)`` and nowhere else --
never into prompts, written output, logs, or the config file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - legacy alias
    import fitz

from ..config.credentials import keyring_store, resolve_for_profile
from ..providers.errors import ProviderError
from ..providers.requirements import check_model_for_routes, resolve_model
from .session import Readiness, Session


# ---------------------------------------------------------------------------
# IO boundary
# ---------------------------------------------------------------------------


class IO(Protocol):
    """The interactive boundary. Phase 14 provides the console version."""

    def read_line(self, prompt: str) -> str: ...

    def read_secret(self, prompt: str) -> str: ...

    def write(self, text: str) -> None: ...


@dataclass
class CommandResult:
    output: str = ""
    exit: bool = False
    failed: bool = False


@dataclass
class SessionDeps:
    """Every collaborator is injected; tests build fakes."""

    registry: object
    config_manager: object            # .load() / .save() / .path()
    service_factory: Callable         # () -> ConversionService
    environ: Mapping[str, str] | None = None


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

_COMMANDS: dict[str, tuple[Callable, str]] = {}


def _command(verb: str, help_text: str) -> Callable:
    def decorate(handler: Callable) -> Callable:
        _COMMANDS[verb] = (handler, help_text)
        return handler

    return decorate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("y", "yes")


def _read_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        doc = fitz.open(str(path))
    except Exception:
        return None, None
    try:
        meta = doc.metadata or {}
    finally:
        doc.close()
    title = (meta.get("title") or "").strip() or None
    author = (meta.get("author") or "").strip() or None
    return title, author


def _credential_label(session: Session) -> str:
    if session.explicit_secret:
        return "manual (this session)"
    if session.credential is not None and session.credential.source != "unavailable":
        return session.credential.source
    return "not available"


def _select_from(entries: list[tuple[str, str]], raw: str) -> str | None:
    """Number or id; None when the selection matches nothing."""
    raw = raw.strip()
    if raw.isdigit() and 1 <= int(raw) <= len(entries):
        return entries[int(raw) - 1][0]
    if raw in {pid for pid, _ in entries}:
        return raw
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@_command("help", "show this help")
def _help(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    lines = ["Available commands:"]
    lines += [f"  /{verb:<9} {text}" for verb, (_, text) in sorted(_COMMANDS.items())]
    return CommandResult(output="\n".join(lines))


@_command("select", "choose the input PDF")
def _select(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    raw = io.read_line("PDF path: ").strip()
    if not raw:
        return CommandResult(output="select cancelled", failed=True)
    path = Path(raw).expanduser()
    if not path.exists():
        return CommandResult(output=f"input not found: {path}", failed=True)
    if not path.is_file():
        return CommandResult(output=f"not a file: {path}", failed=True)

    meta_title, meta_author = _read_metadata(path)
    if meta_title is None and meta_author is None:
        io.write("warning: no readable metadata; title/author will use engine defaults")

    title = io.read_line(f"Title [leave empty for {meta_title or 'PDF metadata'}]: ").strip() or None
    author = io.read_line(f"Author [leave empty for {meta_author or 'PDF metadata'}]: ").strip() or None

    output_dir = "."
    try:
        output_dir = deps.config_manager.load().output_directory or "."
    except Exception:
        pass
    session.select_pdf(path, title=title, author=author, output_dir=output_dir)
    return CommandResult(
        output=(
            f"selected: {path}\n"
            f"title:   {title or meta_title or '(metadata)'}\n"
            f"author:  {author or meta_author or '(metadata)'}\n"
            f"output:  {session.output_path}"
        )
    )


@_command("export", "choose the output EPUB path")
def _export(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    raw = io.read_line("Output path: ").strip()
    if not raw:
        return CommandResult(output="export cancelled", failed=True)
    path = Path(raw).expanduser()
    if path.is_dir():
        return CommandResult(output=f"output path is a directory: {path}", failed=True)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CommandResult(output=f"cannot create {path.parent}: {exc}", failed=True)

    overwrite = False
    if path.exists():
        overwrite = _yes(io.read_line(f"{path} exists - overwrite? (y/N): "))
        if not overwrite:
            session.set_output(path, overwrite=False)
            return CommandResult(
                output=(
                    f"output kept: {path}\n"
                    "existing file will NOT be overwritten; /convert will "
                    "refuse unless you allow overwrite here"
                ),
                failed=True,
            )
    session.set_output(path, overwrite=overwrite)
    return CommandResult(output=f"output: {path}" + (" (overwrite allowed)" if overwrite else ""))


@_command("provider", "choose and authenticate an AI provider")
def _provider(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    entries = []
    for adapter in deps.registry.list():
        profile = getattr(adapter, "profile", None)
        label = getattr(profile, "display_name", None) or adapter.provider_id
        entries.append((adapter.provider_id, label))

    io.write("Available providers:")
    for index, (pid, label) in enumerate(entries, start=1):
        io.write(f"  {index}. {label} ({pid})")
    raw = io.read_line("Select: ").strip()
    chosen = _select_from(entries, raw)
    if chosen is None:
        return CommandResult(output=f"unknown provider selection: {raw}", failed=True)

    if chosen == "none":
        session.select_provider("none")
        return CommandResult(output="provider: none (offline)")

    adapter = deps.registry.get(chosen)
    profile = getattr(adapter, "profile", None)

    # invalidate first (clears model/credential/secret/routing), then resolve
    session.select_provider(chosen)

    resolved = (
        resolve_for_profile(profile, environ=deps.environ) if profile else None
    )
    if resolved is not None and resolved.source != "unavailable":
        session.refresh_credential(deps.registry, environ=deps.environ)
        io.write(
            f"Using credential from {session.credential.source} "
            f"({profile.credential_env_var})."
        )
    else:
        secret = io.read_secret("API key: ").strip()
        if not secret:
            return CommandResult(output="no credential provided", failed=True)
        session.set_explicit_secret(secret)
        session.refresh_credential(deps.registry, environ=deps.environ)

    answer = io.read_line("Verify credentials now? (y/N): ").strip()
    if _yes(answer):
        credential_value = session.explicit_secret or (
            session.credential.credential if session.credential else None
        )
        try:
            ok = adapter.validate_credentials(credential_value)
        except ProviderError as exc:
            io.write(f"verification failed: {exc}")
        else:
            io.write("Credentials verified." if ok else "Credentials rejected.")

    if session.explicit_secret:
        if _yes(io.read_line("Store in OS keyring for later sessions? (y/N): ").strip()):
            stored = keyring_store(chosen, session.explicit_secret)
            io.write("Stored in keyring." if stored else "Keyring unavailable; not stored.")

    if _yes(io.read_line("Save as default provider? (y/N): ").strip()):
        deps.config_manager.save({"provider": {"name": chosen}})
        io.write("Saved to config.")

    return CommandResult(output=f"provider: {chosen} (choose a model with /model)")


@_command("model", "choose the conversion model")
def _model(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    if session.provider_id in (None, "none"):
        return CommandResult(output="choose a provider first (/provider)", failed=True)

    adapter = deps.registry.get(session.provider_id)
    models = [
        m for m in adapter.resolve_models()
        if getattr(m, "status", "active") != "retired"
    ]
    required = (
        session.last_routing.required_routes
        if session.last_routing is not None
        else frozenset({"digest", "vision"})
    )

    io.write("Models:")
    for index, model in enumerate(models, start=1):
        problems = check_model_for_routes(model, required)
        note = "  (incompatible with current routing)" if problems else ""
        io.write(f"  {index}. {model.display_name} [{model.model_id}]{note}")

    raw = io.read_line("Select (number or model id): ").strip()
    if not raw:
        return CommandResult(output="model selection cancelled", failed=True)
    if raw.isdigit() and 1 <= int(raw) <= len(models):
        chosen = models[int(raw) - 1].model_id
    else:
        chosen = raw  # custom ids are allowed; preflight ultimately decides

    session.select_model(chosen)
    notes: list[str] = []
    resolution = resolve_model(adapter, chosen)
    if resolution.warning:
        notes.append(resolution.warning)
    if resolution.definition is not None:
        notes.extend(check_model_for_routes(resolution.definition, required))
    output = f"model: {chosen}"
    if notes:
        output += "\n" + "\n".join(f"warning: {n}" for n in notes)
    return CommandResult(output=output)


@_command("status", "show the current session")
def _status(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    config = deps.config_manager.load()
    report = session.readiness(deps.registry)
    lines = [
        f"PDF        : {session.pdf_path or '(not selected)'}",
        f"Title      : {session.title or '(from PDF metadata)'}",
        f"Author     : {session.author or '(from PDF metadata)'}",
        f"Output     : {session.output_path or '(not set)'}",
        f"Provider   : {session.provider_id or '(not chosen)'}",
        f"Model      : {session.conversion_model or '(not selected)'}",
        f"Credential : {_credential_label(session)}",
    ]
    if session.last_routing is not None:
        summary = session.last_routing.routing_summary
        lines.append(
            f"Routing    : tier1={summary.get('tier1', 0)} "
            f"digest={summary.get('tier2_digest', 0)} "
            f"vision={summary.get('tier2_vision', 0)}"
        )
    lines.append(f"EPUBCheck  : {'enabled' if config.epubcheck_enabled else 'disabled'}")
    lines.append(f"Ace        : {'enabled' if config.ace_enabled else 'disabled'}")
    lines.append(f"Ready      : {report.state.value.upper()}")
    lines += [f"             - {gap}" for gap in report.missing]
    return CommandResult(output="\n".join(lines))


@_command("convert", "run the conversion")
def _convert(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    report = session.readiness(deps.registry)
    if report.state is Readiness.NOT_READY:
        return CommandResult(
            output="not ready:\n" + "\n".join(f"  - {gap}" for gap in report.missing),
            failed=True,
        )

    request = session.build_request()
    service = deps.service_factory()
    result = service.convert(request, explicit_secret=session.explicit_secret)
    if result.preflight is not None:
        session.last_routing = result.preflight

    lines: list[str] = []
    lines += [f"warning: {w}" for w in result.warnings]
    lines += [f"error: {e}" for e in result.all_errors]
    if result.success:
        lines.append(f"done: {result.output_path}")
    elif result.cancelled:
        lines.append("cancelled")
    else:
        lines.append("conversion failed")
    return CommandResult(output="\n".join(lines), failed=not result.success)


@_command("config", "show the saved configuration")
def _config(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    config = deps.config_manager.load()
    lines = [
        f"provider         : {config.provider_name or '(default: none)'}",
        f"conversion model : {config.conversion_model or '(none)'}",
        f"epubcheck        : {'enabled' if config.epubcheck_enabled else 'disabled'}",
        f"ace              : {'enabled' if config.ace_enabled else 'disabled'}",
        f"output directory : {config.output_directory}",
        f"cache dir        : {config.resolved_cache_dir}",
        f"config file      : {deps.config_manager.path()}",
    ]
    return CommandResult(output="\n".join(lines))


@_command("exit", "leave the session")
def _exit(session: Session, io: IO, deps: SessionDeps, args: str) -> CommandResult:
    return CommandResult(output="bye", exit=True)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch(line: str, *, session: Session, io: IO, deps: SessionDeps) -> CommandResult:
    """Parse one input line and run its command. Never raises."""
    text = line.strip()
    if not text:
        return CommandResult()
    if text.startswith("/"):
        text = text[1:].strip()
    verb, _, rest = text.partition(" ")
    entry = _COMMANDS.get(verb.lower())
    if entry is None:
        return CommandResult(
            output=f"unknown command: /{verb} (try /help)", failed=True
        )
    handler = entry[0]
    try:
        return handler(session, io, deps, rest.strip())
    except Exception as exc:  # a command bug must never kill the session
        return CommandResult(
            output=f"command failed: {type(exc).__name__}: {exc}", failed=True
        )
