"""Pixel measurements on the canonical reference, recorded as evidence.

  python measure.py <tid> ink     --region x,y,w,h [--bg auto|#RRGGBB] [--threshold 40] [--object NODE]
  python measure.py <tid> profile --region x,y,w,h --axis x|y [--min-gap 4]     # bands/gutters along an axis
  python measure.py <tid> edges   --start x,y --direction down|up|right|left [--length 400] [--min-step 8]
  python measure.py <tid> radius  --region x,y,w,h [--min-step 8]               # top-left corner radius of a shape
  python measure.py <tid> shadow  --probe x,y,down --probe x,y,right [--bg #RRGGBB] [--length 140]

ink: tight ink bounds + baseline (bottom of the dense rows) + enlarged crop; threshold-based, so soft shadows or
     glows touching the shape inflate it -> use `edges` for frames on shadowed grounds.
edges: sharp boundaries along a scanline (adjacent-pixel steps >= min-step, sub-pixel at the 50% point of the
     step); smooth gradients and soft shadows do not register.
shadow: joint fit of shared blur sigma + per-channel strength with one offset per probe (better conditioned than
     one profile). Opacity and colour are a family, not a value, on a uniform background.
Values are measurements of visible pixels, not recovered source parameters.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TOOL_VERSION, add_evidence, read_json, slugify, template_dir  # noqa: E402

STEPS = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}


def box_arg(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("expected x,y,w,h")
    return v


def load(tdir):
    return np.asarray(Image.open(tdir / "source" / "canonical.png").convert("RGB")).astype(np.int16)


def crop(a, box):
    x, y, w, h = [int(round(v)) for v in box]
    return a[y:y + h, x:x + w], x, y


def hex_rgb(spec):
    return np.array([int(spec[i:i + 2], 16) for i in (1, 3, 5)], np.int16)


def bg_color(c, spec):
    if spec and spec != "auto":
        return hex_rgb(spec)
    edge = np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]])
    return np.median(edge, axis=0).astype(np.int16)


def ink(tdir, box, bg="auto", thr=40):
    a = load(tdir)
    c, x0, y0 = crop(a, box)
    b = bg_color(c, bg)
    m = np.abs(c - b).max(axis=2) > thr
    ys, xs = np.nonzero(m)
    if not len(xs):
        return {"ink": None, "background": b.tolist()}
    rows = m.sum(axis=1)
    dense = np.nonzero(rows >= 0.5 * rows.max())[0]
    out = {"background": b.tolist(), "threshold": thr,
           "ink_box": [x0 + int(xs.min()), y0 + int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
           "baseline_y": y0 + int(dense.max()) + 1, "dense_top_y": y0 + int(dense.min()),
           "ink_height_dense": int(dense.max() - dense.min() + 1),
           "note": "baseline = bottom edge of rows holding >=50% of peak ink; valid for caps/x-height text, not for one-glyph or all-descender crops"}
    im = Image.fromarray(c.astype(np.uint8))
    k = max(1, min(8, 600 // max(1, im.width)))
    rel = f"evidence/crops/ink-{slugify(','.join(map(str, map(int, box))))}.png"
    (tdir / rel).parent.mkdir(parents=True, exist_ok=True)
    im.resize((im.width * k, im.height * k), Image.NEAREST).save(tdir / rel)
    out["artifact"] = rel
    return out


def bands(tdir, box, axis, min_gap=4, thr=40):
    a = load(tdir)
    c, x0, y0 = crop(a, box)
    m = np.abs(c - bg_color(c, "auto")).max(axis=2) > thr
    prof = m.any(axis=0 if axis == "x" else 1)
    off = x0 if axis == "x" else y0
    runs, start = [], None
    for i, v in enumerate(list(prof) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append([start, i])
            start = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    content = [[off + s, off + e] for s, e in merged]
    gaps = [content[i + 1][0] - content[i][1] for i in range(len(content) - 1)]
    lead = content[0][0] - off if content else None
    tail = (off + len(prof)) - content[-1][1] if content else None
    return {"axis": axis, "bands": content, "gaps": gaps, "leading_margin": lead, "trailing_margin": tail}


def step_positions(px, min_step):
    """Sub-pixel boundary positions (index units, boundary between i and i+1 = i+1) of sharp steps in a 1-D RGB line."""
    px = px.astype(np.float64)
    d = np.abs(np.diff(px, axis=0)).max(axis=1)
    out, i = [], 0
    while i < len(d):
        if d[i] < min_step:
            i += 1
            continue
        j = i
        while j + 1 < len(d) and d[j + 1] >= min_step / 3:  # antialiased steps spread over 2-3 px
            j += 1
        ch = int(np.argmax(np.abs(px[j + 1] - px[i])))
        v0, v1 = px[i, ch], px[j + 1, ch]
        cov = np.clip((px[i + 1:j + 1, ch] - v0) / (v1 - v0 if v1 != v0 else 1e-9), 0, 1)  # partial pixels
        out.append({"position": round(j + 1 - float(cov.sum()), 3), "step": float(d[i:j + 1].max()), "width_px": j - i + 1})
        i = j + 1
    return out


def edges(tdir, start, direction, length=400, min_step=8):
    a = load(tdir)
    dx, dy = STEPS[direction]
    x0, y0 = int(start[0]), int(start[1])
    H, W = a.shape[:2]
    n = min(length, (W - x0 if dx > 0 else x0 + 1 if dx < 0 else length), (H - y0 if dy > 0 else y0 + 1 if dy < 0 else length))
    px = np.array([a[y0 + dy * i, x0 + dx * i] for i in range(n)])
    found = step_positions(px, min_step)
    for e in found:  # canvas coordinate of the boundary
        e["canvas"] = round((x0 if dx else y0) + (e["position"] if (dx > 0 or dy > 0) else -e["position"] + 1), 3)
    return {"start": [x0, y0], "direction": direction, "min_step": min_step, "edges": found,
            "first": found[0]["canvas"] if found else None, "last": found[-1]["canvas"] if found else None,
            "note": "canvas = boundary coordinate between pixels (left/top edge of the first pixel after the step)"}


def radius(tdir, box, thr=40, min_step=None):
    a = load(tdir)
    c, x0, y0 = crop(a, box)
    if min_step:  # left boundary per row from sharp steps (robust to soft shadows)
        firsts = [(r, row[0]["position"]) for r in range(c.shape[0]) if (row := step_positions(c[r], min_step))]
        method = f"sharp-step scan per row (min_step {min_step})"
    else:
        m = np.abs(c - bg_color(c, "auto")).max(axis=2) > thr
        firsts = [(r, float(np.nonzero(m[r])[0].min())) for r in range(m.shape[0]) if m[r].any()]
        method = f"threshold > {thr}"
    if len(firsts) < 3:
        return {"radius_estimate": None, "method": method}
    top, left = firsts[0][0], min(p for _, p in firsts)
    pairs, straight = [], 0
    for r, p in firsts:  # curve rows plus a few straight rows that pin R
        pairs.append((r - top + 0.5, p - left))
        straight = straight + 1 if p - left < 0.5 else 0
        if straight >= 4:
            break
    rr, off = np.array(pairs).T
    # circle of radius R: inset(row centre y) = R - sqrt(R^2 - (R - y)^2) for y < R, else 0.
    # (Counting rows until the edge looks straight under-reads by ~sqrt(R).)
    pred = lambda R: np.where(rr < R, R - np.sqrt(np.clip(R ** 2 - (R - rr) ** 2, 0, None)), 0)
    best = min(np.arange(0.5, 200, 0.05), key=lambda R: float(((pred(R) - off) ** 2).sum()))
    return {"radius_estimate": round(float(best), 2), "left_insets_by_row": [round(v, 2) for v in off[:60]],
            "method": method + " + least-squares circle", "uncertainty_px": 1.0,
            "note": "R fitted to the per-row inset of the left edge below the shape top"}


def shadow(tdir, probes, length=140, bg=None):
    """Joint fit over probes leaving a caster edge on a uniform ground:
    r_ch(t) = A_ch * Phi((offset_probe - t) / sigma), t = px beyond the edge (pixel centres)."""
    from scipy.optimize import least_squares
    from scipy.special import ndtr

    a = load(tdir).astype(np.float64)
    t = np.arange(length) + 0.5
    lines = []
    for x0, y0, d in probes:
        dx, dy = STEPS[d]
        lines.append(np.array([a[int(y0 + dy * i), int(x0 + dx * i)] for i in range(length)]))
    ground = hex_rgb(bg).astype(np.float64) if bg else np.median(np.concatenate([ln[-15:] for ln in lines]), axis=0)
    R = [1 - ln / ground for ln in lines]
    k = len(probes)

    def resid(p):
        sig, A = max(p[0], 1e-3), np.array(p[1:4])
        return np.concatenate([(A[None, :] * ndtr((p[4 + i] - t[:, None]) / sig) - R[i]).ravel() for i in range(k)])

    fit = least_squares(resid, x0=[10, .2, .2, .2] + [5] * k, bounds=([0.3, 0, 0, 0] + [-60] * k, [80, 1, 1, 1] + [length] * k))
    sig, A, offs = fit.x[0], list(fit.x[1:4]), list(fit.x[4:])
    amax = max(A)
    return {"probes": [list(p) for p in probes], "ground": ground.tolist(), "ground_source": "declared" if bg else "probe tails",
            "sigma_px": round(sig, 3), "amplitude_per_channel": [round(v, 4) for v in A],
            "offsets_px": [round(o, 3) for o in offs], "rms_residual": float(np.sqrt(np.mean(fit.fun ** 2))),
            "canonical_solution": {"opacity": round(amax, 4), "color": "#" + "".join(f"{int(round(255 * (1 - v / amax))):02X}" for v in A)} if amax else None,
            "ambiguity": "opacity/colour family: any a >= max(A) with colour_ch = 255*(1 - A_ch/a); blend normal vs multiply indistinguishable on uniform ground",
            "note": "offset = distance from the caster edge to the shadow's 50% point along that probe (= shadow offset along it)"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template")
    ap.add_argument("what", choices=["ink", "profile", "edges", "radius", "shadow"])
    ap.add_argument("--region", type=box_arg)
    ap.add_argument("--start", type=lambda s: [float(v) for v in s.split(",")])
    ap.add_argument("--direction", choices=list(STEPS), default="down")
    ap.add_argument("--probe", action="append", default=[], type=lambda s: (float(s.split(",")[0]), float(s.split(",")[1]), s.split(",")[2]))
    ap.add_argument("--length", type=int)
    ap.add_argument("--min-step", type=float)
    ap.add_argument("--bg", default="auto")
    ap.add_argument("--threshold", type=int, default=40)
    ap.add_argument("--axis", choices=["x", "y"], default="x")
    ap.add_argument("--min-gap", type=int, default=4)
    ap.add_argument("--object", help="node/category this measurement supports")
    ap.add_argument("--id", help="evidence id (default derived from the inputs)")
    a = ap.parse_args()
    tdir = template_dir(a.template)
    how = f"thresholded difference from region background (>{a.threshold})"
    if a.what == "shadow":
        v = shadow(tdir, a.probe, a.length or 140, None if a.bg == "auto" else a.bg)
        a.region, how = None, "joint least-squares fit of a blurred-step model"
        key = "-".join(f"{int(x)}-{int(y)}-{d}" for x, y, d in a.probe)
    elif a.what == "edges":
        v = edges(tdir, a.start, a.direction, a.length or 400, a.min_step or 8)
        a.region, how = [a.start[0], a.start[1], 1, 1], f"adjacent-pixel steps >= {a.min_step or 8}"
        key = f"{int(a.start[0])}-{int(a.start[1])}-{a.direction}"
    else:
        key = "-".join(str(int(x)) for x in a.region)
        if a.what == "ink":
            v = ink(tdir, a.region, a.bg, a.threshold)
        elif a.what == "profile":
            v = bands(tdir, a.region, a.axis, a.min_gap, a.threshold)
        else:
            v = radius(tdir, a.region, a.threshold, a.min_step)
            how = v.get("method", how)
    eid = a.id or f"ev-{a.what}-{slugify(key)}"
    src = read_json(tdir / "scene.json")["source"]["sha256"]
    add_evidence(tdir, [{"evidence_id": eid, "source_sha256": src, "region": a.region, "object": a.object,
                         "method": "computed_measurement", "tool": f"{TOOL_VERSION} measure.py {a.what}", "value": v,
                         "units": "px", "uncertainty": "±1px (antialiasing/compression)", "status": "measured",
                         "confidence": {"radius": "medium", "shadow": "medium"}.get(a.what, "high"),
                         "justification": how, "artifacts": [v["artifact"]] if v.get("artifact") else []}])
    print(json.dumps({"evidence_id": eid, **v}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
