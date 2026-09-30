"""Console entry point (``pdf2epub`` and ``python -m pdf2epub``).

Phase 1 stub: the real headless CLI arrives in a later phase. Until then the
engine is still driven through the legacy ``main.py`` in the repository root.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from pdf2epub import __version__


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--version"], ["-V"]):
        print(f"pdf2epub {__version__}")
        return 0
    print(
        "pdf2epub: the command-line interface is not implemented yet.\n"
        "Use `python main.py --help` from the source tree for now.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
