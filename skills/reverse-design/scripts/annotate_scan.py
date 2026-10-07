"""Annotated scan + coverage report for a template.

  python annotate_scan.py <tid>

Writes evidence/annotated.png (node bounds + ids, `?` on inferred/unknown/low-confidence nodes, `?f` on unknown
font identity, palette strip) and evidence/scan_report.md (coverage table, inventory, tokens, fonts, communication,
unresolved items). Inferred parameters are labelled as such; nothing here upgrades a hypothesis to a measurement.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SCAN_CATEGORIES, load_evidence, read_json, template_dir  # noqa: E402
from validate_model import resolved_font  # noqa: E402

COLORS = {"text": "#E0007A", "image": "#0077FF", "shape": "#00A86B", "path": "#00A86B", "group": "#888888",
          "effect": "#AA6600", "background": "#444444"}


def uncertain(n) -> bool:
    return any(p["status"] in ("inferred", "unknown") or p["confidence"] == "low" for p in (n.get("provenance") or {}).values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("template")
    a = ap.parse_args()
    tdir = template_dir(a.template)
    scene, passport = read_json(tdir / "scene.json"), read_json(tdir / "passport.json")
    base = Image.open(tdir / "source" / "canonical.png").convert("RGB")
    W, H = base.size
    colors = [(k, t) for k, t in scene["tokens"].items() if t["type"] == "color" and isinstance(t["value"], str)]
    out = Image.new("RGB", (W, H + 140), "white")
    out.paste(Image.blend(base, Image.new("RGB", base.size, "white"), 0.35), (0, 0))
    d = ImageDraw.Draw(out)
    for n in scene["nodes"]:
        if n["type"] == "background":
            continue
        g = n["geometry"]
        c = COLORS.get(n["type"], "#000000")
        d.rectangle([g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]], outline=c, width=2)
        if n["type"] == "text" and n.get("first_baseline") is not None:  # mid-scan text may not be measured yet
            d.line([g["x"], n["first_baseline"], g["x"] + g["w"], n["first_baseline"]], fill=c, width=1)
        tag = n.get("alias") or n["id"]
        if uncertain(n):
            tag += " ?"
        if n["type"] == "text" and (resolved_font(scene, n).get("identity") or {}).get("status", "unknown") != "verified":
            tag += " ?f"
        tw = d.textlength(tag)
        d.rectangle([g["x"], g["y"] - 14, g["x"] + tw + 6, g["y"]], fill=c)
        d.text((g["x"] + 3, g["y"] - 13), tag, fill="white")
    for i, (k, t) in enumerate(colors):
        x = 10 + i * 150
        d.rectangle([x, H + 12, x + 40, H + 52], fill=t["value"][:7], outline="#777777")
        d.text((x + 46, H + 12), f"{k}\n{t['value']}\n{t['status']}/{t['confidence']}", fill="black")
    d.text((10, H + 70), "boxes: magenta=text (line=baseline) blue=image green=shape/path   ? = inferred/unknown/low   "
                         "?f = font identity unknown", fill="black")
    (tdir / "evidence").mkdir(exist_ok=True)
    out.save(tdir / "evidence" / "annotated.png")

    ev = {r["evidence_id"]: r for r in load_evidence(tdir)["records"]}
    cov = scene["scan"]["coverage"]
    L = [f"# Scan report — {passport['name']} (`{scene['template_id']}` rev {scene['revision']})", "",
         f"Readiness: **{passport['readiness']}** · baseline match: {passport['baseline_match']['profile']} / "
         f"{passport['baseline_match']['status']} · canvas {scene['canvas']['width']}x{scene['canvas']['height']}", "",
         "![annotated](annotated.png)", "", "## Coverage", "", "| Category | Status | Note |", "|---|---|---|"]
    for c in SCAN_CATEGORIES:
        e = cov.get(c)
        amb = "; ".join((e or {}).get("ambiguity", []))
        L.append(f"| {c} | {e['status'] if e else '**MISSING**'} | {(e or {}).get('note', '').replace('|', '/')}"
                 + (f" — *unresolved: {amb}*" if amb else "") + " |")
    L += ["", "## Facets (measurement vs hypothesis kept apart)", "",
          "| facet | status | confidence | finding | evidence | unresolved |", "|---|---|---|---|---|---|"]
    for c in SCAN_CATEGORIES:
        for k, f in ((cov.get(c) or {}).get("facets") or {}).items():
            L.append(f"| {c}.{k} | {f['status']} | {f.get('confidence', '')} | {f.get('note', '').replace('|', '/')} | "
                     f"{', '.join(f.get('evidence_ids', []))} | {'; '.join(f.get('ambiguity', []))} |")
    L += ["", "## Elements", "", "| id | alias | type | role | x,y,w,h | editability | uncertain |", "|---|---|---|---|---|---|---|"]
    for n in scene["nodes"]:
        g = n["geometry"]
        L.append(f"| {n['id']} | {n.get('alias', '')} | {n['type']} | {n['role']} | "
                 f"{g['x']:.0f},{g['y']:.0f},{g['w']:.0f},{g['h']:.0f} | {n.get('editability', 'live')} | {'yes' if uncertain(n) else ''} |")
    L += ["", "## Tokens", "", "| role | value | status | confidence | evidence |", "|---|---|---|---|---|"]
    for k, t in scene["tokens"].items():
        L.append(f"| {k} | `{t['value'] if not isinstance(t['value'], dict) else 'structured'}` | {t['status']} | {t['confidence']} | {', '.join(t.get('evidence_ids', []))} |")
    L += ["", "## Typography candidates", ""]
    for r in ev.values():
        if r["method"] == "candidate_render_comparison" and "ranked" in (r["value"] or {}):
            v = r["value"]
            L.append(f"- `{r['object']}` \"{v['text']}\": identity **{v['identity_status']}**; ties: {v['ties']}; "
                     f"sheet: {', '.join(r.get('artifacts', []))}")
            L += [f"  - {x['names']['full']} — IoU {x['iou']}, width {x['width_error']:+.1%}" for x in v["ranked"][:5]]
    fits = [r for r in ev.values() if r["method"] == "candidate_render_comparison" and "params" in (r["value"] or {})]
    if fits:
        L += ["", "Render fits (conditional on the candidate font):", ""]
        L += [f"- `{r['object']}`: {r['value']['params']} · MAE {r['value']['mae_start']:.2f} → {r['value']['mae_end']:.2f} · "
              f"{', '.join(r.get('artifacts', []))}" for r in fits]
    com = scene["communication"]
    L += ["", "## Communication (interpretation, not measurement)", ""]
    for k in ("goal", "literal_message", "takeaway", "cta", "word_image_relationship"):
        if k in com:
            L.append(f"- **{k}** [{com[k]['status']}/{com[k]['confidence']}]: {com[k]['value']}")
    for m in com["mechanisms"]:
        L.append(f"- chain [{m['status']}/{m['confidence']}]: " + " → ".join(m["chain"])
                 + (f" · competing: {'; '.join(m.get('competing', []))}" if m.get("competing") else ""))
    L += ["", "## Unresolved", ""] + [f"- {u}" for u in passport["unresolved"]]
    (tdir / "evidence" / "scan_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{tdir / 'evidence' / 'annotated.png'}\n{tdir / 'evidence' / 'scan_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
