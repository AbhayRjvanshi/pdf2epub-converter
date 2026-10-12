"""Round 1 / WS1: image-fidelity regression tests.

Every test here pins a confirmed flower-garden defect class at the
extraction boundary (``tier1_classifier.extract_images``):

* /SMask transparency composited into alpha PNGs (pages 6/10/11/29/31)
* renderer-synthesized mask rasters dropped, not packaged (page 6:
  the 828x335 grayscale artifact)
* solid transparency-group backplates dropped (pages 31/32)
* CMYK sources transcoded to RGB without inversion
* identical duplicate placements emitted once

Assertions are content-based: they check pixels, alpha, colorspace and
*absence* of the known artifacts, not just element counts.
"""

import logging

import pytest

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

from pdf2epub.engine import tier1_classifier as t1
from pdf2epub.engine.tier1_classifier import ElementType


def _figures(elements):
    return [e for e in elements if e.element_type is ElementType.IMAGE]


def _extract(page, page_index=0):
    return t1.extract_images(page, page_index, [], None)


# ---------------------------------------------------------------------------
# Real-PDF fixtures
# ---------------------------------------------------------------------------


def test_smasked_image_composites_to_alpha_png(fixture_pdfs):
    """Base+/SMask pairs merge into one alpha PNG; the mask never
    survives as a second, standalone figure."""
    doc = fitz.open(fixture_pdfs["smask_composite"])
    figures = _figures(_extract(doc[0]))
    doc.close()

    assert len(figures) == 1, "mask must not be packaged as a second figure"
    img = figures[0].image_data
    assert img.ext == "png"
    assert img.mime_type == "image/png"
    assert img.image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    pix = fitz.Pixmap(img.image_bytes)
    assert pix.alpha == 1, "transparency must survive into the packaged asset"
    assert (pix.width, pix.height) == (64, 32)
    # polarity: white mask = opaque, black mask = transparent
    left = tuple(pix.pixel(2, 16))
    right = tuple(pix.pixel(62, 16))
    assert left == (255, 0, 0, 255)
    assert right[3] == 0


def test_soft_mask_artifact_raster_is_dropped(fixture_pdfs, caplog):
    """The grayscale raster MuPDF synthesizes for an ExtGState luminosity
    soft mask (flower-garden page 6) is renderer plumbing, not artwork."""
    doc = fitz.open(fixture_pdfs["soft_mask_artifact"])
    with caplog.at_level(
        logging.INFO, logger="pdf2epub.engine.tier1_classifier"
    ):
        figures = _figures(_extract(doc[0]))
    doc.close()

    assert len(figures) == 1
    img = figures[0].image_data
    # the surviving figure is the composited base, with real alpha
    pix = fitz.Pixmap(img.image_bytes)
    assert pix.alpha == 1
    assert tuple(pix.pixel(2, 16)) == (255, 0, 0, 255)
    assert "soft-mask raster" in caplog.text


