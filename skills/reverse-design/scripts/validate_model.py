"""Validate a Design DNA scene: JSON Schema, semantics, assets, capability support, editability.

Usage: python validate_model.py <template-id> [--scene path] [--json]
Exit 0 = valid, 1 = errors. Unsupported features and missing assets are reported explicitly;
they are never silently dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (SCAN_CATEGORIES, SCHEMA_DIR, DnaError, font_cmap, load_evidence, node_map,  # noqa: E402
                    read_json, safe_path, sha256_file, template_dir)

SUPPORTED = {
    "treatment": {"grayscale", "saturate", "contrast", "brightness", "hue_rotate", "tint", "blur"},
    "effect": {"drop_shadow", "layer_blur"},
    "effect_node": {"grain", "vignette"},
    "stroke_align": {"center"},
}
ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
SHORTCUT_COVERAGE = 0.5  # a reference-derived raster covering >= half the canvas cannot back an editable claim


def schema_errors(instance, schema_name: str) -> list[str]:
    import jsonschema

    v = jsonschema.Draft202012Validator(read_json(SCHEMA_DIR / schema_name))
    errs = sorted(v.iter_errors(instance), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:300]}" for e in errs]


def _walk_refs(obj, key):
    """Yield every value stored under `key` anywhere in a JSON tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk_refs(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_refs(v, key)


def resolved_font(scene, node) -> dict:
    f = dict(node.get("font") or {})
    if "token" in f:
        base = dict(scene["tokens"].get(f["token"], {}).get("value") or {})
        base.update({k: v for k, v in f.items() if k != "token"})
        f = base
    return f


def editability_report(scene) -> dict:
    W, H = scene["canvas"]["width"], scene["canvas"]["height"]
    src = scene["source"]["sha256"]
    assets, nodes = scene["assets"], node_map(scene)
    shortcut = []
    for n in scene["nodes"]:
        a = assets.get(n.get("asset") or "")
        if not a or n["type"] not in ("image", "background"):
            continue
        g = n["geometry"]
        cov = max(0, min(g["x"] + g["w"], W) - max(g["x"], 0)) * max(0, min(g["y"] + g["h"], H) - max(g["y"], 0)) / (W * H)
        from_ref = a["sha256"] == src or a.get("derived_from", {}).get("sha256") == src or a["source"] == "reference_crop"
        if from_ref and cov >= SHORTCUT_COVERAGE:
            shortcut.append({"node": n["id"], "coverage": round(cov, 3)})
    slots = {}
    for s in scene["slots"]:
        n = nodes.get(s["node"])
        if n is None:
            slots[s["id"]] = "fail: slot node missing"
        elif shortcut and n["id"] not in {x["node"] for x in shortcut}:
            slots[s["id"]] = "fail: old pixels remain baked into reference background " + shortcut[0]["node"]
        elif s["type"] == "text":
            slots[s["id"]] = "live" if n["type"] == "text" and n.get("editability", "live") == "live" else \
                f"{n.get('editability', 'unknown')}: not live text"
        elif s["type"] in ("image", "logo"):
            if any(x["node"] == n["id"] for x in shortcut):
                slots[s["id"]] = "fail: slot is the reference bitmap"
            else:
                slots[s["id"]] = "replaceable_raster" if n["type"] in ("image", "background") else "live_vector"
        else:
            slots[s["id"]] = "live"
    bad = [k for k, v in slots.items() if v.startswith("fail") or "not live" in v]
    overall = "fail" if shortcut else ("pass" if not bad else "partial")
    return {"overall": overall, "slots": slots, "reference_background_shortcut": shortcut,
            "rule": f"reference-derived raster covering >= {SHORTCUT_COVERAGE:.0%} of canvas fails editability"}


def check_scene(scene, tdir, verify_hashes: bool = True) -> dict:
    errors, warnings, unsupported, missing = [], [], [], []
    errors += schema_errors(scene, "scene.schema.json")
    if errors:
        return {"valid": False, "errors": errors, "warnings": [], "unsupported": [], "missing_assets": [], "editability": None}
    nodes = node_map(scene)
    ids = [n["id"] for n in scene["nodes"]]
    errors += [f"duplicate node id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    aliases = [n["alias"] for n in scene["nodes"] if n.get("alias")]
    errors += [f"duplicate alias {a}" for a in sorted({a for a in aliases if aliases.count(a) > 1})]
    for n in scene["nodes"]:
        p = n.get("parent")
        if p and (p not in nodes or nodes[p]["type"] != "group" or n["id"] not in nodes[p].get("children", [])):
            errors.append(f"{n['id']}: parent {p} missing, not a group, or does not list it as a child")
        for c in n.get("children", []):
            if c not in nodes or nodes[c].get("parent") != n["id"]:
                errors.append(f"{n['id']}: child {c} missing or has a different parent")
    for key in _walk_refs(scene["nodes"], "token"):
        if key not in scene["tokens"]:
            errors.append(f"unknown token reference {key!r}")
    # assets: presence + content hash (missing-asset check)
    for aid, a in scene["assets"].items():
        if aid != a["id"]:
            errors.append(f"asset key {aid} != asset id {a['id']}")
        try:
            f = safe_path(tdir, a["path"])
        except DnaError as e:
            errors.append(str(e))
            continue
        if not f.exists():
            missing.append({"asset": aid, "path": a["path"], "status": "missing"})
        elif verify_hashes and sha256_file(f) != a["sha256"]:
            missing.append({"asset": aid, "path": a["path"], "status": "hash_mismatch"})
    for n in scene["nodes"]:
        refs = [n.get("asset"), (n.get("mask") or {}).get("asset"), resolved_font(scene, n).get("asset") if n["type"] == "text" else None]
        for r in filter(None, refs):
            if r not in scene["assets"]:
                missing.append({"asset": r, "node": n["id"], "status": "unknown_asset_id"})
    errors += [f"asset {m['asset']}: {m['status']}" for m in missing]
    # evidence references must resolve
    known = {r["evidence_id"] for r in load_evidence(tdir)["records"]}
    for ev_list in _walk_refs({k: v for k, v in scene.items() if k != "assets"}, "evidence_ids"):
        for e in ev_list or []:
            if e not in known:
                errors.append(f"evidence id {e} is referenced but not in evidence/evidence.json")
    # capability support (explicit unsupported, never ignored)
    for n in scene["nodes"]:
        for t in n.get("treatment", []):
            if t["op"] not in SUPPORTED["treatment"]:
                unsupported.append({"node": n["id"], "feature": f"treatment:{t['op']}"})
        for fx in n.get("effects", []):
            if fx["type"] not in SUPPORTED["effect"]:
                unsupported.append({"node": n["id"], "feature": f"effect:{fx['type']}"})
        if n["type"] == "effect" and n["effect"]["kind"] not in SUPPORTED["effect_node"]:
            unsupported.append({"node": n["id"], "feature": f"effect_node:{n['effect']['kind']}"})
        if (n.get("stroke") or {}).get("align", "center") not in SUPPORTED["stroke_align"]:
            unsupported.append({"node": n["id"], "feature": f"stroke_align:{n['stroke']['align']}"})
        if (n.get("mask") or {}).get("type") == "asset" and (n.get("mask") or {}).get("feather"):
            unsupported.append({"node": n["id"], "feature": "mask:asset+feather"})
    errors += [f"unsupported {u['feature']} on {u['node']}" for u in unsupported]
    # typography
    for n in scene["nodes"]:
        if n["type"] != "text":
            continue
        f = resolved_font(scene, n)
        for k in ("size",):
            if k not in f:
                errors.append(f"{n['id']}: font.{k} missing after token resolution")
        text = n["content"].replace("\n", "")
        if f.get("asset") in scene["assets"] and not any(m.get("asset") == f["asset"] for m in missing):
            cmap = font_cmap(safe_path(tdir, scene["assets"][f["asset"]]["path"]))
            gaps = sorted({c for c in text if ord(c) not in cmap and not c.isspace()})
            if gaps:
                errors.append(f"{n['id']}: font lacks glyphs {gaps!r}; browser fallback would be silent")
        elif not f.get("asset"):
            warnings.append(f"{n['id']}: font not pinned to a file ({f.get('family')!r}); glyph coverage and determinism unknown")
        if ARABIC.search(text):
            if n.get("tracking", 0):
                errors.append(f"{n['id']}: tracking {n['tracking']}px on Arabic text breaks joining")
            if n.get("direction") != "rtl":
                warnings.append(f"{n['id']}: Arabic content with direction {n.get('direction', 'ltr')!r}")
        if (f.get("identity") or {}).get("status", "unknown") == "unknown":
            warnings.append(f"{n['id']}: font identity unknown (rendering a candidate)")
    # scan coverage
    cov = scene["scan"]["coverage"]
    absent = [c for c in SCAN_CATEGORIES if c not in cov]
    if absent:
        (errors if scene["scan"]["state"] == "complete" else warnings).append(f"scan categories without a result: {absent}")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "unsupported": unsupported,
            "missing_assets": missing, "editability": editability_report(scene)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("template")
    ap.add_argument("--scene", help="scene file (default: template scene.json)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tdir = template_dir(a.template)
    scene = read_json(a.scene or tdir / "scene.json")
    rep = check_scene(scene, tdir)
    for extra, schema in (("passport.json", "template.schema.json"), ("evidence/evidence.json", "evidence.schema.json")):
        if (tdir / extra).exists():
            errs = schema_errors(read_json(tdir / extra), schema)
            rep["errors"] += [f"{extra}: {e}" for e in errs]
            rep["valid"] = rep["valid"] and not errs
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print("VALID" if rep["valid"] else "INVALID")
        for k in ("errors", "warnings"):
            for m in rep[k]:
                print(f"  {k[:-1]}: {m}")
        if rep["editability"]:
            print(f"  editability: {rep['editability']['overall']}")
    return 0 if rep["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
