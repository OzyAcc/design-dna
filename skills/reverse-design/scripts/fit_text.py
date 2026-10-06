"""Fit a text node's size / tracking / position to the reference by rendering with the production renderer.

  python fit_text.py <tid> --region x,y,w,h --text "NEW SEASON" --font FILE --size 28 --x 80 --baseline 172
                     [--tracking 0] [--fit size,tracking,x,baseline] [--align left|center|right]
                     [--color #RRGGBB] [--bg #RRGGBB] [--weight 700] [--object NODE]

Coordinate descent, then Nelder-Mead for coupled parameters, minimising mean absolute error inside the region (reference vs a render of only that text over
the region's background colour). x is the anchor for the chosen alignment (left edge, centre or right edge of
the advance box). The results are fits FOR THIS CANDIDATE FONT; they never establish the font's identity.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TOOL_VERSION, add_evidence, read_json, slugify, template_dir  # noqa: E402
from measure import box_arg  # noqa: E402
from render_static import capture, launch  # noqa: E402

STEPS = {"size": [1, 0.25, 0.05], "x": [1, 0.25, 0.05], "baseline": [1, 0.25, 0.05], "tracking": [0.5, 0.1, 0.02]}


def glyph_regression(ref, rx, text, font):
    """Seed size/tracking/x for left-aligned LTR text from per-glyph ink-mass statistics (antialiasing preserves
    mass, whereas thresholded edges clip the faint extremes of round/diagonal glyphs and read narrow):
      spread:   std_x(glyph ink)  = s * std_x(outline)                      -> s = size/upm (tracking-free)
      centroid: mean_x(glyph ink) = x0 + s*(advances before i + mean_x(outline)) + tracking*i  -> x0, tracking
    Returns None when ink runs cannot be matched 1:1 to the visible characters (touching glyphs, ligatures)."""
    from fontTools.pens.statisticsPen import StatisticsPen
    from fontTools.ttLib import TTFont

    edge = np.concatenate([ref[0], ref[-1], ref[:, 0], ref[:, -1]])
    lum = ref @ [0.2126, 0.7152, 0.0722]
    bgl = np.median(edge, axis=0) @ [0.2126, 0.7152, 0.0722]
    d = np.abs(lum - bgl)
    core = np.quantile(d[d > 40], 0.7) if (d > 40).any() else None
    if core is None:
        return None
    col = np.clip(d / core, 0, 1).sum(axis=0)  # ink mass per column
    on = col > 0.002 * col.max()
    runs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j + 1 < len(on) and on[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    chars = [(k, c) for k, c in enumerate(text) if not c.isspace()]
    if len(runs) != len(chars):
        return None
    f = TTFont(font)
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm
    adv, stats = [], {}
    for c in text:
        g = cmap[ord(c)]
        adv.append(f["hmtx"][g][0])
        if not c.isspace() and c not in stats:
            pen = StatisticsPen(glyphset=gs)
            gs[g].draw(pen)
            stats[c] = (pen.meanX, pen.stddevX)
    meas = []
    for i0, i1 in runs:
        xs, w = np.arange(i0, i1 + 1) + 0.5, col[i0:i1 + 1]
        mx = float((xs * w).sum() / w.sum())
        var = float(((xs - mx) ** 2 * w).sum() / w.sum()) - 1 / 12  # remove pixel-box variance
        meas.append((rx + mx, np.sqrt(max(var, 1e-9))))
    sf = np.array([stats[c][1] for _, c in chars])
    sm = np.array([m[1] for m in meas])
    s = float((sm * sf).sum() / (sf ** 2).sum())
    A = np.array([[1, k] for k, _ in chars], float)
    y = np.array([m[0] - s * (sum(adv[:k]) + stats[c][0]) for (k, c), m in zip(chars, meas)])
    (x0, t), *_ = np.linalg.lstsq(A, y, rcond=None)
    return {"size": s * upm, "x": float(x0), "tracking": float(t), "glyphs_matched": len(chars),
            "note": "kerning ignored; ink-mass moments vs outline area moments (StatisticsPen)"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template")
    ap.add_argument("--region", type=box_arg, required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--font", required=True)
    ap.add_argument("--size", type=float, required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--baseline", type=float, required=True)
    ap.add_argument("--tracking", type=float, default=0)
    ap.add_argument("--fit", default="size,x,baseline")
    ap.add_argument("--align", choices=["left", "center", "right"], default="left")
    ap.add_argument("--color")
    ap.add_argument("--bg")
    ap.add_argument("--weight", type=float, default=700)
    ap.add_argument("--object")
    a = ap.parse_args()
    tdir = template_dir(a.template)
    rx, ry, rw, rh = [int(round(v)) for v in a.region]
    ref = np.asarray(Image.open(tdir / "source" / "canonical.png").convert("RGB"))[ry:ry + rh, rx:rx + rw].astype(np.float64)
    edge = np.concatenate([ref[0], ref[-1], ref[:, 0], ref[:, -1]])
    bg = a.bg or "#" + "".join(f"{int(v):02X}" for v in np.median(edge, axis=0))
    if a.color:
        fg = a.color
    else:  # ink core: farthest 30% from background
        far = np.abs(ref - np.median(edge, axis=0)).max(axis=2)
        core = ref[far >= np.quantile(far[far > 40], 0.7)] if (far > 40).any() else ref.reshape(-1, 3)
        fg = "#" + "".join(f"{int(v):02X}" for v in np.median(core, axis=0))
    anchor = {"left": "start", "center": "middle", "right": "end"}[a.align]
    from playwright.sync_api import sync_playwright

    p = {"size": a.size, "x": a.x, "baseline": a.baseline, "tracking": a.tracking}
    names = [n for n in a.fit.split(",") if n]
    seed = glyph_regression(ref, rx, a.text, a.font) if "tracking" in names and a.align == "left" else None
    if seed:
        p.update(size=seed["size"], x=seed["x"], tracking=seed["tracking"])
    evals = 0
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as tmp:
        b, ch = launch(pw)
        renderer = f"{ch} {b.version}"
        pg = b.new_page(viewport={"width": rw, "height": rh}, device_scale_factor=1)
        page = Path(tmp) / "fit.html"
        page.write_text(f'<meta charset="utf-8"><style>@font-face{{font-family:"f";src:url("{Path(a.font).resolve().as_uri()}");'
                        f'font-weight:1 1000}}html,body{{margin:0}}svg{{display:block}}</style>'
                        f'<svg xmlns="http://www.w3.org/2000/svg" width="{rw}" height="{rh}"><rect width="{rw}" height="{rh}" fill="{bg}"/>'
                        f'<text id="t" font-family="f" font-weight="{a.weight}" fill="{fg}" text-anchor="{anchor}" '
                        f'style="white-space:pre;font-synthesis:none;font-kerning:normal">{html.escape(a.text)}</text></svg>', encoding="utf-8")
        pg.goto(page.as_uri())
        if not pg.evaluate("document.fonts.load('20px f').then(f => f.length > 0)"):
            raise SystemExit(f"font failed to load: {a.font}")

        def shot(q):
            pg.evaluate("""(q) => { const t = document.getElementById('t'); t.setAttribute('font-size', q.size);
                t.setAttribute('x', q.x); t.setAttribute('y', q.baseline); t.setAttribute('letter-spacing', q.tracking); }""",
                        {"size": q["size"], "x": q["x"] - rx, "baseline": q["baseline"] - ry, "tracking": q["tracking"]})
            return np.asarray(Image.open(io.BytesIO(capture(pg, animations="disabled"))).convert("RGB")).astype(np.float64)

        def cost(q):
            nonlocal evals
            evals += 1
            return float(np.abs(shot(q) - ref).mean())

        def descend(p, best, scales):
            for scale in scales:
                improved = True
                while improved and evals < 900:
                    improved = False
                    for n in names:
                        for sgn in (1, -1):
                            q = dict(p, **{n: p[n] + sgn * STEPS[n][scale]})
                            c = cost(q)
                            if c < best - 1e-6:
                                p, best, improved = q, c, True
                                break
            return p, best

        best = start_cost = cost(p)
        p, best = descend(p, best, range(3))
        if len(names) > 1 and best > 1e-6:
            # coupled parameters (size vs tracking, size vs x) form ridges coordinate moves cannot follow
            from scipy.optimize import minimize

            x0 = np.array([p[n] for n in names])
            simplex = np.vstack([x0] + [x0 + np.eye(len(names))[i] * STEPS[n][0] for i, n in enumerate(names)])
            r = minimize(lambda v: cost(dict(p, **dict(zip(names, v)))), x0, method="Nelder-Mead",
                         options={"initial_simplex": simplex, "xatol": 0.005, "fatol": 1e-4, "maxfev": 400})
            if r.fun < best:
                p, best = dict(p, **dict(zip(names, r.x))), float(r.fun)
                p, best = descend(p, best, [2])
        fitted = shot(p)
        b.close()
    rel = f"evidence/crops/fit-{slugify(a.object or a.text)}.png"
    trip = np.hstack([ref, fitted, np.clip(np.abs(ref - fitted) * 4, 0, 255)]).astype(np.uint8)
    k = 4 if trip.shape[1] < 900 else 2
    (tdir / rel).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(trip).resize((trip.shape[1] * k, trip.shape[0] * k), Image.NEAREST).save(tdir / rel)
    out = {k2: round(v, 3) for k2, v in p.items()}
    eid = f"ev-fit-{slugify(a.object or a.text)}"
    add_evidence(tdir, [{"evidence_id": eid, "source_sha256": read_json(tdir / "scene.json")["source"]["sha256"],
                         "region": [rx, ry, rw, rh], "object": a.object, "method": "candidate_render_comparison",
                         "tool": f"{TOOL_VERSION} fit_text.py ({renderer})", "value": {"font": str(Path(a.font).resolve()), "params": out,
                         "fitted": names, "glyph_seed": seed, "align": a.align, "fill": fg, "background": bg, "mae_start": start_cost, "mae_end": best,
                         "evaluations": evals}, "units": "px", "status": "inferred", "confidence": "medium",
                         "justification": "render fit (coordinate descent + Nelder-Mead); parameters are conditional on the candidate font",
                         "artifacts": [rel], "resolving_probe": "original font file and source document"}])
    print(json.dumps({"evidence_id": eid, "params": out, "glyph_seed": seed, "fill": fg, "mae_start": round(start_cost, 3), "mae_end": round(best, 3),
                      "evaluations": evals, "artifact": rel}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