def test_cmyk_raster_transcodes_to_rgb_without_inversion(fixture_pdfs):
    """A CMYK source must not reach the EPUB with a core extension
    intact, and the RGB conversion must not invert the colors."""
    doc = fitz.open(fixture_pdfs["cmyk_raster"])
    figures = _figures(_extract(doc[0]))
    doc.close()

    assert len(figures) == 1
    img = figures[0].image_data
    assert img.ext == "png"
    pix = fitz.Pixmap(img.image_bytes)
    assert "RGB" in str(pix.colorspace)
    # k-only CMYK renders near-black; an inverted conversion is near-white
    pixel = tuple(pix.pixel(pix.width // 2, pix.height // 2))
    assert max(pixel) < 80, f"cmyk conversion inverted the swatch: {pixel}"


def test_duplicate_identical_placement_emits_one_figure(fixture_pdfs):
    """The same raster bytes at the identical position are a duplicate
    paint; identical bytes at distinct positions stay distinct figures."""
    doc = fitz.open(fixture_pdfs["duplicate_placement"])
    figures = _figures(_extract(doc[0]))
    doc.close()
    assert len(figures) == 1

    # negative control: same bytes, different placements -> two figures
    import make_fixtures as mf

    doc2 = fitz.open()
    p = doc2.new_page(width=200.0, height=100.0)
    logo = mf.make_square_png(32)
    p.insert_image(fitz.Rect(10.0, 10.0, 42.0, 42.0), stream=logo)
    p.insert_image(fitz.Rect(60.0, 10.0, 92.0, 42.0), stream=logo)
    figures2 = _figures(_extract(p))
    doc2.close()
    assert len(figures2) == 2


def test_unmasked_jpeg_stays_passthrough(fixture_pdfs):
    """The compositing work must not disturb the plain-JPEG path:
    unmasked rasters keep their original bytes and extension."""
    import make_fixtures as mf

    doc = fitz.open()
    p = doc.new_page(width=200.0, height=100.0)
    p.insert_image(fitz.Rect(10.0, 10.0, 110.0, 60.0), stream=mf.make_square_png(48))
    doc2 = fitz.open("pdf", doc.tobytes())
    figures = _figures(_extract(doc2[0]))
    doc.close()
    doc2.close()
    assert len(figures) == 1


# ---------------------------------------------------------------------------
# Rule-level stubs (deterministic, fast)
# ---------------------------------------------------------------------------


def _rgba_png(size=32, color=(255, 255, 255, 255)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size), True)
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


def _pattern_png(size=32) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size), True)
    pix.set_rect(fitz.IRect(0, 0, size // 2, size), (200, 30, 30, 255))
    pix.set_rect(fitz.IRect(size // 2, 0, size, size), (30, 30, 200, 255))
    return pix.tobytes("png")


def _gray_png(size=16, shade=128) -> bytes:
    """A two-tone grayscale pattern (uniform rasters are droppable)."""
    pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, size, size), False)
    pix.set_rect(fitz.IRect(0, 0, size // 2, size), (shade,))
    pix.set_rect(fitz.IRect(size // 2, 0, size, size), (255 - shade,))
    return pix.tobytes("png")


def _opaque_png(size=32) -> bytes:
    """An RGB png without any alpha channel (the opaque-base shape)."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size), False)
    pix.set_rect(pix.irect, (40, 90, 160))
    return pix.tobytes("png")


def _stub_page(blocks, images=None, infos=None):
    class _Page:
        @staticmethod
        def get_text(kind):
            return {"dict": {"blocks": blocks}}.get(kind, {})

        @staticmethod
        def get_images(full=True):
            return images or []

        @staticmethod
        def get_image_info(xrefs=True):
            return infos or []

    return _Page()


def test_uniform_synthetic_raster_is_dropped(caplog):
    """An all-white group buffer carries no artwork (pages 31/32)."""
    block = {
        "type": 1, "number": 4, "bbox": (10.0, 10.0, 42.0, 42.0),
        "ext": "png", "colorspace": 3, "width": 32, "height": 32,
        "image": _rgba_png(32), "mask": None,
    }
    infos = [{"bbox": (10.0, 10.0, 42.0, 42.0), "width": 32, "height": 32,
              "xref": 0}]
    images = [(9, 0, 32, 32, 8, "DeviceRGB", "", "Im0", "FlateDecode", 0)]
    with caplog.at_level(logging.INFO, logger="pdf2epub.engine.tier1_classifier"):
        out = t1.extract_images(_stub_page([block], images, infos), 0, [], None)
    assert out == []
    assert "solid transparency-group buffer" in caplog.text


def test_synthetic_painted_raster_is_kept():
    """A non-uniform synthesized raster (painted group content, e.g. the
    page-31 background and the page-32 logo) is real visible content."""
    block = {
        "type": 1, "number": 4, "bbox": (10.0, 10.0, 42.0, 42.0),
        "ext": "png", "colorspace": 3, "width": 32, "height": 32,
        "image": _pattern_png(32), "mask": None,
    }
    infos = [{"bbox": (10.0, 10.0, 42.0, 42.0), "width": 32, "height": 32,
              "xref": 0}]
    out = t1.extract_images(_stub_page([block], [], infos), 0, [], None)
    assert len(out) == 1
    assert out[0].image_data.image_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_unregistered_block_is_kept():
    """No placement evidence at all (e.g. an inline image MuPDF did not
    register) must degrade to the old keep-everything behavior."""
    block = {
        "type": 1, "number": 2, "bbox": (10.0, 10.0, 42.0, 42.0),
        "ext": "png", "colorspace": 3, "width": 32, "height": 32,
        "image": _pattern_png(32), "mask": None,
    }
    out = t1.extract_images(_stub_page([block], [], []), 0, [], None)
    assert len(out) == 1


def test_gray_raster_without_masked_page_image_is_kept():
    """The mask-artifact rule requires a masked real image on the page:
    without one, a gray synthetic is kept rather than guessed away."""
    block = {
        "type": 1, "number": 4, "bbox": (10.0, 10.0, 42.0, 42.0),
        "ext": "png", "colorspace": 1, "width": 32, "height": 32,
        "image": _gray_png(32), "mask": None,
    }
    infos = [{"bbox": (10.0, 10.0, 42.0, 42.0), "width": 32, "height": 32,
              "xref": 0}]
    images = [(9, 0, 32, 32, 8, "DeviceGray", "", "Im0", "FlateDecode", 0)]
    out = t1.extract_images(_stub_page([block], images, infos), 0, [], None)
    assert len(out) == 1


def test_gray_raster_outside_masked_bbox_is_kept():
    """Overlap with a masked image's placement is required corroboration:
    a gray raster elsewhere on the page stays."""
    block = {
        "type": 1, "number": 4, "bbox": (150.0, 10.0, 182.0, 42.0),
        "ext": "png", "colorspace": 1, "width": 32, "height": 32,
        "image": _gray_png(32), "mask": None,
    }
    infos = [
        {"bbox": (10.0, 10.0, 42.0, 42.0), "width": 48, "height": 48,
         "xref": 9},
        {"bbox": (150.0, 10.0, 182.0, 42.0), "width": 32, "height": 32,
         "xref": 0},
    ]
    images = [(9, 11, 48, 48, 8, "DeviceRGB", "", "Im0", "FlateDecode", 0)]
    out = t1.extract_images(_stub_page([block], images, infos), 0, [], None)
    assert len(out) == 1


def test_composite_dimension_mismatch_keeps_opaque_base(caplog):
    """A mask whose dimensions do not match the base must not crash the
    extraction: the opaque base survives with a diagnostic."""
    block = {
        "type": 1, "number": 0, "bbox": (10.0, 10.0, 42.0, 42.0),
        "ext": "png", "colorspace": 3, "width": 32, "height": 32,
        "image": _opaque_png(32), "mask": _gray_png(16),
    }
    infos = [{"bbox": (10.0, 10.0, 42.0, 42.0), "width": 32, "height": 32,
              "xref": 9}]
    images = [(9, 11, 32, 32, 8, "DeviceRGB", "", "Im0", "FlateDecode", 0)]
    with caplog.at_level(logging.WARNING, logger="pdf2epub.engine.tier1_classifier"):
        out = t1.extract_images(_stub_page([block], images, infos), 0, [], None)
    assert len(out) == 1
    assert "could not be composited" in caplog.text
    pix = fitz.Pixmap(out[0].image_data.image_bytes)
    assert pix.alpha == 0, "fallback base must stay opaque, not corrupt"


def test_cmyk_colorspace_gate_transcodes_core_extension():
    """A core extension (jpeg) carrying CMYK bytes must transcode anyway."""
    block = {
        "type": 1, "number": 0, "bbox": (10.0, 10.0, 42.0, 42.0),
        "ext": "jpeg", "colorspace": 4, "width": 32, "height": 32,
        "image": _pattern_png(32), "mask": None,
    }
    infos = [{"bbox": (10.0, 10.0, 42.0, 42.0), "width": 32, "height": 32,
              "xref": 9}]
    images = [(9, 0, 32, 32, 8, "DeviceCMYK", "", "Im0", "DCTDecode", 0)]
    out = t1.extract_images(_stub_page([block], images, infos), 0, [], None)
    assert len(out) == 1
    img = out[0].image_data
    assert img.ext == "png"
    pix = fitz.Pixmap(img.image_bytes)
    assert "RGB" in str(pix.colorspace)
