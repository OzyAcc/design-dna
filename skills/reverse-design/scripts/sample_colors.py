"""Role-based color sampling from clean interior patches (never a global histogram).

  python sample_colors.py <tid> --sample background.paper=40,40,30,30 --sample background.paper=900,1200,30,30
                                [--ink-core text.primary=x,y,w,h] [--gradient hero.fade=x1,y1,x2,y2,steps] [--inset 2] [--apply]

--ink-core samples thin strokes (text): median of the darkest 30% of pixels that differ from the region's
ring just outside the box), i.e. stroke cores without antialiased edges. Each patch is inset to avoid antialiased edges; median/mean/std per channel and Lab are stored with the
coordinates. Several patches for one role are aggregated and their spread (Delta E 2000) reported.
High spread = texture/gradient/photo: recorded as non-solid, not forced into a flat token.
--apply writes/updates the role tokens in scene.json (with sample boxes for later verification).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TOOL_VERSION, add_evidence, read_json, slugify, template_dir, write_json  # noqa: E402
from compare_render import delta_e, ink_core  # noqa: E402


def hexc(rgb) -> str:
    return "#" + "".join(f"{int(round(v)):02X}" for v in rgb)


def patch_stats(a, box, inset):
    x, y, w, h = [int(round(v)) for v in box]
    p = a[y + inset:y + h - inset, x + inset:x + w - inset].reshape(-1, 3).astype(np.float64)
    if not len(p):
        raise SystemExit(f"patch {box} is empty after inset {inset}")
    med = np.median(p, axis=0)
    from skimage.color import rgb2lab

    lab = rgb2lab(med.reshape(1, 1, 3) / 255.0).reshape(3)
    return {"box": [x, y, w, h], "inset": inset, "pixels": int(len(p)), "median": med.tolist(), "mean": p.mean(axis=0).tolist(),
            "std": p.std(axis=0).tolist(), "lab_median": lab.tolist()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template")
    ap.add_argument("--sample", action="append", default=[], help="role=x,y,w,h")
    ap.add_argument("--gradient", action="append", default=[], help="role=x1,y1,x2,y2,steps")
    ap.add_argument("--ink-core", action="append", default=[], help="role=x,y,w,h (thin strokes such as text)")
    ap.add_argument("--inset", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    tdir = template_dir(a.template)
    scene = read_json(tdir / "scene.json")
    img = np.asarray(Image.open(tdir / "source" / "canonical.png").convert("RGB"))
    groups = defaultdict(list)
    for s in a.sample:
        role, box = s.split("=", 1)
        groups[role].append(patch_stats(img, [float(v) for v in box.split(",")], a.inset))
    for s_ in a.ink_core:
        role, box = s_.split("=", 1)
        bx = [int(round(float(v))) for v in box.split(",")]
        core = ink_core(img, bx)
        if core is None:
            raise SystemExit(f"no ink in {box}")
        groups[role].append({"box": bx, "inset": 0, "pixels": int(len(core)), "median": np.median(core, axis=0).tolist(),
                             "mean": core.mean(axis=0).tolist(), "std": core.std(axis=0).tolist(), "method": "ink-core (darkest 30% of ink)"})
    records, results = [], {}
    for role, patches in groups.items():
        med = np.median([p["median"] for p in patches], axis=0)
        spread = max((delta_e(p["median"], q["median"]) for p in patches for q in patches), default=0.0)
        worst_std = max(max(p["std"]) for p in patches)
        solid = worst_std <= 8 and spread <= 2
        conf = "high" if worst_std <= 3 and spread <= 1 else ("medium" if solid else "low")
        eid = f"ev-color-{slugify(role)}"
        results[role] = {"value": hexc(med), "solid": solid, "patch_spread_delta_e": spread, "max_patch_std": worst_std,
                         "confidence": conf, "patches": patches}
        records.append({"evidence_id": eid, "source_sha256": scene["source"]["sha256"], "region": patches[0]["box"],
                        "object": f"tokens.{role}", "method": "pixel_sampling", "tool": f"{TOOL_VERSION} sample_colors.py",
                        "value": results[role], "units": "sRGB 0-255", "status": "measured" if solid else "inferred",
                        "confidence": conf, "uncertainty": {"max_patch_std": worst_std, "patch_spread_delta_e": spread},
                        "justification": "median of inset interior patches" + ("" if solid else "; non-uniform -> not a solid token"),
                        "limitations": ["visible blended result; underlying color + opacity recipe unresolved if translucent"]})
        if a.apply and solid:
            scene["tokens"][role] = {"type": "color", "value": hexc(med), "space": "srgb", "status": "measured",
                                     "confidence": conf, "evidence_ids": [eid], "samples": [p["box"] for p in patches],
                                     "sample_method": "ink_core" if patches[0].get("method", "").startswith("ink-core") else "patch_median"}
    for g in a.gradient:
        role, spec = g.split("=", 1)
        x1, y1, x2, y2, n = [float(v) for v in spec.split(",")]
        stops = []
        for i in range(int(n)):
            t = i / (n - 1)
            px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            p = patch_stats(img, [px - 2, py - 2, 5, 5], 0)
            stops.append({"offset": round(t, 4), "color": hexc(p["median"]), "std": p["std"]})
        eid = f"ev-gradient-{slugify(role)}"
        value = {"type": "linear", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "units": "canvas", "interpolation": "srgb",
                 "stops": [{"offset": s["offset"], "color": s["color"]} for s in stops]}
        results[role] = {"gradient": value, "samples": stops}
        records.append({"evidence_id": eid, "source_sha256": scene["source"]["sha256"], "region": [x1, y1, x2 - x1, y2 - y1],
                        "object": f"tokens.{role}", "method": "pixel_sampling", "tool": f"{TOOL_VERSION} sample_colors.py",
                        "value": value, "units": "sRGB", "status": "measured", "confidence": "medium",
                        "justification": f"{int(n)} point samples along the declared axis",
                        "limitations": ["stop positions are sample points, not recovered original stops; interpolation curve unknown"]})
        if a.apply:
            scene["tokens"][role] = {"type": "color", "value": value, "space": "srgb", "status": "measured",
                                     "confidence": "medium", "evidence_ids": [eid]}
    add_evidence(tdir, records)
    # swatch strip for the annotated scan
    strip = Image.new("RGB", (160 * max(1, len(results)), 90), "white")
    d = ImageDraw.Draw(strip)
    for i, (role, r) in enumerate(results.items()):
        col = r.get("value") or r["gradient"]["stops"][0]["color"]
        d.rectangle([i * 160 + 8, 8, i * 160 + 152, 56], fill=col, outline="#888888")
        d.text((i * 160 + 8, 62), f"{role}\n{col}", fill="black")
    (tdir / "evidence").mkdir(exist_ok=True)
    strip.save(tdir / "evidence" / "swatches.png")
    if a.apply:
        write_json(tdir / "scene.json", scene)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "patches"} for k, v in results.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
