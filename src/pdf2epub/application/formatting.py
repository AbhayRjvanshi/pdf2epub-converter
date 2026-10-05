"""Public formatting helpers for CLI/REPL consumers.

Re-exported from the engine so UIs never reach into private engine
internals; the engine itself stays free of application imports (its own
private printer delegates to the same pure function).
"""

from ..engine.driver import format_routing_table

__all__ = ["format_routing_table"]
