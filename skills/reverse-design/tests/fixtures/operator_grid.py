"""Operator-assisted scan of a flattened product grid (equal photo frames + centred captions on a flat ground).

  python operator_grid.py <template-id> --labels "A,B,C,D,E,F" --cols 3 --rows 2 --font FILE [--font FILE ...]

The operator supplies only what a person reads off the image (captions, grid shape, candidate fonts to try).
Every number is measured by the tools and stored as evidence before it is used: projection profiles -> frames and
gutters, corner radius, caption ink + baselines, role colours, ranked font candidates, render-fitted captions.
Photos without originals become bounded raster crops, one replaceable slot each. Font identity stays unknown.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from common import add_evidence, import_asset, now, read_json, template_dir, write_json  # noqa: E402


def tool(script, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"{script} failed: {r.stdout[-500:]} {r.stderr[-500:]}")
    return json.loads(r.stdout[r.stdout.index("{"):])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template")
    ap.add_argument("--labels", required=True, help="captions in reading order, comma-separated (manual observation)")
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--rows", type=int, default=2)
    ap.add_argument("--font", action="append", required=True, help="candidate font files to rank")
    ap.add_argument("--font-source", default="system_font", choices=["system_font", "supplied"], help="provenance of the font files")
    a = ap.parse_args()
    tid, labels = a.template, a.labels.split(",")
    tdir = template_dir(tid)
    scene = read_json(tdir / "scene.json")
    W, H, src = scene["canvas"]["width"], scene["canvas"]["height"], scene["source"]["sha256"]
    M = lambda *x: tool("measure.py", tid, *x)
    # pass 2: grid from projection profiles, then low-threshold ink refinement per frame
    # sensitive threshold: light photos on a white ground differ by only ~20-30 levels at their edges
    bands = M("profile", "--region", f"0,0,{W},{H}", "--axis", "y", "--min-gap", "6", "--threshold", "10", "--id", "ev-grid-rows")["bands"]
    photo_rows = [b for b in bands if b[1] - b[0] > 0.15 * H][:a.rows]
    cap_rows = [next(b for b in bands if b[0] > pr[1] and b[1] - b[0] <= 0.15 * H) for pr in photo_rows]
    frames = []
    for r, (y0, y1) in enumerate(photo_rows):
        cols = M("profile", "--region", f"0,{y0},{W},{y1 - y0}", "--axis", "x", "--min-gap", "6", "--threshold", "10",
                 "--id", f"ev-grid-cols-row{r + 1}")["bands"]
        if len(cols) != a.cols:
            raise SystemExit(f"row {r + 1}: found {len(cols)} columns, expected {a.cols}")
        for c, (x0, x1) in enumerate(cols):
            ib = M("ink", "--region", f"{x0 - 6},{y0 - 6},{x1 - x0 + 12},{y1 - y0 + 12}", "--threshold", "12",
                   "--id", f"ev-frame-{r + 1}-{c + 1}", "--object", "frames")["ink_box"]
            frames.append(ib)
    size = round(statistics.median([f[2] for f in frames] + [f[3] for f in frames]))
    xs = [round(statistics.median(frames[r * a.cols + c][0] for r in range(a.rows))) for c in range(a.cols)]
    ys = [round(statistics.median(frames[r * a.cols + c][1] for c in range(a.cols))) for r in range(a.rows)]
    radii = [M("radius", "--region", f"{f[0] - 10},{f[1] - 10},120,120", "--threshold", "12", "--id", f"ev-radius-frame-{i + 1}",
               "--object", "frames")["radius_estimate"] for i, f in ((0, frames[0]), (len(frames) - 1, frames[-1]))]
    radius = round(statistics.mean(radii), 2)
    # pass 3: captions (ink + baseline per cell)
    caps = []
    for i, name in enumerate(labels):
        r, c = divmod(i, a.cols)
        cy0, cy1 = cap_rows[r]
        caps.append(M("ink", "--region", f"{xs[c]},{cy0 - 6},{size},{cy1 - cy0 + 12}", "--id", f"ev-caption-{i + 1}", "--object", "typography"))
    # pass 4: role colours
    gut = f"{xs[0] + size + 3},{ys[0] + 40},{max(4, xs[1] - xs[0] - size - 6)},{size - 80}"
    tool("sample_colors.py", tid, "--sample", "background.canvas=5,5,25,25", "--sample", f"background.canvas={W - 30},5,25,25",
         "--sample", f"background.canvas=5,{H - 30},25,25", "--sample", f"background.canvas={gut}",
         *sum([["--ink-core", "text.caption=" + ",".join(map(str, caps[k]["ink_box"]))] for k in (0, len(caps) // 2, len(caps) - 1)], []), "--apply")
    # typography: rank candidates on the two widest captions, then render-fit every caption with the best one
    widest = sorted(range(len(caps)), key=lambda k: -caps[k]["ink_box"][2])[:2]
    ranked = {}
    for k in widest:
        b = caps[k]["ink_box"]
        rr = tool("font_candidates.py", tid, "--region", f"{b[0] - 3},{b[1] - 3},{b[2] + 6},{b[3] + 6}", "--text", labels[k],
                  "--object", f"caption-{k + 1}", *sum([["--font", f] for f in a.font], []))
        for x in rr["ranked"]:
            ranked.setdefault(x["file"], {"name": x["font"], "iou": [], "size": []})
            ranked[x["file"]]["iou"].append(x["iou"])
            ranked[x["file"]]["size"].append(x["size_px_by_height"])
        ranked_ev = rr["evidence_id"]
    order = sorted(ranked.items(), key=lambda kv: -statistics.mean(kv[1]["iou"]))
    best_file, best = order[0]
    seed = statistics.median(best["size"])
    fitted = []
    for i, name in enumerate(labels):
        r, c = divmod(i, a.cols)
        cy0, cy1 = cap_rows[r]
        # the baseline is the ink measurement (the provenance below says so); fitting it against a substitute font
        # would trade it for glyph-shape differences, so only size and x are fitted
        fitted.append(tool("fit_text.py", tid, "--region", f"{xs[c] + 10},{cy0 - 8},{size - 20},{cy1 - cy0 + 16}", "--text", name,
                           "--font", best_file, "--size", seed, "--x", xs[c] + size / 2, "--baseline", caps[i]["baseline_y"],
                           "--fit", "size,x", "--align", "center", "--object", f"n-caption-{i + 1}"))
    fsize = round(statistics.median(f["params"]["size"] for f in fitted), 2)
    font = import_asset(tdir, best_file, "font", a.font_source)
    add_evidence(tdir, [{"evidence_id": "ev-transcription", "source_sha256": src, "region": None, "object": "typography",
                         "method": "manual_observation", "tool": "operator reading (no OCR engine)", "value": labels,
                         "status": "observed", "confidence": "high", "justification": "short uppercase captions read at enlargement",
                         "limitations": ["candidate transcription; confirm with a second reader"]}])
    # author the model (reload: sample_colors --apply has written the role tokens since the first read)
    scene = read_json(tdir / "scene.json")
    crops = tdir / "evidence" / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    canon = Image.open(tdir / "source" / "canonical.png").convert("RGB")
    nodes = [{"id": "n-bg", "alias": "background", "type": "background", "role": "background", "parent": None,
              "fill": {"token": "background.canvas"}, "geometry": {"x": 0, "y": 0, "w": W, "h": H},
              "provenance": {"fill": {"status": "measured", "confidence": "high", "evidence_ids": ["ev-color-background-canvas"]}}}]
    slots, assets = [], {font["id"]: font}
    identity = {"status": "unknown", "candidates": [f"{v['name']} (IoU {statistics.mean(v['iou']):.2f})" for _, v in order[:3]],
                "evidence_ids": [ranked_ev], "resolving_probe": "original font file or source document"}
    for i, name in enumerate(labels):
        r, c = divmod(i, a.cols)
        x, y = xs[c], ys[r]
        crop = crops / f"photo-{i + 1}.png"
        canon.crop((x, y, x + size, y + size)).save(crop)
        asset = import_asset(tdir, crop, "image", "reference_crop", derived_from={"sha256": src, "box": [x, y, size, size]},
                             note="bounded raster sublayer cut from the flattened reference; original photo unavailable")
        assets[asset["id"]] = asset
        k, fp = f"{i + 1}", fitted[i]["params"]
        lh = round(fsize * 1.2, 2)
        nodes += [
            {"id": f"n-card-{k}", "alias": f"card-{k}", "type": "group", "role": "card", "parent": None,
             "children": [f"n-photo-{k}", f"n-caption-{k}"], "geometry": {"x": x, "y": y, "w": size, "h": fp["baseline"] - y + 8}},
            {"id": f"n-photo-{k}", "alias": f"photo-{k}", "type": "image", "role": "product_photo", "parent": f"n-card-{k}",
             "asset": asset["id"], "placement": {"fit": "fill", "focal": [0.5, 0.5], "scale": 1}, "mask": {"type": "rect", "radius": radius},
             "treatment": [], "effects": [], "geometry": {"x": x, "y": y, "w": size, "h": size}, "editability": "raster",
             "provenance": {"geometry": {"status": "measured", "confidence": "high", "evidence_ids": [f"ev-frame-{r + 1}-{c + 1}"], "note": "±1px (JPEG ringing)"},
                            "mask.radius": {"status": "measured", "confidence": "medium", "evidence_ids": ["ev-radius-frame-1", f"ev-radius-frame-{len(frames)}"]},
                            "asset": {"status": "observed", "confidence": "high", "note": "reference pixels reused, not a recovered original"},
                            "treatment": {"status": "unknown", "confidence": "unassessed", "resolving_probe": "original photos"}}},
            {"id": f"n-caption-{k}", "alias": f"caption-{k}", "type": "text", "role": "product_name", "parent": f"n-card-{k}",
             "content": name, "font": {"asset": font["id"], "weight": 700, "size": fsize, "identity": identity}, "align": "center",
             "direction": "ltr", "lang": "en", "first_baseline": fp["baseline"], "line_height": lh, "tracking": 0,
             "fill": {"token": "text.caption"}, "fit": {"policy": "strict", "max_lines": 1},
             "geometry": {"x": round(fp["x"] - size / 2, 3), "y": round(fp["baseline"] - lh + 6, 3), "w": size, "h": lh},
             "editability": "live",
             "provenance": {"content": {"status": "observed", "confidence": "high", "evidence_ids": ["ev-transcription"]},
                            "first_baseline": {"status": "measured", "confidence": "high", "evidence_ids": [f"ev-caption-{i + 1}"]},
                            "font": {"status": "inferred", "confidence": "low", "evidence_ids": [ranked_ev, fitted[i]["evidence_id"]]}}}]
        slots += [{"id": f"slot-photo-{k}", "role": "product_photo", "node": f"n-photo-{k}", "type": "image"},
                  {"id": f"slot-name-{k}", "role": "product_name", "node": f"n-caption-{k}", "type": "text", "fit": "strict",
                   "limits": {"max_lines": 1}}]
    gutter = xs[1] - xs[0] - size
    scene.update(nodes=nodes, slots=slots, assets=assets)
    scene["constraints"] = (
        [{"id": f"c-gutter-{r}-{c}", "type": "gap", "a": f"n-photo-{r * a.cols + c + 2}.left", "b": f"n-photo-{r * a.cols + c + 1}.right",
          "value": gutter, "tolerance": 1, "status": "measured"} for r in range(a.rows) for c in range(a.cols - 1)]
        + [{"id": f"c-caption-centre-{i + 1}", "type": "equal", "a": f"n-caption-{i + 1}.center_x", "b": f"n-photo-{i + 1}.center_x",
            "tolerance": 1, "status": "measured"} for i in range(len(labels))])
    claim = lambda v, st="inferred", conf="medium": {"value": v, "status": st, "confidence": conf, "evidence_ids": []}
    scene["communication"] = {
        "goal": claim("show the breadth of a product range in one placement"),
        "literal_message": claim(" · ".join(labels), "observed", "high"),
        "takeaway": claim("several distinct options exist; compare and pick"),
        "cta": claim(None, "observed", "high"),
        "word_image_relationship": claim("captioning: names label the evidence"),
        "mechanisms": [{"chain": ["equal frames in a strict grid, no hero", "row-by-row comparison", "choice: there is an option for you",
                                  "browse the range"], "status": "inferred", "confidence": "medium",
                        "competing": ["the most saturated photo may take first fixation and break equal weighting"]}],
        "hierarchy": {"order": [f"n-photo-{i + 1}" for i in range(len(labels))], "status": "inferred"}}
    scene["verification"]["expected_text"] = {f"n-caption-{i + 1}": n for i, n in enumerate(labels)}
    meta = scene["source"]["metadata"]
    m = lambda note, ev, conf="high": {"status": "measured", "note": note, "evidence_ids": list(ev), "confidence": conf}
    ob = lambda note, ev: {"status": "observed", "note": note, "evidence_ids": list(ev), "confidence": "high"}
    inf = lambda note, conf="medium", amb=None: dict({"status": "inferred", "note": note, "confidence": conf}, **({"ambiguity": amb} if amb else {}))
    unk = lambda note, probe: {"status": "unknown", "note": note, "ambiguity": [probe]}
    na = lambda note: {"status": "not_applicable", "note": note}
    frames_ev = [f"ev-frame-{r + 1}-{c + 1}" for r in range(a.rows) for c in range(a.cols)]
    cap_ev = [f"ev-caption-{i + 1}" for i in range(len(labels))]
    fit_ev = [f["evidence_id"] for f in fitted]
    scene["scan"]["coverage"].update({
        "composition": dict(m(f"{a.cols}x{a.rows} grid, {size}px frames, {gutter}px gutters", ["ev-grid-rows", "ev-grid-cols-row1"]), facets={
            "grid": m(f"{a.cols} columns x {a.rows} rows", ["ev-grid-rows", "ev-grid-cols-row1", "ev-grid-cols-row2"]),
            "spacing": m(f"gutter {gutter}px; caption baselines {fitted[0]['params']['baseline']:.1f} / {fitted[-1]['params']['baseline']:.1f}", frames_ev + cap_ev),
            "alignment": m("captions centred on their frames (constraint per caption)", fit_ev),
            "whitespace": m(f"margins {xs[0]}px left, {W - xs[-1] - size}px right", ["ev-grid-cols-row1"])}),
        "element_inventory": ob(f"background, {len(labels)} photos, {len(labels)} captions; no logo, CTA or rules", ["ev-grid-rows", "ev-transcription"]),
        "geometry": dict(m(f"frames ±1px, radius {radius}px", frames_ev), facets={
            "position_size": m("frame boxes and caption boxes", frames_ev + cap_ev),
            "radii_strokes": m(f"corner radius {radius}px (least-squares circle); no strokes", ["ev-radius-frame-1", f"ev-radius-frame-{len(frames)}"], "medium"),
            "transforms": ob("no rotation or skew visible", frames_ev)}),
        "color": dict(m("canvas + caption ink by role", ["ev-color-background-canvas", "ev-color-text-caption"]), facets={
            "role_tokens": m("background.canvas, text.caption", ["ev-color-background-canvas", "ev-color-text-caption"]),
            "gradients": inf("no layout gradients; gradients exist only inside photos", "high"),
            "opacity_blending": inf("no translucent layout elements visible", "high")}),
        "typography": dict(inf(f"identity UNKNOWN; best candidate {best['name']} (IoU {statistics.mean(best['iou']):.2f})", "low",
                               [f"{v['name']} IoU {statistics.mean(v['iou']):.2f}" for _, v in order[:3]]), facets={
            "text": ob("captions transcribed (manual observation, no OCR)", ["ev-transcription"]),
            "font_candidates": m("ranked by ink IoU with contact sheets", [ranked_ev], "medium"),
            "font_identity": unk("no source evidence names the font file", "original font file or source document"),
            "size_line_height": inf(f"{fsize}px fitted for the substitute font (conditional on that candidate)", "low"),
            "tracking": inf("0 assumed; tracking not separable from the substitute's widths", "low"),
            "baselines_alignment": m("baselines measured from ink and render-fitted; centred", cap_ev + fit_ev),
            "direction": ob("left-to-right Latin capitals", ["ev-transcription"])}),
        "image_treatment": dict(unk("photos are bounded reference crops; originals and grading recipe unknown", "original photos"), facets={
            "images": ob(f"{len(labels)} photographs", frames_ev),
            "crop_intent": unk("only the visible crop exists; how it was cropped from originals is unknown", "original photos"),
            "masks": m(f"rounded rectangle, radius {radius}px", ["ev-radius-frame-1"], "medium"),
            "treatment": unk("grading baked into pixels", "original photos")}),
        "depth_compositing": dict(ob("flat: photos sit on the ground, nothing overlaps", frames_ev), facets={
            "layering": ob("background, then photo + caption per card", frames_ev),
            "shadows": ob("no drop shadows around frames (edge profile flat)", frames_ev),
            "blend_modes": inf("normal blending everywhere (no evidence of other modes)", "medium")}),
        "surface_texture": dict(ob(f"flat ground; JPEG {meta.get('jpeg_subsampling', 'n/a')} artifacts", ["ev-src-metadata"]), facets={
            "textures": ob("no layout texture; JPEG block artifacts only", ["ev-src-metadata"])}),
        "lighting": na("no layout-level lighting; photos carry their own"),
        "hierarchy_attention": inf("equal-weight grid; the most saturated photo may take first fixation", "medium"),
        "message_mechanism": dict(inf("range/choice through a comparison grid", "medium"),
                                  facets={"message_delivery": inf("equal frames + names -> compare -> pick one", "medium",
                                                                  ["could also read as a catalogue index rather than an ad"])}),
        "character_theme": inf("clean catalogue, product-led", "medium"),
        "usage_context": inf("feed ad / catalogue overview; unsuited to single-hero offers", "low"),
        "output_requirements": unk("no brief supplied", "target channel, size and format from the brief")})
    scene["scan"]["state"] = "complete"
    write_json(tdir / "scene.json", scene)
    p = read_json(tdir / "passport.json")
    lab = lambda v, st="suggested": {"value": v, "status": st}
    p.update(character=lab("clean product catalogue"), goal=lab("show range breadth"), theme=lab("home furniture range"), mechanism=lab("comparison grid with captions", "inferred"),
             channels=lab(["social feed", "catalogue page"]), usage=lab("collection launches, range overviews"),
             unsuitable_for=lab("single hero product, price-led offers"), literal_message=lab(" · ".join(labels), "observed"),
             visual_signature=["flat ground", f"{a.cols}x{a.rows} equal photo grid", "small radius", "bold centred captions"],
             slots=[s["id"] for s in slots], unresolved=[f"font identity unknown (best candidate {best['name']})",
                                                         "original photos unavailable: photo slots are reference crops"], updated=now())
    write_json(tdir / "passport.json", p)
    print(json.dumps({"frames": [xs, ys, size], "radius": radius, "caption_size": fsize, "best_font": best["name"],
                      "baselines": [f["params"]["baseline"] for f in fitted]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
