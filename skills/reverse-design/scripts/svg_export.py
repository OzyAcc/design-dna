"""SVG export that says what it contains, and proves it renders like the engine's PNG.

The export is ONE self-contained file (images and, by default, fonts embedded as data URIs) plus a manifest that
classifies every element: live_text, vector, embedded_raster, procedural_texture or group, with each SVG filter
(shadow, blur, colour treatment) declared as a filter effect that design tools may rasterise or drop. The
exported file itself is then rendered in the pinned browser and compared with the PNG render (decoded pixels).
Not every SVG is an "editable master": the manifest is the claim, the round-trip is the evidence.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from common import write_json

SVGNS = "{http://www.w3.org/2000/svg}"


def classify(scene, fonts_mode) -> dict:
    els, counts = [], {}
    for n in scene["nodes"]:
        if not n.get("visible", True):
            kind, note = "hidden", "not exported"
        elif n["type"] == "text":
            kind, note = "live_text", f"<text>/<tspan>, font {'embedded' if fonts_mode == 'embed' else 'referenced by name'}"
        elif n["type"] in ("shape", "path") or (n["type"] == "background" and not n.get("asset")):
            kind, note = "vector", "native SVG geometry"
        elif n["type"] in ("image", "background"):
            kind, note = "embedded_raster", "pixel data embedded; replaceable as a whole, not as objects inside it"
        elif n["type"] == "effect":
            kind = "procedural_texture" if n["effect"]["kind"] == "grain" else "vector"
            note = "feTurbulence noise generated at render time" if kind == "procedural_texture" else "radial gradient"
        else:
            kind, note = "group", "container"
        filters = [f"treatment:{t['op']}" for t in n.get("treatment", [])] + \
                  [f"effect:{fx['type']}" for fx in n.get("effects", []) if fx.get("enabled", True)]
        if n.get("mask"):
            filters.append(f"mask:{n['mask']['type']}")
        els.append({"node": n["id"], "type": n["type"], "export_as": kind, "note": note, "filter_effects": filters,
                    "model_editability": n.get("editability", "live")})
        counts[kind] = counts.get(kind, 0) + 1
    return {"elements": els, "counts": counts}


def export_svg(scene, tdir, out_dir, name, fit_sizes, fonts="embed") -> dict:
    from render_static import compile_svg

    svg, used_fonts = compile_svg(scene, tdir, href_mode="data" if fonts == "embed" else "data-nofonts", fit_sizes=fit_sizes)
    path = Path(out_dir) / f"{name}.svg"
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg, encoding="utf-8")
    cls = classify(scene, fonts)
    external = re.findall(r'(?:href|url)\(?"?(?!data:|#)([^"\)\s>]+\.(?:png|jpe?g|webp|ttf|otf|woff2?))', svg)
    manifest = {
        "file": path.name, "bytes": path.stat().st_size, "self_contained": not external, "external_references": external,
        "fonts": [{"asset": a, "sha256": scene["assets"][a]["sha256"], "names": scene["assets"][a].get("font_names"),
                   "embedded": fonts == "embed"} for a in used_fonts],
        **cls,
        "is_editable_master": False,
        "editability_statement": ("Live text stays text and vector geometry stays vector. Embedded rasters are replaceable "
                                  "only as whole images. Filter effects (shadows, blurs, colour treatments) are live SVG "
                                  "filters that some design tools rasterise or ignore. The scene.json model, not this "
                                  "file, is the editable master."),
        "font_note": "embedded fonts keep their own licence terms; check before redistributing" if fonts == "embed" else
                     "fonts referenced by name: text renders identically only where the same font files are installed",
    }
    write_json(Path(out_dir) / f"{name}.svg.manifest.json", manifest)
    return {"svg": str(path), "manifest": manifest}


def verify_svg(svg_path, png_path, scene, channel=None) -> dict:
    """Render the exported SVG file itself, compare with the PNG render, and check live text + rasters structurally."""
    from compare_render import decode, diff_where, pixel_metrics
    from renderer_env import browser, capture

    W, H = int(scene["canvas"]["width"]), int(scene["canvas"]["height"])
    with browser(channel) as (b, ch):
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.goto(Path(svg_path).resolve().as_uri(), wait_until="load")
        pg.evaluate("async () => { await Promise.all([...document.fonts].map(f => f.load().catch(() => null))); await document.fonts.ready; }")
        shot = capture(pg, clip={"x": 0, "y": 0, "width": W, "height": H},
                       omit_background=scene["canvas"]["alpha"] == "transparent", animations="disabled")
    tmp = Path(svg_path).with_suffix(".roundtrip.png")
    Image.open(io.BytesIO(shot)).save(tmp)
    a, _ = decode(png_path)
    bimg, _ = decode(tmp)
    pm = pixel_metrics(a, bimg) if a.shape == bimg.shape else {"unequal_pixels": None, "note": "dimension mismatch"}
    if pm.get("unequal_pixels"):
        pm["where"] = diff_where(a, bimg)
    root = ET.parse(svg_path).getroot()
    texts = {}
    for g in root.iter(f"{SVGNS}g"):
        t = g.find(f"{SVGNS}text")
        if g.get("id") and t is not None:
            texts[g.get("id")] = "\n".join("".join(s.itertext()) for s in t.findall(f"{SVGNS}tspan"))
    want = {n["id"]: n["content"] for n in scene["nodes"] if n["type"] == "text" and n.get("visible", True)}
    live = {k: texts.get(k) == v for k, v in want.items()}
    rasters = [im for im in root.iter(f"{SVGNS}image")]
    n_raster = sum(1 for n in scene["nodes"] if n.get("visible", True) and n.get("asset") and n["type"] in ("image", "background"))
    ok_pix = pm.get("unequal_pixels") == 0
    return {"roundtrip_png": str(tmp), "renderer": ch, "pixels_vs_engine_png": pm,
            "roundtrip_status": "pass" if ok_pix else "fail",
            "live_text_matches_model": live, "live_text_status": "pass" if all(live.values()) else "fail",
            "embedded_rasters": len(rasters), "raster_nodes": n_raster,
            "raster_status": "pass" if len([r for r in rasters if r.get("href", "").startswith("data:")]) >= n_raster else "fail",
            "note": "decoded-pixel comparison of the exported file rendered standalone vs the engine PNG (same pinned browser)"}
