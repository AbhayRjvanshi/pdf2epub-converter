"""Fresh-process memory probe for the long-document budget gate.

Run as a child interpreter by
``test_long_document_converts_within_budget`` (Round 3 M0 correction).
The gate it replaces subtracted two readings of one long-lived pytest
process's ``ru_maxrss``; that measured how far the conversion
overshot the session's *historical* peak -- allocator noise, not the
conversion's footprint -- and its macOS numbers were kilobytes
mislabelled as megabytes (Darwin reports ``ru_maxrss`` in bytes, see
the BSD getrusage(2) man page; Linux reports KiB, see getrusage(2) on
man7.org). This probe reports the child's own total peak, normalized
per platform, with no subtraction anywhere.

Usage (from the parent test)::

    python tests/memprobe.py <src-dir> <large.pdf> <out.epub>

Prints ``PEAK_MIB=<float>``, ``ELAPSED=<float>`` and
``CHAPTERS=<int>``; exits non-zero if the conversion fails. Requires
the ``resource`` module (Unix) -- the parent test skips on platforms
without it. The import lives inside ``convert_and_report`` so the
platform-normalization helper stays importable (and testable) on
every platform.
"""

import sys
import time


def peak_mib(ru_maxrss: int, platform: str = sys.platform) -> float:
    """Normalize a ru_maxrss reading to MiB.

    Darwin reports the value in BYTES; Linux reports it in KiB. Any
    other platform is treated as the Linux convention and flagged by
    the caller if it ever appears in CI.
    """
    if platform == "darwin":
        return ru_maxrss / (1024 * 1024)
    return ru_maxrss / 1024


def convert_and_report(src_dir: str, pdf_path: str, out_path: str) -> None:
    import resource

    sys.path.insert(0, src_dir)
    from pdf2epub.engine import driver

    started = time.monotonic()
    result = driver.run_pipeline(
        pdf_path,
        out_path,
        llm_adapter=None,
        verbose=False,
        cache_dir=out_path + ".cache",
        validators=(),  # this gate measures the conversion, not validation
    )
    elapsed = time.monotonic() - started
    if not result["success"]:
        raise SystemExit(f"probe: conversion failed: {result.get('validation')}")
    peak = peak_mib(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(f"PEAK_MIB={peak:.1f}")
    print(f"ELAPSED={elapsed:.1f}")
    print(f"CHAPTERS={len(result['build'].chapters)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: memprobe.py <src-dir> <large.pdf> <out.epub>")
    convert_and_report(sys.argv[1], sys.argv[2], sys.argv[3])
