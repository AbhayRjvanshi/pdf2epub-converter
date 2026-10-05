"""Console entry point (``pdf2epub`` and ``python -m pdf2epub``)."""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    # Lazy import keeps this module cheap and dependency-free to import
    # (the Phase 1 contract); the CLI itself pulls in the engine.
    from .cli.headless import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
