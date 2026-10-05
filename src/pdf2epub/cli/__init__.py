"""Command-line interfaces: the headless CLI (REPL arrives in Phase 14)."""

from .headless import build_parser, main

__all__ = ["build_parser", "main"]
