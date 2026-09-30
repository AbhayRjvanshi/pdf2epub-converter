"""Phase 2: engine lives in pdf2epub.engine; root modules are identity shims."""

import importlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PURE_MODULES = [
    "tier1_classifier",
    "confidence_router",
    "tier2_llm_handler",
    "packaging_and_validation",
]


@pytest.mark.parametrize("name", PURE_MODULES)
def test_root_module_is_the_packaged_module(name):
    legacy = importlib.import_module(name)
    packaged = importlib.import_module(f"pdf2epub.engine.{name}")
    assert legacy is packaged


def test_main_is_the_packaged_driver():
    import main

    from pdf2epub.engine import driver

    assert main is driver


def test_full_legacy_symbol_surface_present():
    import main

    for symbol in (
        "run_pipeline",
        "create_llm_client_adapter",
        "parse_xhtml_to_stream_elements",
        "_embed_visual_page",
        "build_arg_parser",
        "main",
        "tier1_classifier",
        "BLOCK_TAG_TYPES",
    ):
        assert hasattr(main, symbol), symbol


def test_monkeypatch_on_root_main_reaches_the_pipeline(fixture_pdfs, tmp_path, monkeypatch):
    """A copy-style shim would let this patch land where the pipeline never looks."""
    import main

    calls = []

    def fake_embed(report, page, spool_dir):
        calls.append(report.page_num)
        return []

    monkeypatch.setattr(main, "_embed_visual_page", fake_embed)
    main.run_pipeline(
        fixture_pdfs["clean_book"],
        str(tmp_path / "patched.epub"),
        llm_adapter=None,
        verbose=False,
        skip_validation=True,
        cache_dir=str(tmp_path / "cache"),
    )
    assert calls, "patched _embed_visual_page was never called by run_pipeline"


def test_monkeypatch_on_root_module_reaches_the_engine(monkeypatch):
    import packaging_and_validation as legacy

    from pdf2epub.engine import packaging_and_validation as packaged

    sentinel = object()
    monkeypatch.setattr(legacy, "subprocess", sentinel)
    assert packaged.subprocess is sentinel


def _clean_env():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # prove the source-tree fallback, not the test runner
    return env


def test_direct_execution_help():
    proc = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=ROOT, env=_clean_env(), capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--provider" in proc.stdout


def test_direct_execution_converts_a_fixture(fixture_pdfs, tmp_path):
    out = tmp_path / "x.epub"
    proc = subprocess.run(
        [sys.executable, "main.py", fixture_pdfs["single_column"],
         "--provider", "none", "-o", str(out), "--cache-dir", str(tmp_path / "c"),
         "--quiet"],
        cwd=ROOT, env=_clean_env(), capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(out) as zf:
        assert "mimetype" in zf.namelist()


def test_engine_imports_from_outside_the_repo(tmp_path):
    """Package import works from an arbitrary directory with only src on the path."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "from pdf2epub.engine import driver; print(driver.run_pipeline.__name__)"],
        cwd=tmp_path,
        env={**_clean_env(), "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "run_pipeline" in proc.stdout
