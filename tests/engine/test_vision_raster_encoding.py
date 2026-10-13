"""Round 3 M3a: vision-embedded scanned-page rasters as JPEG.

C1 corpus evidence (docs/round3_image_inventory.md): 74 rendered
page rasters cost 89.57 MB as PNG against 15.43 MB of source JPEGs --
a 5.8x inflation. Photographic page renders are the classic JPEG use
case; the approved policy encodes them as JPEG q90 with two hard
guards:

* a raster that carries alpha stays PNG -- JPEG cannot carry alpha,
  and flattening transparent content is forbidden by the Round 3
  policy;
* a JPEG encoder failure falls back to the PNG raster -- a page's
  content must never be lost to an encoding attempt.

Size reduction itself is asserted on the real corpus document in the
M3a benchmark (the synthetic scanned fixture is not photographic, so
a fixture-level size assertion would prove nothing).
"""

import zipfile
from types import SimpleNamespace

import pytest

from pdf2epub.engine import confidence_router as cr
from pdf2epub.engine import driver

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz


def _run(pdf, out, **kw):
    kw.setdefault("llm_adapter", None)
    kw.setdefault("verbose", False)
    kw.setdefault("cache_dir", str(out.parent / "cache"))
    kw.setdefault("validators", ())
    return driver.run_pipeline(str(pdf), str(out), **kw)


def _media(zf):
    return [n for n in zf.namelist() if n.startswith("EPUB/images/")]


def test_scanned_page_raster_is_encoded_as_jpeg(fixture_pdfs, tmp_path):
    out = tmp_path / "scan.epub"
    result = _run(fixture_pdfs["scanned"], out)
    assert result["success"] is True, result
    with zipfile.ZipFile(out) as zf:
        media = _media(zf)
        assert len(media) == 1, media
        name = media[0]
        assert name.endswith(".jpeg"), name
        data = zf.read(name)
        assert data[:3] == b"\xff\xd8\xff"  # real JPEG, not a renamed PNG
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        xml = zf.read(opf).decode()
        assert f'media-type="image/jpeg"' in xml  # manifest matches bytes

        # dimensions are preserved exactly: same render, new encoding
        doc = fitz.open(fixture_pdfs["scanned"])
        ref = doc[0].get_pixmap(dpi=cr.RASTER_DPI)
        doc.close()
        pix = fitz.Pixmap(data)
        assert (pix.width, pix.height) == (ref.width, ref.height)


def test_alpha_bearing_raster_stays_png():
    """JPEG cannot carry alpha: an alpha-bearing page raster must keep
    its lossless PNG representation, whatever the size temptation."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), True)
    rgba_png = pix.tobytes("png")
    report = SimpleNamespace(raster_bytes=rgba_png, page_num=1, page_index=0)
    elements = driver._embed_visual_page(report, page, None)
    doc.close()
    assert len(elements) == 1
    img = elements[0].image_data
    assert img.ext == "png"
    assert img.mime_type == "image/png"
    assert img.filename.endswith(".png")
    assert img.image_bytes == rgba_png


def test_jpeg_encode_failure_falls_back_to_png(monkeypatch):
    """A page's content must never be lost to an encoding attempt: an
    encoder failure keeps the PNG raster."""
    real_tobytes = fitz.Pixmap.tobytes

    def exploding(self, output="png", **kwargs):
        if output == "jpeg":
            raise RuntimeError("simulated encoder failure")
        return real_tobytes(self, output, **kwargs)

    monkeypatch.setattr(fitz.Pixmap, "tobytes", exploding)
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    png = page.get_pixmap(dpi=cr.RASTER_DPI).tobytes("png")
    report = SimpleNamespace(raster_bytes=png, page_num=1, page_index=0)
    elements = driver._embed_visual_page(report, page, None)
    doc.close()
    assert len(elements) == 1
    img = elements[0].image_data
    assert img.ext == "png"
    assert img.image_bytes == png


def test_flat_born_digital_render_stays_png_when_png_is_smaller(fixture_pdfs):
    """The other branch of the measured rule: a born-digital flat
    text page renders smaller as PNG than as q90 JPEG (the reference
    book's vision page regressed 125 KB -> 203 KB before this rule:
    202,835 JPEG against 125,022 PNG). Eligibility is measured per
    raster, never guessed from the page class."""
    doc = fitz.open(fixture_pdfs["no_heading"])
    png = doc[0].get_pixmap(dpi=cr.RASTER_DPI).tobytes("png")
    page = doc[0]
    jpeg = fitz.Pixmap(png).tobytes("jpeg", jpg_quality=90)
    assert len(png) < len(jpeg)  # premise: PNG wins on this raster
    report = SimpleNamespace(raster_bytes=png, page_num=1, page_index=0)
    elements = driver._embed_visual_page(report, page, None)
    doc.close()
    assert len(elements) == 1
    img = elements[0].image_data
    assert img.ext == "png"
    assert img.image_bytes == png


def test_vision_raster_encoding_is_deterministic(fixture_pdfs, tmp_path):
    """The encoder promises byte-level reproducibility for identical
    input: two conversions of the same page must package the identical
    JPEG bytes under the identical content-hash filename."""
    outs = []
    for i in (1, 2):
        out = tmp_path / f"scan{i}.epub"
        result = _run(fixture_pdfs["scanned"], out)
        assert result["success"] is True
        with zipfile.ZipFile(out) as zf:
            media = _media(zf)
            assert len(media) == 1
            outs.append((media[0], zf.read(media[0])))
    assert outs[0][0] == outs[1][0]  # same content-hash filename
    assert outs[0][1] == outs[1][1]  # byte-identical JPEG
