"""Operator-assisted acceptance demonstrations 1 and 2 (called from run_acceptance.py).

T01 rebuilds the synthetic layered reference from measurements only: coarse operator region proposals ->
    measure.py / sample_colors.py / font_candidates.py / model fits. Ground truth is read ONLY at the end, to
    score recovered parameters. T02 scans an unfamiliar flattened product-grid JPEG with the same tools.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path[:0] = [str(SCRIPTS), str(HERE / "fixtures")]
from common import import_asset, read_json, template_dir, write_json  # noqa: E402
from compare_render import compare  # noqa: E402
from inspect_source import create_template  # noqa: E402
from render_static import render  # noqa: E402
from validate_model import editability_report  # noqa: E402

import fontset  # noqa: E402

SANS = fontset.paths("sans_candidates")
SERIF = fontset.paths("serif_candidates")


def tool(script, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{script} {args[:3]} failed: {r.stdout[-600:]} {r.stderr[-600:]}")
    return json.loads(r.stdout[r.stdout.index("{"):]) if "{" in r.stdout else r.stdout


def glyph(font, ch):
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    f = TTFont(font)
    gs, name = f.getGlyphSet(), f.getBestCmap()[ord(ch)]
    pen = BoundsPen(gs)
    gs[name].draw(pen)
    return {"bounds": pen.bounds, "advance": f["hmtx"][name][0], "upm": f["head"].unitsPerEm}


def box(b, pad=3):
    return f"{b[0] - pad},{b[1] - pad},{b[2] + 2 * pad},{b[3] + 2 * pad}"


def fit_treatment(src, ref):
    """Least-squares fit of SVG saturate(s) then contrast(c) mapping src->ref (sRGB 0..1)."""
    from scipy.optimize import least_squares

    def apply(p, x):
        s, c = p
        m = np.array([[.213 + .787 * s, .715 - .715 * s, .072 - .072 * s],
                      [.213 - .213 * s, .715 + .285 * s, .072 - .072 * s],
                      [.213 - .213 * s, .715 - .715 * s, .072 + .928 * s]])
        return np.clip(np.clip(x @ m.T, 0, 1) * c + (0.5 - 0.5 * c), 0, 1)

    fit = least_squares(lambda p: (apply(p, src) - ref).ravel(), x0=[1, 1], bounds=([0, 0.5], [2, 2]))
    return {"saturate": round(fit.x[0], 4), "contrast": round(fit.x[1], 4), "rms": float(np.sqrt(np.mean(fit.fun ** 2)))}


def measured_coverage(log, fl, fh, fc, f1) -> dict:
    """16-category coverage for the measured rebuild: every facet points at the evidence that produced it."""
    ev = lambda *keys: [log[k]["evidence_id"] for k in keys]
    fits = [fl[0]["evidence_id"], fh[0]["evidence_id"], fc[0]["evidence_id"], f1["evidence_id"]]
    colors = ["ev-color-background-paper", "ev-color-accent-primary", "ev-color-text-secondary", "ev-color-text-primary", "ev-color-cta-text"]
    m = lambda note, ids, conf="high": {"status": "measured", "note": note, "evidence_ids": list(ids), "confidence": conf}
    ob = lambda note, ids: {"status": "observed", "note": note, "evidence_ids": list(ids), "confidence": "high"}
    inf = lambda note, conf="medium", amb=None: dict({"status": "inferred", "note": note, "confidence": conf}, **({"ambiguity": amb} if amb else {}))
    unk = lambda note, amb: {"status": "unknown", "note": note, "ambiguity": [amb]}
    geo = ev("bar", "label", "h1", "h2", "hero_h", "hero_v", "pill", "cta", "logo")
    return {
        "input_canvas": m("1080x1350 PNG, sRGB assumed (untagged)", ["ev-src-metadata", "ev-src-canonical"]),
        "composition": dict(m("single column, centred hero", geo), facets={
            "grid": m("one column; hero centred on the canvas axis", ev("hero_h")), "spacing": m("stacking gaps from ink boxes", geo),
            "alignment": m("shared left edge: accent bar, label, headline, CTA", ev("bar", "label", "h1", "pill")),
            "whitespace": m("paper margins from ink extents", geo)}),
        "element_inventory": ob("bar, label, headline (2 lines), hero, CTA pill + text, translucent sheen, logo", geo),
        "geometry": dict(m("frames by edge scanlines, text by render fits", geo + fits), facets={
            "position_size": m("every node", geo), "radii_strokes": m("hero radius by circle fit; pill radius = h/2", ev("radius", "pill"), "medium"),
            "transforms": ob("no rotation visible", geo)}),
        "color": dict(m("five role tokens", colors), facets={
            "role_tokens": m("paper, accent, text primary/secondary, cta text", colors),
            "gradients": inf("only inside the photo asset", "high"),
            "opacity_blending": inf("sheen = white at a solved opacity (white is an assumption)", "medium", ["any (colour, opacity) pair with the same blend"])}),
        "typography": dict(m("render-fitted with the best candidates", fits, "medium"), facets={
            "text": ob("3 strings", ["ev-transcription"]),
            "font_candidates": m("ranked per text by ink IoU + fit residual", fits, "medium"),
            "font_identity": unk("best candidates are not proof of identity", "original font files or source document"),
            "size_line_height": m("render fits", fits, "medium"), "tracking": m("label tracking from ink-moment seed + fit", [fl[0]["evidence_id"]], "medium"),
            "baselines_alignment": m("render fits", fits), "direction": ob("ltr", ["ev-transcription"])}),
        "image_treatment": dict(m("supplied original placed and graded by model fit", ev("hero_h", "hero_v"), "medium"), facets={
            "images": ob("bag.png supplied as the original", ev("hero_h")),
            "crop_intent": m("cover with focal shift from correlation search", ev("hero_v"), "medium"),
            "masks": m("rounded rectangle, circle-fitted radius", ev("radius"), "medium"),
            "treatment": inf("saturate then contrast (order assumed)", "medium", ["contrast-then-saturate fits differently"])}),
        "depth_compositing": dict(m("shadow fitted on four probes", ev("shadow"), "medium"), facets={
            "layering": inf("bar, text, hero, CTA, sheen above pill, logo", "high"),
            "shadows": m("offset, blur and strength family from the joint probe fit", ev("shadow"), "medium"),
            "blend_modes": unk("multiply chosen; normal is indistinguishable on a uniform ground", "layered source or a second background")}),
        "surface_texture": dict(ob("flat paper", colors[:1]), facets={"textures": ob("none in the layout", colors[:1])}),
        "lighting": inf("soft light from above, implied by the shadow offset"),
        "hierarchy_attention": inf("headline -> hero -> CTA (hypothesis)"),
        "message_mechanism": dict(inf("promise + product as evidence + CTA"), facets={"message_delivery": inf("serif promise, product proof, one red action")}),
        "character_theme": inf("quiet editorial premium"),
        "usage_context": inf("social feed product launch (4:5)", "low"),
        "responsive_system": {"status": "unknown", "note": "a single still shows one state"},
        "output_requirements": unk("no brief supplied", "channel, size and format"),
    }


def t01(root: Path, fx: Path, ref: Path, record):
    o = root / "t01-synthetic-measured"
    o.mkdir(parents=True, exist_ok=True)
    tid = create_template(ref, "Editorial Product Spotlight (measured)", "user_supplied", tid="editorial-measured")["template_id"]
    tdir = template_dir(tid)
    M = lambda *a: tool("measure.py", tid, *a)
    log = {}
    # pass 2-3: elements + geometry (operator proposes coarse regions / scanlines; the tools measure)
    log["bar"] = bar = M("ink", "--region", "60,80,200,50", "--object", "n-accent-bar")
    log["label"] = lab = M("ink", "--region", "60,130,420,60", "--object", "n-label")
    log["h1"] = h1 = M("ink", "--region", "60,200,960,118", "--object", "n-headline")
    log["h2"] = h2 = M("ink", "--region", "60,318,960,110", "--object", "n-headline")
    # the hero frame sits on a shadowed ground: sharp-step scanlines, not thresholds
    log["hero_h"] = eh = M("edges", "--start", "100,740", "--direction", "right", "--length", "880", "--min-step", "8", "--object", "n-hero")
    log["hero_v"] = ev = M("edges", "--start", "200,400", "--direction", "down", "--length", "700", "--min-step", "8", "--object", "n-hero")
    hx, hy = eh["first"], ev["first"]
    hw, hh = eh["last"] - hx, ev["last"] - hy
    HX, HY, HW, HH = (int(round(v)) for v in (hx, hy, hw, hh))
    log["radius"] = rad = M("radius", "--region", f"{HX - 20},{HY - 20},120,120", "--min-step", "6", "--object", "n-hero")
    log["pill"] = pill = M("ink", "--region", "60,1130,420,140", "--object", "n-cta-pill")
    px_, py_, pw, ph = pill["ink_box"]
    log["cta"] = cta = M("ink", "--region", f"{px_ + 20},{py_ + 10},{375 - px_ - 20},{ph - 20}", "--object", "n-cta-text")
    log["logo"] = logo = M("ink", "--region", "860,1150,160,110", "--object", "n-logo")
    # pass 4: colour by role (before the shadow fit, which needs the declared paper colour)
    log["colors"] = tool("sample_colors.py", tid, "--sample", "background.paper=20,20,40,40", "--sample", "background.paper=1000,20,60,60",
                         "--sample", "background.paper=600,1290,100,40", "--sample", "accent.primary=90,103,100,6",
                         "--sample", "accent.primary=100,1165,30,60", "--ink-core", "text.secondary=" + ",".join(map(str, lab["ink_box"])),
                         "--ink-core", "text.primary=" + ",".join(map(str, h2["ink_box"])),
                         "--ink-core", "cta.text=" + ",".join(map(str, cta["ink_box"])), "--apply")
    paper_hex = read_json(tdir / "scene.json")["tokens"]["background.paper"]["value"]
    # pass 6: shadow - 4 probes, shared blur + strength, one offset per side
    log["shadow"] = sh = M("shadow", "--probe", f"{HX + HW // 2},{HY + HH},down", "--probe", f"900,{HY - 1},up",
                           "--probe", f"{HX + HW},{HY + HH // 2},right", "--probe", f"{HX - 1},{HY + HH // 2},left",
                           "--bg", paper_hex, "--length", "130", "--object", "n-hero")
    off = dict(zip(("down", "up", "right", "left"), sh["offsets_px"]))
    dyv, dxv, spread = (off["down"] - off["up"]) / 2, (off["right"] - off["left"]) / 2, (off["down"] + off["up"]) / 2
    # translucent sheen: circle through sharp boundary points (white-over-paper step is faint -> min-step 3)
    pts = []
    for x in (460, 475, 490, 505, 520):
        e = M("edges", "--start", f"{x},1095", "--direction", "down", "--length", "180", "--min-step", "3", "--object", "n-sheen")
        if len(e["edges"]) >= 2:
            pts += [(x + .5, e["first"]), (x + .5, e["last"])]
    for y in (1150, 1170, 1190, 1210, 1230):
        e = M("edges", "--start", f"445,{y}", "--direction", "right", "--length", "120", "--min-step", "3", "--object", "n-sheen")
        if e["edges"]:
            pts.append((e["first"], y + .5))
    P = np.array(pts)
    sol = np.linalg.lstsq(np.c_[2 * P, np.ones(len(P))], (P ** 2).sum(1), rcond=None)[0]
    ccx, ccy = float(sol[0]), float(sol[1])
    cr = float(np.sqrt(sol[2] + ccx ** 2 + ccy ** 2))
    canon8 = np.asarray(Image.open(tdir / "source" / "canonical.png").convert("RGB"))
    paper = np.array([int(paper_hex[i:i + 2], 16) for i in (1, 3, 5)], float)
    obs = np.median(canon8[int(ccy) - 6:int(ccy) + 6, int(ccx + cr * 0.45):int(ccx + cr * 0.65)].reshape(-1, 3), axis=0)
    alpha = float(np.mean((obs - paper) / (255 - paper)))
    log["sheen"] = {"points": pts, "cx": ccx, "cy": ccy, "r": cr, "alpha_white": alpha}

    # typography: rank candidates (font_candidates.py), seed each from its own ink-based size estimate, then render-fit
    # with the production renderer; lowest residual wins. Identity stays unknown (no source evidence).
    def fits(ink_m, text, fonts, fit, align, obj, tracked=False):
        ib = ink_m["ink_box"]
        cands = tool("font_candidates.py", tid, "--region", box(ib), "--text", text, "--object", obj,
                     *sum([["--font", f] for f in fonts], []))["ranked"]
        rows = []
        for c in cands:
            s0 = c["size_px_by_height"] if tracked else c["size_px_by_width"]
            g = glyph(c["file"], text[0])
            x0 = ib[0] - g["bounds"][0] * s0 / g["upm"] if align == "left" else ib[0] + ib[2] / 2
            tr0 = (ib[2] - ib[2] * s0 / c["size_px_by_width"]) / (len(text) - 1) if tracked else 0
            r = tool("fit_text.py", tid, "--region", box(ib, 6), "--text", text, "--font", c["file"], "--size", s0, "--x", x0,
                     "--baseline", ink_m["baseline_y"], "--tracking", tr0, "--fit", fit, "--align", align,
                     "--object", f"{obj}-{Path(c['file']).stem}")
            rows.append({"file": c["file"], "name": c["font"], "seed": {"size": s0, "x": x0, "tracking": tr0}, **r})
        return sorted(rows, key=lambda r: r["mae_end"])

    log["fit_label"] = fl = fits(lab, "NEW SEASON", SANS, "size,tracking,x,baseline", "left", "n-label", tracked=True)
    log["fit_head2"] = fh = fits(h2, "quiet confidence.", SERIF, "size,x,baseline", "left", "n-headline-2")
    hsize = fh[0]["params"]["size"]
    log["fit_head1"] = f1 = tool("fit_text.py", tid, "--region", box(h1["ink_box"], 6), "--text", "Carry the", "--font", fh[0]["file"],
                                 "--size", hsize, "--x", fh[0]["params"]["x"], "--baseline", h1["baseline_y"], "--fit", "x,baseline",
                                 "--align", "left", "--object", "n-headline-1")
    log["fit_cta"] = fc = fits(cta, "Shop the edit", SANS, "size,x,baseline", "center", "n-cta-text")
    lsize, tracking, x_label = fl[0]["params"]["size"], fl[0]["params"]["tracking"], fl[0]["params"]["x"]
    x_head = (fh[0]["params"]["x"] + f1["params"]["x"]) / 2
    lh = fh[0]["params"]["baseline"] - f1["params"]["baseline"]
    csize, cx_cta = fc[0]["params"]["size"], fc[0]["params"]["x"]
    # pass 5: image placement + treatment (supplied original asset; candidate-model fits)
    asset = Image.open(fx / "bag.png").convert("RGB")
    k = max(hw / asset.width, hh / asset.height)
    sc = np.asarray(asset.resize((round(asset.width * k), round(asset.height * k)), Image.BICUBIC)).astype(float) / 255
    rf = canon8[HY:HY + HH, HX:HX + HW].astype(float) / 255
    I = (slice(40, HH - 40), slice(40, HW - 40))
    norm = lambda a: (a - a.mean(axis=(0, 1))) / (a.std(axis=(0, 1)) + 1e-6)
    shifts = [(sy, sx) for sy in range(sc.shape[0] - HH + 1) for sx in range(sc.shape[1] - HW + 1)]
    sy, sx = min(shifts, key=lambda s: np.abs(norm(sc[s[0]:s[0] + HH, s[1]:s[1] + HW][I]) - norm(rf[I])).mean())
    focal = [sx / (sc.shape[1] - HW) if sc.shape[1] > HW else 0.5, sy / (sc.shape[0] - HH) if sc.shape[0] > HH else 0.5]
    log["treatment"] = tr = fit_treatment(sc[sy:sy + HH, sx:sx + HW][I][::4, ::4].reshape(-1, 3), rf[I][::4, ::4].reshape(-1, 3))
    log["focal"] = {"shift": [sx, sy], "focal": focal}
    # author the measured scene
    scene = read_json(tdir / "scene.json")
    fonts = {k2: import_asset(tdir, r[0]["file"], "font", fontset.source()) for k2, r in (("label", fl), ("head", fh), ("cta", fc))}
    bag = import_asset(tdir, fx / "bag.png", "image", "supplied", note="original asset supplied with the layered source")
    lg = json.loads((fx / "logo.json").read_text())
    scene["assets"].update({a["id"]: a for a in list(fonts.values()) + [bag]})
    unk = lambda rows: {"status": "unknown", "candidates": [f"{r['name']} (mae {r['mae_end']})" for r in rows[:3]],
                        "evidence_ids": [r["evidence_id"] for r in rows[:3]], "resolving_probe": "source font file or document"}
    ms = {"*": {"status": "measured", "confidence": "high", "note": "measure.py / sample_colors.py"}}
    T = lambda nid, alias, content, fk, size, x, w, base, lhh, fill, align, track, rows: {
        "id": nid, "alias": alias, "type": "text", "role": alias, "parent": None, "content": content,
        "font": {"asset": fonts[fk]["id"], "weight": 700, "size": round(size, 3), "identity": unk(rows)}, "align": align, "direction": "ltr",
        "lang": "en", "first_baseline": round(base, 3), "line_height": round(lhh, 3), "tracking": round(track, 3), "fill": {"token": fill},
        "fit": {"policy": "strict", "max_lines": content.count("\n") + 1},
        "geometry": {"x": round(x, 3), "y": round(base - lhh * 0.8, 3), "w": round(w, 3), "h": round(lhh * (content.count("\n") + 1), 3)},
        "editability": "live", "provenance": {"*": {"status": "inferred", "confidence": "medium", "evidence_ids": [rows[0]["evidence_id"]],
                                                    "note": "render-fit with the best candidate font; conditional on that candidate"}}}
    b = bar["ink_box"]
    scene["nodes"] = [
        {"id": "n-bg", "type": "background", "role": "background", "parent": None, "fill": {"token": "background.paper"},
         "geometry": {"x": 0, "y": 0, "w": 1080, "h": 1350}, "provenance": ms},
        {"id": "n-accent-bar", "alias": "accent-bar", "type": "shape", "shape": "rect", "role": "accent", "parent": None,
         "fill": {"token": "accent.primary"}, "geometry": {"x": b[0], "y": b[1], "w": b[2], "h": b[3]}, "provenance": ms},
        T("n-label", "label", "NEW SEASON", "label", lsize, x_label, 1080 - 2 * x_label, fl[0]["params"]["baseline"], round(lsize * 1.2, 2),
          "text.secondary", "left", tracking, fl),
        T("n-headline", "headline", "Carry the\nquiet confidence.", "head", hsize, x_head, 1080 - 2 * x_head, f1["params"]["baseline"], lh,
          "text.primary", "left", 0, fh),
        {"id": "n-hero", "alias": "hero", "type": "image", "role": "hero", "parent": None, "asset": bag["id"],
         "placement": {"fit": "cover", "focal": [round(f, 3) for f in focal], "scale": 1}, "mask": {"type": "rect", "radius": rad["radius_estimate"]},
         "treatment": [{"op": "saturate", "amount": tr["saturate"]}, {"op": "contrast", "amount": tr["contrast"]}],
         "effects": [{"id": "cast_shadow", "type": "drop_shadow", "kind": "cast", "enabled": True, "dx": round(dxv, 2), "dy": round(dyv, 2),
                      "blur": sh["sigma_px"], "spread": round(max(0.0, spread), 2), "color": sh["canonical_solution"]["color"],
                      "opacity": sh["canonical_solution"]["opacity"], "blend": "multiply"}],
         "geometry": {"x": round(hx, 3), "y": round(hy, 3), "w": round(hw, 3), "h": round(hh, 3)}, "editability": "raster",
         "provenance": {"*": ms["*"], "effects": {"status": "inferred", "confidence": "medium", "note": "opacity/colour family member; blend mode unresolved"},
                        "treatment": {"status": "inferred", "confidence": "medium", "note": "least-squares fit, order saturate->contrast assumed"}}},
        {"id": "n-cta-pill", "alias": "cta-pill", "type": "shape", "shape": "rect", "role": "cta", "parent": None, "radius": ph / 2,
         "fill": {"token": "accent.primary"}, "geometry": {"x": px_, "y": py_, "w": pw, "h": ph}, "provenance": ms},
        T("n-cta-text", "cta", "Shop the edit", "cta", csize, cx_cta - pw / 2, pw, fc[0]["params"]["baseline"], round(csize * 1.3, 2),
          "cta.text", "center", 0, fc),
        {"id": "n-sheen", "alias": "sheen", "type": "shape", "shape": "ellipse", "role": "decoration", "parent": None, "fill": "#FFFFFF",
         "opacity": round(alpha, 3), "geometry": {"x": round(ccx - cr, 3), "y": round(ccy - cr, 3), "w": round(2 * cr, 3), "h": round(2 * cr, 3)},
         "provenance": {"*": {"status": "inferred", "confidence": "medium", "note": "least-squares circle through boundary points; white assumed, opacity solved over paper"}}},
        {"id": "n-logo", "alias": "logo", "type": "path", "role": "logo", "parent": None, "path": lg["d"], "path_box": lg["box"],
         "fill": {"token": "text.primary"}, "geometry": dict(zip("xywh", logo["ink_box"])), "provenance": ms}]
    # replaceable roles the operator identified (a scan without slots cannot claim editability)
    scene["slots"] = [
        {"id": "slot-headline", "role": "headline", "node": "n-headline", "type": "text", "fit": "strict", "limits": {"max_lines": 2}},
        {"id": "slot-label", "role": "label", "node": "n-label", "type": "text", "fit": "strict"},
        {"id": "slot-hero", "role": "hero", "node": "n-hero", "type": "image", "treatments_allowed": ["saturate", "contrast"]},
        {"id": "slot-cta", "role": "cta", "node": "n-cta-text", "type": "text", "fit": "strict"},
        {"id": "slot-accent", "role": "accent", "node": "n-accent-bar", "type": "color"},
        {"id": "slot-logo", "role": "logo", "node": "n-logo", "type": "logo"}]
    scene["verification"]["expected_text"] = {"n-label": "NEW SEASON", "n-headline": "Carry the\nquiet confidence.", "n-cta-text": "Shop the edit"}
    from common import add_evidence

    add_evidence(tdir, [{"evidence_id": "ev-transcription", "source_sha256": scene["source"]["sha256"], "region": None, "object": "typography",
                         "method": "manual_observation", "tool": "operator reading (no OCR engine)", "value": scene["verification"]["expected_text"],
                         "status": "observed", "confidence": "high", "justification": "three short English strings read at enlargement"}])
    scene["scan"] = {"state": "complete", "coverage": measured_coverage(log, fl, fh, fc, f1)}
    write_json(tdir / "scene.json", scene)
    pp = read_json(tdir / "passport.json")
    lab = lambda v, st="suggested": {"value": v, "status": st}
    pp.update(character=lab("quiet editorial premium"), theme=lab("everyday luxury accessories"), goal=lab("present one premium product"),
              usage=lab("single-product launches on social feeds"), unsuitable_for=lab("range overviews, price-led offers"),
              literal_message=lab("Carry the quiet confidence. Shop the edit.", "observed"), takeaway=lab("premium without shouting", "inferred"),
              mechanism=lab("serif promise -> product as evidence -> single red call to action", "inferred"),
              unresolved=["font identity unknown (best candidates rendered)", "shadow opacity/colour is a family, blend mode unresolved",
                          "treatment order saturate->contrast assumed"])
    write_json(tdir / "passport.json", pp)
    write_json(o / "measurements.json", log)
    r = render(scene, tdir, o / "render", isolate=True, formats=("png", "svg"))
    rep = compare(tdir / "source" / "canonical.png", r["png"], o / "compare", scene, r, "editable_close", "editable_rendering", editability_report(scene))
    # score against ground truth (read only now)
    gt = {n["id"]: n for n in read_json(template_dir("fixture-layered-source") / "scene.json")["nodes"]}
    me = {n["id"]: n for n in scene["nodes"]}
    geo = {nid: max(abs(me[nid]["geometry"][k] - gt[nid]["geometry"][k]) for k in "xywh") for nid in ("n-accent-bar", "n-hero", "n-cta-pill", "n-sheen", "n-logo")}
    gfx, mfx = gt["n-hero"]["effects"][0], me["n-hero"]["effects"][0]
    A_gt = [gfx["opacity"] * (1 - int(gfx["color"][i:i + 2], 16) / 255) for i in (1, 3, 5)]
    errs = {"geometry_max_px": geo, "label_size_pct": abs(lsize / 28 - 1) * 100, "head_size_pct": abs(hsize / 84 - 1) * 100,
            "cta_size_pct": abs(csize / 34 - 1) * 100, "label_tracking_px": abs(tracking - 4),
            "baselines_px": {k: abs(me[k]["first_baseline"] - gt[k]["first_baseline"]) for k in ("n-label", "n-headline", "n-cta-text")},
            "x_px": {"n-label": abs(x_label - 80), "n-headline": abs(x_head - 80), "n-cta-text": abs(cx_cta - 260)}, "line_height_px": abs(lh - 96),
            "radius_px": abs(rad["radius_estimate"] - 32), "shadow_dx_px": abs(mfx["dx"]), "shadow_dy_px": abs(mfx["dy"] - 18), "shadow_sigma_px": abs(mfx["blur"] - 22),
            "shadow_amplitude_max_err": max(abs(a - b2) for a, b2 in zip(A_gt, sh["amplitude_per_channel"])), "shadow_spread_px": spread,
            "saturate_err": abs(tr["saturate"] - 0.85), "contrast_err": abs(tr["contrast"] - 1.08), "focal_y_err": abs(focal[1] - 0.55),
            "sheen_alpha_err": abs(alpha - 0.35), "fonts_top": [fl[0]["name"], fh[0]["name"], fc[0]["name"]], "pixel_verdict": rep["overall"]}
    write_json(o / "scores.json", errs)
    true_faces = [fontset.full_name(fontset.path(k)) for k in ("sans", "serif", "sans")]
    record(1, "Rebuild a known layered reference from its flattened image + supplied photo, logo and candidate fonts", {
        "geometry of shapes/frames within 1px": all(v <= 1 for v in geo.values()) or geo,
        "text baselines within 1px; x within 1px": all(v <= 1 for v in errs["baselines_px"].values()) and all(v <= 1 for v in errs["x_px"].values()) or [errs["baselines_px"], errs["x_px"]],
        "font sizes within 1.5%; line height within 1px; tracking within 0.5px": errs["label_size_pct"] <= 1.5 and errs["head_size_pct"] <= 1.5 and errs["cta_size_pct"] <= 1.5 and errs["line_height_px"] <= 1 and errs["label_tracking_px"] <= 0.5
        or {k: errs[k] for k in ("label_size_pct", "head_size_pct", "cta_size_pct", "line_height_px", "label_tracking_px")},
        "best font candidates are the true faces (identity still unknown: no source evidence)": errs["fonts_top"] == true_faces or errs["fonts_top"],
        "live text content correct": rep["checks"]["typography"] and all(v["status"] == "pass" for v in rep["checks"]["typography"].values()),
        "mask radius within 2px": errs["radius_px"] <= 2 or errs["radius_px"],
        "shadow offset/blur within 1.5px; GT opacity+colour inside the measured family (±0.02)": errs["shadow_dx_px"] <= 1.5 and errs["shadow_dy_px"] <= 1.5 and errs["shadow_sigma_px"] <= 1.5 and errs["shadow_amplitude_max_err"] <= 0.02
        or {k: errs[k] for k in ("shadow_dx_px", "shadow_dy_px", "shadow_sigma_px", "shadow_amplitude_max_err")},
        "treatment saturate/contrast within 0.05; focal within 0.1": errs["saturate_err"] <= 0.05 and errs["contrast_err"] <= 0.05 and errs["focal_y_err"] <= 0.1
        or {k: errs[k] for k in ("saturate_err", "contrast_err", "focal_y_err")},
        "sheen opacity within 0.03 (white assumed)": errs["sheen_alpha_err"] <= 0.03 or errs["sheen_alpha_err"],
        "the rebuild itself passes editable_close against the reference": rep["overall"]["status"] == "pass" or dict(
            rep["overall"], regions={k.split(".", 1)[1]: {m: rep["checks"]["regions"][k.split(".", 1)[1]][m] for m in ("ssim", "unequal_fraction", "max_channel_error")}
                                     for k in rep["overall"]["failed"] if k.startswith("regions.")},
            fits={k: {"font": rows[0]["name"], "params": rows[0]["params"], "seed": rows[0]["seed"], "mae_end": rows[0]["mae_end"]}
                  for k, rows in (("label", fl), ("headline", fh), ("cta", fc))},
            renderer="{channel} {browser_version}".format(**r["render_profile"])),
    }, [o / "scores.json", o / "measurements.json", o / "compare" / "side_by_side.png", o / "compare" / "diff_heatmap.png"],
        notes=f"pixel verdict (editable_close): {rep['overall']['status']}; failed={rep['overall'].get('failed')}")


def t02(root: Path, fx: Path, record):
    """Unfamiliar flattened reference: a 6-up product grid drawn by Pillow/FreeType (not the engine's renderer),
    captions in a font outside the candidate list when available, lossy 4:2:0 JPEG. Truth is read only to score."""
    o = root / "t02-unfamiliar-flattened"
    o.mkdir(parents=True, exist_ok=True)
    truth = json.loads((fx / "grid_truth.json").read_text())
    tid = create_template(fx / "grid_flattened.jpg", "Product Grid Six-Up", "user_supplied")["template_id"]
    cands = SANS + fontset.paths("grid_extra_candidates")
    r = subprocess.run([sys.executable, str(HERE / "fixtures" / "operator_grid.py"), tid, "--labels", ",".join(truth["labels"]),
                        "--cols", "3", "--rows", "2", "--font-source", fontset.source(), *sum([["--font", f] for f in cands], [])],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"operator_grid.py failed: {r.stdout[-600:]} {r.stderr[-600:]}")
    got = json.loads(r.stdout[r.stdout.index("{"):])
    tool("annotate_scan.py", tid)
    import dna

    rec = dna.reconstruct(tid, "editable")
    tdir = template_dir(tid)
    scene, passport, rep = read_json(tdir / "scene.json"), read_json(tdir / "passport.json"), read_json(rec["report"])
    for f in ("evidence/annotated.png", "evidence/scan_report.md"):
        shutil.copy2(tdir / f, o / Path(f).name)
    shutil.copy2(Path(rec["report"]).parent / "side_by_side.png", o / "side_by_side.png")
    regions = rep["checks"]["regions"]
    xs, ys, size = got["frames"]
    frame_err = max([abs(x - tf[0]) for x, tf in zip(xs, truth["frames"][:3])] + [abs(y - truth["frames"][3 * i][1]) for i, y in enumerate(ys)]
                    + [abs(size - truth["frames"][0][2])])
    cap_fail = [k for k, v in regions.items() if "caption" in k and v["status"] != "pass"]
    meta = scene["source"]["metadata"]
    write_json(o / "scores.json", {"operator_output": got, "truth": truth, "frame_max_err_px": frame_err, "caption_regions_failing": cap_fail,
                                   "verdict": rep["overall"]})
    record(2, "Scan an unfamiliar flattened reference; keep uncertainty; measured editable baseline", {
        "all 16 scan categories have a result": len(scene["scan"]["coverage"]) == 16,
        "JPEG compression recorded in source evidence": meta.get("jpeg_subsampling") == "4:2:0" or meta,
        "frames within 1.5px of hidden truth; radius within 2px": (frame_err <= 1.5 and abs(got["radius"] - truth["radius"]) <= 2) or {"frame_err": frame_err, "radius": got["radius"]},
        "caption baselines within 1px of hidden truth": all(abs(b - truth["baselines"][i // 3]) <= 1 for i, b in enumerate(got["baselines"])) or got["baselines"],
        "font identity stays unknown, ranked candidates + contact sheet kept": all(n["font"]["identity"]["status"] == "unknown" for n in scene["nodes"] if n["type"] == "text")
        and any((tdir / "evidence" / "fonts").glob("candidates-*.png")),
        "photo slots reproduce exactly (region SSIM >= 0.99)": all(v["status"] == "pass" for k, v in regions.items() if "photo" in k),
        "readiness matches the verdict (font mismatch -> partial_baseline, never hidden)":
            passport["readiness"] == ("partial_baseline" if rep["overall"]["status"] != "pass" else "editable_close") and len(passport["unresolved"]) >= 2,
        "every slot independently editable (no shortcut)": rep["checks"]["editability"]["status"] == "pass",
    }, [o / "annotated.png", o / "scan_report.md", o / "side_by_side.png", o / "scores.json"],
        notes=f"captions drawn in {truth['label_font']} (not a candidate); best substitute {got['best_font']}; failing caption regions: {cap_fail}")


def run(root, fx, ref, record, want):
    for n, fn in ((1, lambda: t01(root, fx, ref, record)), (2, lambda: t02(root, fx, record))):
        if want(n):
            try:
                fn()
            except Exception as e:
                import traceback

                record(n, f"crashed: T{n:02d}", {"ran without crashing": f"{e.__class__.__name__}: {e}"}, notes=traceback.format_exc()[-1500:])
