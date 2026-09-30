"""Compatibility shim: the module now lives in ``pdf2epub.engine``.

An identity alias (not a copy) so monkeypatching this name affects the engine.
"""

import sys

from pdf2epub.engine import packaging_and_validation as _m

sys.modules[__name__] = _m
