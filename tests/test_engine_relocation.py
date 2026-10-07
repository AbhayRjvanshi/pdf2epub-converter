"""Phase 2: engine lives in pdf2epub.engine; root modules are identity shims."""

import importlib
import os
import subprocess
import sys
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
