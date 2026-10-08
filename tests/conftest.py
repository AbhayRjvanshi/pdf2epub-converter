import sys
from pathlib import Path

import pytest

# The package itself comes from `pythonpath = src` (pytest.ini); this insert
# only makes the test-side fixture generator importable from any test module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_fixtures  # noqa: E402

try:
    import pymupdf as fitz  # noqa: E402
except ImportError:  # pragma: no cover
    import fitz  # noqa: E402

from pdf2epub.engine import tier1_classifier as t1  # noqa: E402


@pytest.fixture(scope="session")
def fixture_pdfs(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixtures")
    return make_fixtures.build_all(out)


@pytest.fixture(scope="session")
def clean_doc(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["clean_book"])
    yield doc
    doc.close()


@pytest.fixture(scope="session")
def clean_profile(clean_doc):
    return t1.DocumentFontProfile.build(clean_doc)


@pytest.fixture(scope="session")
def tier1_stream(clean_doc, clean_profile):
    """Deterministic stream for the four Tier 1 pages of the clean fixture."""
    elements = []
    for idx in range(4):
        elements.extend(t1.build_page_stream(clean_doc[idx], clean_profile, idx))
    return elements


def page_heights(doc):
    return {i: float(doc[i].rect.height) for i in range(len(doc))}
