"""Intake a reference and open a persistent named template (Step A + scan pass 1).

Usage: python inspect_source.py <file> --name "Editorial Product Spotlight" [--name-status user_supplied|suggested] [--id ID]

Preserves the original bytes under source/ (content-hashed, immutable), reads metadata, writes a separately
identified canonical sRGB comparison copy, records evidence, and creates a skeleton scene + passport.
Only static raster images have an adapter; other inputs return an explicit `unsupported_adapter` result.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (SCHEMA_VERSION, TOOL_VERSION, DnaError, add_evidence, now, sha256_bytes, sha256_file,  # noqa: E402
                    slugify, store_root, template_dir, write_immutable, write_json)

RASTER = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
NOT_YET = {".pdf": "pdf/document", ".svg": "vector source", ".psd": "layered source", ".fig": "figma",
           ".ai": "illustrator", ".mp4": "motion", ".mov": "motion", ".html": "website/ui"}


def read_metadata(path: Path) -> dict:
    with Image.open(path) as im:
        icc = im.info.get("icc_profile")
        exif = im.getexif()
        alpha = "A" in im.mode or "transparency" in im.info
        alpha_used = False
        if alpha:
            alpha_used = bool(np.asarray(im.convert("RGBA"))[:, :, 3].min() < 255)
        meta = {"format": im.format, "width": im.width, "height": im.height, "header_note": "width/height = raw file header (before EXIF orientation)", "mode": im.mode,
                "has_alpha_channel": alpha, "alpha_used": alpha_used,
                "icc_profile": ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip() if icc else None,
                "exif_orientation": exif.get(0x0112), "dpi": im.info.get("dpi"), "frames": getattr(im, "n_frames", 1),
                "file_bytes": path.stat().st_size}
        if im.format == "JPEG":
            from PIL import JpegImagePlugin

            meta["jpeg_subsampling"] = {0: "4:4:4", 1: "4:2:2", 2: "4:2:0"}.get(JpegImagePlugin.get_sampling(im), "unknown")
            q = getattr(im, "quantization", None) or {}
            meta["jpeg_luma_quant_mean"] = round(float(np.mean(q[0])), 2) if 0 in q else None
    g = math.gcd(meta["width"], meta["height"])
    meta["aspect_ratio"] = f"{meta['width'] // g}:{meta['height'] // g}"
    return meta


def meta_size(meta):
    return meta["oriented_width"], meta["oriented_height"]


def canonical_copy(path: Path, out: Path) -> str:
    with Image.open(path) as im:
        im.load()
        steps = []
        if im.getexif().get(0x0112, 1) != 1:
            steps.append("EXIF orientation applied")
        im = ImageOps.exif_transpose(im)
        icc = im.info.get("icc_profile")
        mode = "RGBA" if ("A" in im.mode or "transparency" in im.info) else "RGB"
        if icc:
            im = ImageCms.profileToProfile(im.convert(mode), ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                           ImageCms.createProfile("sRGB"), outputMode=mode)
            steps.append("embedded ICC converted to sRGB (perceptual)")
        else:
            steps.append("no ICC profile: pixel values kept, assumed sRGB (inferred)")
        if getattr(im, "n_frames", 1) > 1:
            steps.append("first frame only")
        im.convert(mode).save(out, format="PNG")
    return "; ".join(steps) + f"; decoded to 8-bit {mode} PNG"


def candidate_artwork_bounds(path: Path):
    """If all four corners share a color, propose the tight bounds of non-margin content (inference only)."""
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    corners = np.array([a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]])
    if np.abs(corners - corners[0]).max() > 8:
        return None, "corners differ; no uniform margin to trim"
    ys, xs = np.nonzero(np.abs(a - corners[0]).max(axis=2) > 8)
    if not len(xs):
        return None, "uniform image"
    return [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)], \
        f"uniform margin color {corners[0].tolist()}"


def unknown_claim(probe):
    return {"value": None, "status": "unknown", "confidence": "unassessed", "evidence_ids": [], "resolving_probe": probe}


def create_template(src: Path, name: str, name_status: str, tid: str | None = None) -> dict:
    ext = src.suffix.lower()
    if ext in NOT_YET:
        raise DnaError(f"no adapter for {NOT_YET[ext]} inputs yet; only static raster images are implemented",
                       "unsupported_adapter", {"adapter": NOT_YET[ext], "status": "unsupported",
                                               "workaround": "export the artwork as PNG and scan that (layers/interactions stay unknown)"})
    if ext not in RASTER:
        raise DnaError(f"unrecognized input type {ext!r}", "unsupported_adapter")
    tid = tid or slugify(name)
    base = tid
    i = 2
    while template_dir(tid).exists():
        tid = f"{base}-{i}"
        i += 1
    tdir = template_dir(tid)
    data = src.read_bytes()
    digest = sha256_bytes(data)
    rel = f"source/{digest[:16]}{ext}"
    write_immutable(tdir / rel, data)
    meta = read_metadata(tdir / rel)
    canon = tdir / "source" / "canonical.png"
    conversion = canonical_copy(tdir / rel, canon)
    with Image.open(canon) as im:  # the working canvas is the orientation-normalised image, not the raw header
        meta["oriented_width"], meta["oriented_height"] = im.size
    g = math.gcd(*meta_size(meta))
    meta["aspect_ratio"] = f"{meta['oriented_width'] // g}:{meta['oriented_height'] // g}"
    with Image.open(canon) as im:
        im.thumbnail((320, 320))
        im.save(tdir / "source" / "thumb.png")
    bounds, why = candidate_artwork_bounds(canon)
    tool = f"{TOOL_VERSION} inspect_source.py; Pillow {Image.__version__}"
    add_evidence(tdir, [
        {"evidence_id": "ev-src-metadata", "source_sha256": digest, "region": None, "object": "input_canvas",
         "method": "direct_metadata", "tool": tool, "value": meta, "units": "px", "status": "measured",
         "confidence": "high", "justification": "read from file header/decoder", "limitations": [
             "a flattened raster carries no layers, hidden pixels, interactions or print settings"]},
        {"evidence_id": "ev-src-canonical", "source_sha256": digest, "region": None, "object": "input_canvas",
         "method": "computed_measurement", "tool": tool, "value": {"path": "source/canonical.png",
                                                                  "sha256": sha256_file(canon), "conversion": conversion},
         "status": "measured", "confidence": "high", "justification": "deterministic decode + declared conversion"},
        {"evidence_id": "ev-src-framing", "source_sha256": digest, "region": bounds, "object": "input_canvas",
         "method": "inference", "tool": tool, "value": {"candidate_artwork_bounds": bounds, "basis": why},
         "status": "inferred", "confidence": "low", "justification": "corner-color heuristic; does not prove absence of surrounding UI",
         "resolving_probe": "confirm whether the image is the artwork itself or a screenshot containing it"},
    ])
    W, H = meta["oriented_width"], meta["oriented_height"]
    scene = {
        "schema_version": SCHEMA_VERSION, "template_id": tid, "revision": 0, "base_revision": None,
        "source": {"sha256": digest, "path": rel, "original_name": src.name, "metadata": meta,
                   "canonical": {"path": "source/canonical.png", "sha256": sha256_file(canon), "conversion": conversion}},
        "canvas": {"width": W, "height": H, "origin": "top-left", "units": "px", "color_space": "srgb",
                   "alpha": "transparent" if meta["alpha_used"] else "opaque", "background_composite": "#FFFFFF",
                   "artwork_bounds": [0, 0, W, H]},
        "tokens": {}, "assets": {}, "nodes": [], "constraints": [], "slots": [], "locks": [],
        "communication": {"goal": unknown_claim("ask the user for the original brief"),
                          "literal_message": unknown_claim("transcribe visible copy"),
                          "takeaway": unknown_claim("interpret after hierarchy pass"),
                          "mechanisms": [], "hierarchy": {"order": [], "status": "unknown"}},
        "scan": {"state": "in_progress", "coverage": {
            "input_canvas": {"status": "measured", "note": f"{W}x{H} {meta['format']} {meta['mode']}; ICC: {meta['icc_profile']}",
                             "evidence_ids": ["ev-src-metadata", "ev-src-canonical", "ev-src-framing"]},
            "responsive_system": {"status": "unknown", "note": "a single still shows one state; breakpoints/interactions unknowable"}}},
        "verification": {"tolerances": {"anchor_px": 1, "delta_e": 1, "region_ssim": 0.99, "declared_before_iteration": True,
                                        "justification": "spec starting points for editable_close"}},
    }
    write_json(tdir / "scene.json", scene)
    passport = {
        "schema_version": SCHEMA_VERSION, "id": tid, "name": name, "name_status": name_status, "aliases": [],
        "thumbnail": "source/thumb.png", "reference": {"path": rel, "sha256": digest, "original_name": src.name},
        "revision": 0, "readiness": "scan_in_progress", "aspect_ratio": meta["aspect_ratio"],
        "baseline_match": {"profile": "none", "status": "not_run", "report": None, "how": None},
        "editability_coverage": {}, "unresolved": ["scan passes 2-8 not yet run"], "created": now(), "updated": now()}
    write_json(tdir / "passport.json", passport)
    return {"template_id": tid, "dir": str(tdir), "metadata": meta, "canonical": conversion,
            "candidate_artwork_bounds": bounds, "store": str(store_root())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file")
    ap.add_argument("--name", required=True)
    ap.add_argument("--name-status", default="user_supplied", choices=["user_supplied", "suggested"])
    ap.add_argument("--id")
    a = ap.parse_args()
    try:
        r = create_template(Path(a.file), a.name, a.name_status, a.id)
    except DnaError as e:
        print(json.dumps(e.as_dict(), indent=2))
        return 2
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
