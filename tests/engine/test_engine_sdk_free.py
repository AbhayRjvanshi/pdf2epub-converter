"""Phase 16: the engine is SDK-free.

The legacy permissive bridge (``providers.compat``) was retired together
with the legacy CLI. What outlives it is the invariant it used to guard:
importing the engine pulls neither a provider SDK nor the provider layer,
and no engine source file mentions an SDK import. There is no longer any
delegation path to test.
"""

import os
import subprocess
import sys
from pathlib import Path


def test_importing_the_engine_pulls_no_sdk_and_no_providers():
    src = Path(__file__).resolve().parent.parent.parent / "src"
    code = (
        "import sys, importlib;"
        "importlib.import_module('pdf2epub.engine.driver');"
        "bad = [m for m in ('openai', 'anthropic', 'pdf2epub.providers')"
        "       if m in sys.modules"
        "       or any(x.startswith(m + '.') for x in sys.modules)];"
        "sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_engine_source_contains_no_sdk_imports():
    import pdf2epub.engine as engine_pkg

    engine_dir = Path(engine_pkg.__file__).parent
    for path in engine_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import openai" not in text, path.name
        assert "import anthropic" not in text, path.name
