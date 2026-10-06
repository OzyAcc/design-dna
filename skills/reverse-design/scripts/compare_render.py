"""Compare a reference against an actual exported render: metric panel, artifacts, profile verdicts.

Usage:
  python compare_render.py <reference> <render> --out <dir> [--template ID --scene FILE --render-report FILE]
                           [--profile exact_pixels|editable_close] [--how copying|asset_reuse|editable_rendering]

Decoding policy: Pillow decode; EXIF orientation applied; embedded ICC converted to sRGB (untagged = assumed
sRGB); alpha composited over the declared background. No resize, blur, recolor or registration is applied.
Every check returns pass / fail / unknown; unknown never counts as pass. SSIM is one structural measure,
not a percent-identity claim.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_json, template_dir, write_json  # noqa: E402

DEFAULT_TOL = {"anchor_px": 1.0, "delta_e": 1.0, "region_ssim": 0.99}
HEAT_GAIN = 4
INK_THRESHOLD = 40


def decode(path, bg=(255, 255, 255)):
    im = Image.open(path)
    im.load()
    pol = {"file": str(path), "mode": im.mode, "size": list(im.size)}
    im = ImageOps.exif_transpose(im)
    icc = im.info.get("icc_profile")
    if icc:
        mode = "RGBA" if "A" in im.mode else "RGB"
        im = ImageCms.profileToProfile(im.convert(mode), ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                       ImageCms.createProfile("sRGB"), outputMode=mode)
        pol["icc"] = "embedded profile converted to sRGB"
    else:
        pol["icc"] = "none (assumed sRGB)"
    if "A" in im.mode or im.mode == "P":
        rgba = im.convert("RGBA")
        base = Image.new("RGBA", rgba.size, bg + (255,))
        im = Image.alpha_composite(base, rgba)
        pol["alpha"] = f"composited over rgb{bg}"
    return np.asarray(im.convert("RGB")), pol


def pixel_metrics(a, b) -> dict:
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    unequal = int(np.count_nonzero(d.max(axis=2)))
    return {"unequal_pixels": unequal, "unequal_fraction": unequal / (a.shape[0] * a.shape[1]),
            "max_channel_error": int(d.max()), "mae": float(d.mean()), "rmse": float(np.sqrt((d.astype(np.float64) ** 2).mean())),
            "range": "0-255 per channel, RGB"}


def ssim(a, b):
    from skimage.metrics import structural_similarity

    side = min(a.shape[0], a.shape[1])
    win = min(7, side if side % 2 else side - 1)
    if win < 3:
        return None, {"reason": f"region {a.shape[1]}x{a.shape[0]} too small for a valid SSIM window"}
    v = structural_similarity(a, b, channel_axis=2, data_range=255, win_size=win)
    return float(v), {"win_size": win, "gaussian_weights": False, "channel_axis": 2, "data_range": 255}


def clip_box(box, W, H):
    x, y, w, h = box
    x0, y0 = max(0, int(np.floor(x))), max(0, int(np.floor(y)))
    x1, y1 = min(W, int(np.ceil(x + w))), min(H, int(np.ceil(y + h)))
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def ink_bbox(img, box, bg):
    x0, y0, x1, y1 = box
    crop = img[y0:y1, x0:x1].astype(np.int16)
    mask = np.abs(crop - np.array(bg, np.int16)).max(axis=2) > INK_THRESHOLD
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return [x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1]


def border_bg(img, box):
    x0, y0, x1, y1 = box
    c = img[y0:y1, x0:x1].reshape(-1, 3) if (x1 - x0) < 3 or (y1 - y0) < 3 else np.concatenate(
        [img[y0, x0:x1], img[y1 - 1, x0:x1], img[y0:y1, x0], img[y0:y1, x1 - 1]])
    return [int(v) for v in np.median(c, axis=0)]


def delta_e(c1, c2) -> float:
    from skimage.color import deltaE_ciede2000, rgb2lab

    lab = rgb2lab(np.array([[c1, c2]], np.float64) / 255.0)
    return float(deltaE_ciede2000(lab[0, 0], lab[0, 1]))


def patch_median(img, box, inset=2):
    x, y, w, h = box
    b = clip_box([x + inset, y + inset, w - 2 * inset, h - 2 * inset], img.shape[1], img.shape[0])
    if b is None:
        return None, None
    p = img[b[1]:b[3], b[0]:b[2]].reshape(-1, 3).astype(np.float64)
    return [float(v) for v in np.median(p, axis=0)], [float(v) for v in p.std(axis=0)]


def ink_core(img, box, ring=4):
    """Stroke-core pixels of thin ink (text): background = median of a ring just outside the box (tight ink
    boxes can be >50% ink); ink = pixels > 40 away from it; core = the 30% farthest in luminance."""
    x, y, w, h = [int(round(v)) for v in box]
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x - ring), max(0, y - ring), min(W, x + w + ring), min(H, y + h + ring)
    outer = img[y0:y1, x0:x1].astype(np.float64)
    mask = np.ones(outer.shape[:2], bool)
    mask[y - y0:y - y0 + h, x - x0:x - x0 + w] = False
    bg = np.median(outer[mask], axis=0)
    reg = img[y:y + h, x:x + w].reshape(-1, 3).astype(np.float64)
    ink = reg[np.abs(reg - bg).max(axis=1) > 40]
    if not len(ink):
        return None
    lw = np.array([0.2126, 0.7152, 0.0722])
    far = np.abs(ink @ lw - bg @ lw)
    return ink[far >= np.quantile(far, 0.7)]


def ink_core_median(img, box):
    core = ink_core(img, box)
    if core is None:
        return None, None
    return [float(v) for v in np.median(core, axis=0)], [float(v) for v in core.std(axis=0)]


def regions_from_scene(scene, render_report=None) -> list[dict]:
    bounds = (render_report or {}).get("bounds", {})
    out = []
    for n in scene["nodes"]:
        if n["type"] in ("background", "group") or not n.get("visible", True):
            continue
        rb = (bounds.get(n["id"]) or {}).get("rendered")
        g = n["geometry"]
        box = rb or [g["x"], g["y"], g["w"], g["h"]]
        kind = "image" if n["type"] == "image" else ("text" if n["type"] == "text" else n.get("role", n["type"]))
        out.append({"id": n["id"], "kind": kind, "box": [box[0] - 2, box[1] - 2, box[2] + 4, box[3] + 4]})
    return out


def compare(ref_path, out_path, out_dir, scene=None, render_report=None, profile="editable_close",
            how=None, editability=None, bg=(255, 255, 255)) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "crops").mkdir(parents=True, exist_ok=True)
    ref, rpol = decode(ref_path, bg)
    out, opol = decode(out_path, bg)
    tol = dict(DEFAULT_TOL, **(((scene or {}).get("verification") or {}).get("tolerances") or {}))
    rep = {"profile": profile, "reference": rpol, "render": opol, "tolerances": tol, "checks": {}, "unknown": [],
           "heatmap": {"value": "max channel |ref-render|", "gain": HEAT_GAIN, "colormap": "black->red->yellow"}}
    if ref.shape != out.shape:
        rep["checks"]["dimensions"] = {"status": "fail", "reference": list(ref.shape[:2][::-1]), "render": list(out.shape[:2][::-1])}
        rep["overall"] = "fail"
        write_json(out_dir / "report.json", rep)
        return rep
    H, W = ref.shape[:2]
    rep["checks"]["dimensions"] = {"status": "pass", "size": [W, H]}
    pm = pixel_metrics(ref, out)
    rep["checks"]["exact_pixels"] = dict(pm, status="pass" if pm["unequal_pixels"] == 0 else "fail", achieved_by=how)
    rep["checks"]["pixel_error"] = dict(mae=pm["mae"], rmse=pm["rmse"], status="info")
    g, gset = ssim(ref, out)
    rep["checks"]["ssim_global"] = {"value": g, "settings": gset, "status": "info",
                                    "note": "global SSIM is not used for a verdict; large blank areas can hide local errors"}
    # artifacts
    Image.fromarray(np.hstack([ref, out])).save(out_dir / "side_by_side.png")
    Image.blend(Image.fromarray(ref), Image.fromarray(out), 0.5).save(out_dir / "overlay_50.png")
    d = np.abs(ref.astype(np.int16) - out.astype(np.int16)).max(axis=2).astype(np.int32) * HEAT_GAIN
    heat = np.stack([np.clip(d, 0, 255), np.clip(d - 255, 0, 255), np.zeros_like(d)], axis=2).astype(np.uint8)
    Image.fromarray(heat).save(out_dir / "diff_heatmap.png")
    if scene is None:
        rep["unknown"] += ["geometry", "typography", "color", "editability", "communication"]
        rep["overall"] = _verdict(rep, profile)
        write_json(out_dir / "report.json", rep)
        return rep
    # region checks (text/logo/hero/shapes separately so blank space cannot hide them)
    regions, geo, reg = regions_from_scene(scene, render_report), {}, {}
    for r in regions:
        b = clip_box(r["box"], W, H)
        if b is None:
            continue
        rc, oc = ref[b[1]:b[3], b[0]:b[2]], out[b[1]:b[3], b[0]:b[2]]
        s, sset = ssim(rc, oc)
        rpm = pixel_metrics(rc, oc)
        reg[r["id"]] = {"box": list(b), "kind": r["kind"], "ssim": s, "ssim_settings": sset,
                        "unequal_fraction": rpm["unequal_fraction"], "max_channel_error": rpm["max_channel_error"],
                        "status": "unknown" if s is None else ("pass" if s >= tol["region_ssim"] else "fail")}
        trip = np.hstack([rc, oc, heat[b[1]:b[3], b[0]:b[2]]])
        k = 2 if trip.shape[1] < 600 else 1  # small regions enlarged (nearest) for inspection
        Image.fromarray(trip).resize((trip.shape[1] * k, trip.shape[0] * k), Image.NEAREST).save(out_dir / "crops" / f"{r['id']}.png")
        if r["kind"] != "image":
            bgc = border_bg(ref, b)
            ri, oi = ink_bbox(ref, b, bgc), ink_bbox(out, b, bgc)
            if ri is None or oi is None:
                geo[r["id"]] = {"status": "unknown", "reason": "no ink found in one image", "reference_ink": ri, "render_ink": oi}
            else:
                err = max(abs(p - q) for p, q in zip(ri, oi))
                geo[r["id"]] = {"status": "pass" if err <= tol["anchor_px"] else "fail", "max_edge_error_px": err,
                                "reference_ink": ri, "render_ink": oi}
    rep["checks"]["regions"] = reg
    rep["checks"]["geometry"] = geo
    # color tokens with recorded sample patches
    col = {}
    for key, t in scene["tokens"].items():
        if t["type"] != "color" or not isinstance(t["value"], str):
            continue
        sampler = ink_core_median if t.get("sample_method") == "ink_core" else patch_median
        for i, box in enumerate(t.get("samples") or []):
            rm, rs = sampler(ref, box)
            om, _ = sampler(out, box)
            if rm is None:
                col[f"{key}#{i}"] = {"status": "unknown", "reason": "sample patch too small after inset"}
                continue
            de = delta_e(rm, om)
            col[f"{key}#{i}"] = {"status": "pass" if de <= tol["delta_e"] else "fail", "delta_e_2000": de,
                                 "reference_median": rm, "reference_std": rs, "render_median": om}
    if not col:
        rep["unknown"].append("color: no token sample patches recorded")
    rep["checks"]["color"] = col
    # typography / content
    expected = (scene.get("verification") or {}).get("expected_text") or {}
    typo = {}
    for n in scene["nodes"]:
        if n["type"] != "text":
            continue
        exp = expected.get(n["id"])
        ident = ((n.get("font") or {}).get("identity") or {}).get("status", "unknown")
        if exp is None:
            typo[n["id"]] = {"status": "unknown", "reason": "no reference transcription recorded", "font_identity": ident}
        else:
            same = exp == n["content"]
            typo[n["id"]] = {"status": "pass" if same else "fail", "content_identical": same,
                             "line_breaks": [exp.count("\n") + 1, n["content"].count("\n") + 1], "font_identity": ident}
    rep["checks"]["typography"] = typo
    rep["checks"]["editability"] = {"status": "unknown" if editability is None else
                                    ("pass" if editability["overall"] == "pass" else "fail"), "detail": editability}
    rep["checks"]["communication"] = {"status": "unknown", "note": "interpretive; see passport/communication hypotheses"}
    rep["unknown"].append("communication (interpretive, cannot be measured from pixels)")
    rep["overall"] = _verdict(rep, profile)
    write_json(out_dir / "report.json", rep)
    return rep


def _verdict(rep, profile) -> dict:
    c = rep["checks"]
    if profile == "exact_pixels":
        st = "pass" if c["dimensions"]["status"] == "pass" and c["exact_pixels"]["status"] == "pass" else "fail"
        return {"profile": profile, "status": st, "achieved_by": c["exact_pixels"].get("achieved_by"),
                "note": "identical pixels do not establish identical original layers"}
    items = []
    for group in ("regions", "geometry", "color", "typography"):
        items += [(f"{group}.{k}", v["status"]) for k, v in (c.get(group) or {}).items()]
    items.append(("editability", c.get("editability", {}).get("status", "unknown")))
    fails = [k for k, s in items if s == "fail"]
    unknown = [k for k, s in items if s == "unknown"]
    st = "fail" if fails or c["dimensions"]["status"] == "fail" else ("incomplete" if unknown else "pass")
    return {"profile": profile, "status": st, "failed": fails, "unknown": unknown + rep["unknown"],
            "note": "a tolerance pass is not 100% identity"}


def outside_influence(base_png, var_png, influence_boxes, W, H) -> dict:
    """adapt_preserve pixel check: pixels outside the pre-declared influence must be identical."""
    a, _ = decode(base_png)
    b, _ = decode(var_png)
    mask = np.zeros((H, W), bool)
    for box in influence_boxes:
        cb = clip_box(box, W, H)
        if cb:
            mask[cb[1]:cb[3], cb[0]:cb[2]] = True
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > 0
    outside = int(np.count_nonzero(diff & ~mask))
    return {"status": "pass" if outside == 0 else "fail", "changed_outside_influence": outside,
            "changed_inside_influence": int(np.count_nonzero(diff & mask)),
            "influence_fraction": float(mask.mean()), "influence_boxes": influence_boxes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reference")
    ap.add_argument("render")
    ap.add_argument("--out", required=True)
    ap.add_argument("--template")
    ap.add_argument("--scene")
    ap.add_argument("--render-report")
    ap.add_argument("--profile", default="editable_close", choices=["exact_pixels", "editable_close"])
    ap.add_argument("--how", choices=["copying", "asset_reuse", "editable_rendering", "mixed"])
    a = ap.parse_args()
    scene = edit = None
    if a.template:
        from validate_model import editability_report

        scene = read_json(a.scene or template_dir(a.template) / "scene.json")
        edit = editability_report(scene)
    rr = read_json(a.render_report) if a.render_report else None
    rep = compare(a.reference, a.render, a.out, scene, rr, a.profile, a.how, edit)
    print(json.dumps(rep["overall"], indent=2))
    return 0 if rep["overall"]["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
