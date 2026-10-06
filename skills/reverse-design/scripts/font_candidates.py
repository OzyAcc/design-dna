"""Rank candidate font files against a reference text crop. Identity stays unknown unless source evidence resolves it.

  python font_candidates.py <tid> --region x,y,w,h --text "TURINO" --font C:/Windows/Fonts/arialbd.ttf --font ...
                            [--object NODE] [--source-evidence EVIDENCE_ID] [--apply]

Each candidate is rendered with the production renderer (Playwright/Edge), scaled to the reference ink height,
and scored by ink-mask IoU (left-aligned) plus width error. A contact sheet is saved. Candidates within 0.01 IoU
of the best are reported as indistinguishable at this resolution. --apply records the ranked candidates on the
node (identity.status stays "unknown" unless a source_extraction record names the top file's hash) and pins the
top candidate as the approximate render font.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (TOOL_VERSION, add_evidence, find_node, font_names, import_asset, load_evidence,  # noqa: E402
                    read_json, sha256_file, slugify, template_dir, write_json)
from measure import box_arg  # noqa: E402
from render_static import launch  # noqa: E402

THR = 40
TIE = 0.01
RENDER_PX = 200  # candidates are rendered at this size; size estimates scale from it


def tight_mask(rgb, bg=None):
    a = rgb.astype(np.int16)
    if bg is None:
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        bg = np.median(edge, axis=0)
    m = np.abs(a - np.array(bg)).max(axis=2) > THR
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def scale_mask(m, h):
    w = max(1, round(m.shape[1] * h / m.shape[0]))
    im = Image.fromarray((m * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)
    return np.asarray(im) >= 128


def iou(a, b):
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    pa, pb = np.zeros((h, w), bool), np.zeros((h, w), bool)
    pa[:a.shape[0], :a.shape[1]], pb[:b.shape[0], :b.shape[1]] = a, b
    u = np.count_nonzero(pa | pb)
    return np.count_nonzero(pa & pb) / u if u else 0.0


def render_candidates(text, fonts):
    from playwright.sync_api import sync_playwright

    import html
    import tempfile

    out = []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        b, ch = launch(p)
        pg = b.new_page(device_scale_factor=1)
        for i, f in enumerate(fonts):
            page = Path(tmp) / f"c{i}.html"
            page.write_text(f'<meta charset="utf-8"><style>@font-face{{font-family:"c{i}";src:url("{Path(f).resolve().as_uri()}");'
                            f'font-weight:1 1000}}body{{margin:0;background:#fff}}#t{{font:{RENDER_PX}px "c{i}";white-space:pre;'
                            f'padding:40px;display:inline-block;color:#000;font-synthesis:none}}</style>'
                            f'<span id="t">{html.escape(text)}</span>', encoding="utf-8")
            pg.goto(page.as_uri())
            ok = pg.evaluate(f"document.fonts.load('{RENDER_PX}px c{i}').then(f => f.length > 0)")
            if not ok:
                raise SystemExit(f"candidate font failed to load: {f}")
            png = pg.locator("#t").screenshot(animations="disabled")
            out.append(np.asarray(Image.open(io.BytesIO(png)).convert("RGB")))
        renderer = f"{ch} {b.version}"
        b.close()
    return out, renderer


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template")
    ap.add_argument("--region", type=box_arg, required=True)
    ap.add_argument("--text", required=True, help="exact visible text in the region (one line)")
    ap.add_argument("--font", action="append", required=True)
    ap.add_argument("--object")
    ap.add_argument("--source-evidence")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    tdir = template_dir(a.template)
    scene = read_json(tdir / "scene.json")
    img = np.asarray(Image.open(tdir / "source" / "canonical.png").convert("RGB"))
    x, y, w, h = [int(round(v)) for v in a.region]
    ref = tight_mask(img[y:y + h, x:x + w])
    if ref is None:
        raise SystemExit("no ink in region")
    rows = []
    renders, renderer = render_candidates(a.text, a.font)
    for f, rgb in zip(a.font, renders):
        m = tight_mask(rgb, bg=[255, 255, 255])
        cm = scale_mask(m, ref.shape[0])
        rows.append({"file": str(Path(f).resolve()), "sha256": sha256_file(f), "names": font_names(f),
                     "iou": round(iou(ref, cm), 4), "width_error": round((cm.shape[1] - ref.shape[1]) / ref.shape[1], 4),
                     "size_px_by_height": round(RENDER_PX * ref.shape[0] / m.shape[0], 2),
                     "size_px_by_width": round(RENDER_PX * ref.shape[1] / m.shape[1], 2), "_m": cm})
    rows.sort(key=lambda r: -r["iou"])
    best = rows[0]["iou"]
    for r in rows:
        r["indistinguishable_from_best"] = best - r["iou"] < TIE
    ties = [r["names"]["full"] for r in rows if r["indistinguishable_from_best"]]
    # identity: only source evidence can verify
    identity, why, verified = "unknown", "visual similarity ranks candidates; it never proves identity", None
    if a.source_evidence:
        rec = next((r for r in load_evidence(tdir)["records"] if r["evidence_id"] == a.source_evidence), None)
        named = (rec or {}).get("value", {}).get("font_sha256") if rec and rec["method"] == "source_extraction" else None
        match = next((r for r in rows if r["sha256"] == named), None)
        if match and match["indistinguishable_from_best"]:
            identity, verified = "verified", match
            why = f"source evidence {a.source_evidence} names this exact file hash and it matches visually"
        elif match:
            why += f"; CONFLICT: {a.source_evidence} names {match['names']['full']} but it does not match visually (IoU {match['iou']})"
        else:
            why += f"; {a.source_evidence} names no supplied candidate"
    if verified:  # the source-named file leads; visual ties no longer matter
        rows.remove(verified)
        rows.insert(0, verified)
    # contact sheet
    k = max(1, 80 // ref.shape[0]) if ref.shape[0] < 80 else 1
    rh = ref.shape[0] * k
    cw = max(r["_m"].shape[1] for r in rows + [{"_m": ref}]) * k
    sheet = Image.new("RGB", (cw * 3 + 360, (rh + 30) * (len(rows) + 1) + 10), "white")
    d = ImageDraw.Draw(sheet)
    toimg = lambda m: Image.fromarray(((~m) * 255).astype(np.uint8)).resize((m.shape[1] * k, m.shape[0] * k), Image.NEAREST)
    sheet.paste(toimg(ref), (10, 10))
    d.text((cw * 3 + 20, 10), "REFERENCE (tight ink)", fill="black")
    for i, r in enumerate(rows, 1):
        yy = 10 + i * (rh + 30)
        sheet.paste(toimg(r["_m"]), (10, yy))
        ov = np.zeros((max(ref.shape[0], r["_m"].shape[0]), max(ref.shape[1], r["_m"].shape[1]), 3), np.uint8) + 255
        ov[:ref.shape[0], :ref.shape[1]][ref] = [220, 40, 40]
        mm = ov[:r["_m"].shape[0], :r["_m"].shape[1]]
        mm[r["_m"]] = np.where(mm[r["_m"]] == [220, 40, 40], [120, 40, 160], [40, 80, 220])
        sheet.paste(Image.fromarray(ov).resize((ov.shape[1] * k, ov.shape[0] * k), Image.NEAREST), (cw + 20, yy))
        d.text((cw * 3 + 20, yy), f"{r['names']['full']}\nsha {r['sha256'][:12]}\nIoU {r['iou']}  width {r['width_error']:+.1%}"
               + ("\n= TIE with best" if r["indistinguishable_from_best"] else ""), fill="black")
    rel = f"evidence/fonts/candidates-{slugify(a.object or a.text)}.png"
    (tdir / rel).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(tdir / rel)
    ranked = [{k2: v for k2, v in r.items() if k2 != "_m"} for r in rows]
    eid = f"ev-font-{slugify(a.object or a.text)}"
    add_evidence(tdir, [{"evidence_id": eid, "source_sha256": scene["source"]["sha256"], "region": a.region,
                         "object": a.object, "method": "candidate_render_comparison",
                         "tool": f"{TOOL_VERSION} font_candidates.py ({renderer})", "value": {"text": a.text, "ranked": ranked,
                         "identity_status": identity, "ties": ties}, "units": None, "status": "inferred" if identity == "unknown" else "measured",
                         "confidence": "low" if len(ties) > 1 else ("medium" if best >= 0.85 else "low"), "justification": why,
                         "alternatives": [r["names"]["full"] for r in rows[1:]], "artifacts": [rel],
                         "resolving_probe": None if identity == "verified" else "obtain the original font file, source document, or designer confirmation"}])
    if a.apply and a.object:
        n = find_node(scene, a.object)
        top = rows[0]
        rec = import_asset(tdir, top["file"], "font", "system_font" if "Windows" in top["file"] else "supplied")
        scene["assets"][rec["id"]] = rec
        n["font"]["asset"] = rec["id"]
        n["font"]["identity"] = {"status": identity, "candidates": [{"full": r["names"]["full"], "sha256": r["sha256"], "iou": r["iou"]} for r in rows],
                                 "evidence_ids": [eid], "resolving_probe": None if identity == "verified" else "original font file or source document"}
        n.setdefault("provenance", {})["font.asset"] = {"status": "inferred" if identity == "unknown" else "measured",
                                                        "confidence": "low" if len(ties) > 1 else "medium", "evidence_ids": [eid],
                                                        "note": "best-ranked candidate used as approximate render font"}
        write_json(tdir / "scene.json", scene)
    print(json.dumps({"evidence_id": eid, "identity_status": identity, "verified_font": verified["names"]["full"] if verified else None,
                      "basis": why, "ties": ties, "contact_sheet": rel,
                      "ranked": [{"font": r["names"]["full"], "file": r["file"], "iou": r["iou"], "width_error": r["width_error"],
                                  "size_px_by_height": r["size_px_by_height"], "size_px_by_width": r["size_px_by_width"]} for r in ranked]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
