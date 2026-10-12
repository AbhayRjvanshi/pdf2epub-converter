"""Round 2 WS-2: evidence-gated cover selection at the driver level.

The ``cover-image`` manifest property is assigned only when the title
page actually looks like a cover: an image whose placement covers ~the
whole page, on page 0, on a page that carries almost no text (a cover
is not a prose page with a big illustration). Anything weaker means
graceful omission -- a wrong cover marker is worse than none, and
EPUBCheck does not require one.
"""

import re
import zipfile
from pathlib import Path

import make_fixtures as mf

from pdf2epub.engine import driver

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

PAGE_W, PAGE_H = 420.0, 680.0


def _write_pdf(path, *, full_bleed=True, image_page=0, page0_text="By T. Albert", dense_text=False):
    doc = fitz.open()
    png = mf.make_square_png(200)
    if image_page == 0:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        rect = (0.0, 0.0, PAGE_W, PAGE_H) if full_bleed else (50.0, 50.0, 150.0, 150.0)
        page.insert_image(fitz.Rect(*rect), stream=png)
        if dense_text:
            # insert_text clips at the page width, so a dense page is
            # many wrapped lines, never one long string.
            for i in range(12):
                page.insert_text(
                    (54.0, 200.0 + i * 15.0),
                    "word word word word word word ",
                    fontname="helv", fontsize=10.0,
                )
        elif page0_text:
            page.insert_text((54.0, 620.0), page0_text, fontname="helv", fontsize=10.0)
    else:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((54.0, 100.0), "Opening prose.", fontname="helv", fontsize=14.0)
        later = doc.new_page(width=PAGE_W, height=PAGE_H)
        later.insert_image(fitz.Rect(0.0, 0.0, PAGE_W, PAGE_H), stream=png)
    closing = doc.new_page(width=PAGE_W, height=PAGE_H)
    closing.insert_text(
        (54.0, 100.0), "A closing paragraph of prose.", fontname="helv", fontsize=14.0
    )
    doc.save(str(path))
    doc.close()
    return Path(path)


def _manifest(tmp_path, pdf, name="out.epub"):
    out = tmp_path / name
    result = driver.run_pipeline(
        str(pdf), str(out),
        llm_adapter=None, verbose=False,
        cache_dir=str(tmp_path / "cache"),
        validators=(),
    )
    assert result["success"] is True, result
    with zipfile.ZipFile(out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        return zf.read(opf).decode()


def test_full_bleed_title_page_image_becomes_the_cover(tmp_path):
    pdf = _write_pdf(tmp_path / "THE-FLOWER-GARDEN-book.pdf")
    xml = _manifest(tmp_path, pdf)
    assert 'properties="cover-image"' in xml
    item = re.search(r"<item[^>]*cover-image[^>]*/>", xml)
    assert item and ".png" in item.group(0)


def test_small_image_on_the_title_page_is_not_a_cover(tmp_path):
    pdf = _write_pdf(tmp_path / "small cover.pdf", full_bleed=False)
    xml = _manifest(tmp_path, pdf)
    assert "cover-image" not in xml


def test_full_bleed_image_on_a_later_page_is_not_a_cover(tmp_path):
    pdf = _write_pdf(tmp_path / "later art.pdf", image_page=1)
    xml = _manifest(tmp_path, pdf)
    assert "cover-image" not in xml


def test_text_dense_first_page_is_not_a_cover(tmp_path):
    """A full-page illustration on a page dense with prose is an
    illustrated content page, not a cover."""
    pdf = _write_pdf(tmp_path / "dense page.pdf", dense_text=True)
    xml = _manifest(tmp_path, pdf)
    assert "cover-image" not in xml
