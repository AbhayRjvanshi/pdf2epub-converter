"""Phase 1: the pdf2epub package skeleton imports cleanly and stays light."""

import importlib
import subprocess
import sys

import pytest

SUBPACKAGES = ["application", "cli", "providers", "config", "validators"]


def test_package_imports_and_exposes_version():
    pkg = importlib.import_module("pdf2epub")
    assert isinstance(pkg.__version__, str) and pkg.__version__


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackages_import(name):
    assert importlib.import_module(f"pdf2epub.{name}")


def test_module_entrypoint_imports():
    mod = importlib.import_module("pdf2epub.__main__")
    assert callable(mod.main)


def test_entrypoint_version_and_exit_codes(capsys):
    from pdf2epub.__main__ import main

    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("pdf2epub ")
    assert main([]) == 2  # required subcommand missing -> usage + exit 2
    assert main(["--help"]) == 0


def test_import_needs_no_engine_or_optional_extras():
    """Importing the package must not pull in heavy or optional libraries."""
    code = (
        "import sys, pdf2epub, pdf2epub.__main__;"
        "bad = [m for m in ('openai', 'anthropic', 'keyring', 'fitz', 'pymupdf',"
        " 'ebooklib', 'lxml') if m in sys.modules];"
        "sys.exit(1 if bad else 0)"
    )
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(src), "PATH": "", "SYSTEMROOT": "C:\\Windows"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_module_execution_reports_version():
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src"
    proc = subprocess.run(
        [sys.executable, "-m", "pdf2epub", "--version"],
        env={"PYTHONPATH": str(src), "SYSTEMROOT": "C:\\Windows"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0 and proc.stdout.startswith("pdf2epub ")
