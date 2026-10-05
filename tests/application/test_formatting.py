"""Phase 9: the public routing-table formatter used by CLI/REPL."""

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - legacy alias
    import fitz

from pdf2epub.application.formatting import format_routing_table
from pdf2epub.engine import confidence_router


def test_format_routing_table_has_a_row_per_page(fixture_pdfs):
    doc = fitz.open(fixture_pdfs["clean_book"])
    try:
        reports = confidence_router.route_document(doc, build_payloads=False)
    finally:
        doc.close()

    table = format_routing_table(reports)
    lines = table.splitlines()
    assert "page" in lines[0] and "score" in lines[0]
    assert len(lines) == len(reports) + 2  # header + separator + rows
    assert "tier1" in table
