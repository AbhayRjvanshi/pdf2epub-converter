"""Layer isolation, enforced by test, in both directions.

Providers never import the engine, PDF libraries or SDKs; the engine never
imports providers. Both properties are checked in fresh interpreters so
lazy imports cannot hide a violation.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"


def test_provider_modules_import_nothing_heavy():
    code = (
        "import sys, importlib;"
        "mods = ('pdf2epub.providers', 'pdf2epub.providers.base',"
        " 'pdf2epub.providers.models', 'pdf2epub.providers.errors',"
        " 'pdf2epub.providers.offline', 'pdf2epub.providers.mock',"
        " 'pdf2epub.providers.profile', 'pdf2epub.providers.catalog',"
        " 'pdf2epub.providers.registry', 'pdf2epub.providers.requirements',"
        " 'pdf2epub.providers.openai_style',"
        " 'pdf2epub.providers.anthropic_style',"
        " 'pdf2epub.providers.nvidia_style');"
        "[importlib.import_module(m) for m in mods];"
        "heavy = ('fitz', 'pymupdf', 'ebooklib', 'lxml',"
        " 'openai', 'anthropic', 'keyring');"
        "bad = [m for m in sys.modules"
        "       if m == 'pdf2epub.engine' or m.startswith('pdf2epub.engine.')"
        "       or m.split('.')[0] in heavy];"
        "sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(SRC), "PATH": "", "SYSTEMROOT": "C:\\Windows"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_engine_modules_never_import_providers():
    code = (
        "import sys;"
        "__import__('pdf2epub.engine.driver');"
        "bad = [m for m in sys.modules"
        "       if m == 'pdf2epub.providers'"
        "       or m.startswith('pdf2epub.providers.')];"
        "sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(SRC), "PATH": "", "SYSTEMROOT": "C:\\Windows"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_offline_and_mock_satisfy_the_protocol_members():
    # structural check independent of runtime Protocol mechanics
    from pdf2epub.providers.mock import MockProvider
    from pdf2epub.providers.offline import OfflineProvider

    for provider in (OfflineProvider(), MockProvider()):
        assert isinstance(provider.provider_id, str)
        assert callable(provider.resolve_models)
        assert callable(provider.validate_credentials)
        assert callable(provider.create_llm_callable)
