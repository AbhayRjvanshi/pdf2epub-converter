"""Image inventory and size attribution for a converted EPUB.

Round 3 WS-1 / M0b measurement tool: converts a PDF with the CURRENT
engine (no behavior changes) and produces a per-asset inventory that
joins every packaged image back to its PDF origin using *placement
evidence* -- xref and bounding box -- never pixel dimensions, which
collide in real books (every full-page illustration in the Flower
Garden is ~820x1060).

Usage:
    python scripts/image_inventory.py <input.pdf> --out-dir <dir>

Writes <out-dir>/<stem>_inventory.json and prints a summary. The
generated EPUB is kept next to it as the frozen BEFORE artifact for
later before/after benchmarks.

Attribution classes (verified facts, not image-content guesses):
    rendered-page-raster  vision-embedded scan page (no source xref
                          exists; produced by the converter itself)
    mask-composite        source carried a soft mask; output carries
                          the composited alpha
    transcoded            source format/colorspace is non-core
                          (JPX, BMP, TIFF, WebP, CMYK) and the asset
                          was re-encoded at extraction
    passthrough           output bytes are byte-identical to the
                          source's encoded bytes
    re-encoded            same-core format but bytes differ (e.g. a
                          colorspace-conversion re-encode); flagged
                          for investigation, never silently accepted
    unmatched             no xref/bbox evidence found -- recorded as
                          such, never forced onto a lookalike source

Ambiguous joins (two placements overlapping the element almost
equally) are flagged ``ambiguous: true`` rather than resolved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

from pdf2epub.engine import driver
from pdf2epub.engine.tier1_classifier import ElementType

CORE_EXTS = {"png", "jpeg", "jpg"}


def _cs_is_core(cs_raw) -> bool:
    """Same semantics as the extraction gate (tier1_classifier):
    the dict-block/extract_image colorspace is a component count when
    an int (the engine's _CS_GRAY=1, _CS_RGB=3; 4 = CMYK) or a device
    name when a string. None is accepted as core, exactly like the
    gate."""
    if cs_raw is None:
        return True
    if isinstance(cs_raw, int):
        return cs_raw in (1, 3)
    cs = str(cs_raw).lower()
    return (
        cs in ("devicegray", "gray", "devicergb", "rgb")
        or cs.endswith("gray")
        or cs.endswith("rgb")
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sniff_format(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    return "other"


def _overlap_fraction(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    return inter / area_a if area_a else 0.0


def build_inventory(pdf_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    epub_path = out_dir / f"{pdf_path.stem[:40]}_baseline.epub"

    result = driver.run_pipeline(
        str(pdf_path), str(epub_path),
        llm_adapter=None, verbose=False,
        cache_dir=str(out_dir / "cache"),
        validators=(),  # structural only: this is a measurement run
    )
    if not result["success"]:
        raise SystemExit(f"conversion failed: {result.get('validation')}")

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    # xref -> source record, and page -> placements
    sources: dict[int, dict] = {}
    placements: dict[int, list[dict]] = {}
    for pno in range(total_pages):
        for info in doc[pno].get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if not xref:
                continue
            placements.setdefault(pno, []).append(info)
            if xref in sources:
                continue
            rec = doc.extract_image(xref)
            kind, smask = doc.xref_get_key(xref, "SMask")
            cs_raw = rec.get("colorspace")
            sources[xref] = {
                "xref": xref,
                "ext": rec.get("ext"),
                "bytes": len(rec["image"]),
                "width": rec["width"],
                "height": rec["height"],
                "colorspace": str(cs_raw) if cs_raw is not None else None,
                "cs_core": _cs_is_core(cs_raw),
                "has_smask": bool(rec.get("smask")) or kind != "null",
            }
    doc.close()

    with zipfile.ZipFile(str(epub_path)) as zf:
        packaged = {n: zf.read(n) for n in zf.namelist()
                    if n.endswith((".png", ".jpeg", ".jpg", ".gif"))}

    elements = [
        e for e in result["build"].clean_stream
        if e.element_type is ElementType.IMAGE and e.image_data is not None
    ]
    assets = []
    for e in elements:
        img = e.image_data
        data = packaged.get(f"EPUB/images/{img.filename}")
        if data is None:  # not packaged (should not happen)
            assets.append({
                "filename": img.filename, "packaged": False,
                "page": e.page_num + 1, "bbox": list(img.bbox),
                "class": "not-packaged",
            })
            continue
        pix = fitz.Pixmap(data)
        # -- placement join: best-overlap xref on the element's page ----
        best, best_score, runner_up = None, 0.0, 0.0
        for info in placements.get(e.page_num, []):
            score = _overlap_fraction(img.bbox, info["bbox"])
            if score > best_score:
                runner_up = best_score
                best, best_score = info, score
            elif score > runner_up:
                runner_up = score
        src = sources.get(best["xref"]) if best and best_score > 0.5 else None
        ambiguous = bool(best and runner_up > 0.9 * best_score)

        if img.filename.startswith("page_"):
            klass = "rendered-page-raster"
        elif src is None:
            klass = "unmatched"
        elif (src["width"], src["height"]) != (pix.width, pix.height):
            # A 43x44 output cannot be the re-encode of an 817x1060
            # source: the bbox join landed inside a page-filling
            # artwork's placement. Recorded as a suspect join; the
            # class is never forced onto it.
            klass = "join-suspect"
        elif src["has_smask"] and pix.alpha:
            klass = "mask-composite"
        elif src["has_smask"]:
            # the Round 1 warning path: compositing failed, the opaque
            # base survived -- transparency lost, must stay visible
            klass = "mask-fallback"
        elif not src["cs_core"] or (src["ext"] or "").lower() not in CORE_EXTS:
            klass = "transcoded"
        elif src["bytes"] == len(data):
            klass = "passthrough"
        else:
            klass = "re-encoded"

        assets.append({
            "filename": img.filename,
            "packaged": True,
            "page": e.page_num + 1,
            "bbox": [round(v, 2) for v in img.bbox],
            "out_format": sniff_format(data),
            "out_bytes": len(data),
            "out_width": pix.width,
            "out_height": pix.height,
            "out_alpha": bool(pix.alpha),
            "alt_source": img.alt_source,
            "class": klass,
            "ambiguous_join": ambiguous,
            "join_overlap": round(best_score, 3) if best else None,
            "src_xref": src["xref"] if src else None,
            "src_ext": src["ext"] if src else None,
            "src_bytes": src["bytes"] if src else None,
            "src_width": src["width"] if src else None,
            "src_height": src["height"] if src else None,
            "src_colorspace": src["colorspace"] if src else None,
            "src_has_smask": src["has_smask"] if src else None,
            "dims_match": (
                (src["width"], src["height"]) == (pix.width, pix.height)
                if src else None
            ),
            "delta_bytes": (len(data) - src["bytes"]) if src else None,
        })

    by_class: dict[str, dict] = {}
    for a in assets:
        c = by_class.setdefault(a["class"], {"count": 0, "out_bytes": 0, "src_bytes": 0})
        c["count"] += 1
        c["out_bytes"] += a.get("out_bytes", 0)
        if a.get("src_bytes"):
            c["src_bytes"] += a["src_bytes"]

    inventory = {
        "source": {"path": str(pdf_path), "sha256": sha256(pdf_path),
                   "pages": total_pages},
        "epub": {"path": str(epub_path), "sha256": sha256(epub_path),
                 "bytes": epub_path.stat().st_size},
        "engine_commit_note": "baseline generated at the current HEAD; "
                              "no production encoding behavior changed in M0b",
        "assets": sorted(assets, key=lambda a: -a.get("out_bytes", 0)),
        "totals": {
            "elements": len(elements),
            "packaged_assets": len(packaged),
            "packaged_image_bytes": sum(len(d) for d in packaged.values()),
            "unmatched": sum(1 for a in assets if a["class"] == "unmatched"),
            "ambiguous_joins": sum(1 for a in assets if a.get("ambiguous_join")),
            "dims_mismatch": sum(
                1 for a in assets
                if a.get("dims_match") is False
                and a["class"] not in ("rendered-page-raster",)
            ),
        },
        "by_class": by_class,
    }
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    inv = build_inventory(args.pdf, args.out_dir)
    out = args.out_dir / f"{args.pdf.stem[:40]}_inventory.json"
    out.write_text(json.dumps(inv, indent=1), encoding="utf-8")

    print(f"source sha256: {inv['source']['sha256']}")
    print(f"epub: {inv['epub']['bytes']} bytes, sha256 {inv['epub']['sha256'][:16]}...")
    print(f"packaged image bytes: {inv['totals']['packaged_image_bytes']}")
    print(f"unmatched: {inv['totals']['unmatched']}, "
          f"ambiguous joins: {inv['totals']['ambiguous_joins']}, "
          f"dims mismatches: {inv['totals']['dims_mismatch']}")
    for klass, c in sorted(inv["by_class"].items(), key=lambda kv: -kv[1]["out_bytes"]):
        print(f"  {klass:<20} {c['count']:>4} assets  {c['out_bytes']:>9} out bytes  "
              f"{c['src_bytes']:>9} src bytes")
    print(f"inventory: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
