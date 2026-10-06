"""Transactions on template variants: typed ops -> locks/constraints/validation -> render + verify -> commit.

  python apply_patch.py new-variant <tid> --task "Launch this handbag" [--name NAME]
  python apply_patch.py apply <tid> <vid> <patch.json> [--no-verify] [--dry-run]
  python apply_patch.py undo <tid> <vid>
  python apply_patch.py name <tid> <vid> "Everyday Bag - Yellow Variant"
  python apply_patch.py export <tid> <vid> [--formats png,svg]
  python apply_patch.py show <tid> <vid>

Revisions are immutable files; undo moves the head pointer to the parent revision (nothing is deleted).
A rejected transaction is recorded under rejected/ with its conflicts and options.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ID_RE, DnaError, deep, diff_paths, now, read_json, slugify, template_dir,  # noqa: E402
                    write_json)
from compare_render import outside_influence  # noqa: E402
from ops import apply_ops, check_constraints, check_locks, reading_order  # noqa: E402
from render_static import render  # noqa: E402
from validate_model import check_scene, schema_errors  # noqa: E402

IGNORED = ("revision", "base_revision", "variant", "render_profile")


def vdir(tid, vid) -> Path:
    if not ID_RE.match(vid or ""):
        raise DnaError(f"invalid variant id {vid!r}", "bad_id")
    return template_dir(tid) / "variants" / vid


def rev_file(vd: Path, rev: int) -> Path:
    return vd / "revisions" / f"rev-{rev:04d}.json"


def load_variant(tid, vid):
    vd = vdir(tid, vid)
    if not (vd / "variant.json").exists():
        raise DnaError(f"variant {vid} of {tid} does not exist", "unknown_variant")
    meta = read_json(vd / "variant.json")
    return vd, meta, read_json(rev_file(vd, meta["head"]))


def new_variant(tid, task, name=None) -> dict:
    tdir = template_dir(tid)
    base = read_json(tdir / "scene.json")
    passport = read_json(tdir / "passport.json")
    vid, i = slugify(name or task, 40), 2
    while vdir(tid, vid).exists():
        vid, i = f"{slugify(name or task, 40)}-{i}", i + 1
    vd = vdir(tid, vid)
    s0 = deep(base)
    s0["variant"] = {"variant_id": vid, "base_revision": base["revision"], "task": task}
    write_json(rev_file(vd, base["revision"]), s0)
    meta = {"id": vid, "template": tid, "name": name or task, "name_status": "user_supplied" if name else "suggested",
            "task": task, "baseline_revision": base["revision"], "head": base["revision"], "revisions": [base["revision"]],
            "inherited_limitations": {k: passport.get(k) for k in ("readiness", "baseline_match", "unresolved")},
            "history": [{"event": "created", "head": base["revision"], "at": now()}]}
    write_json(vd / "variant.json", meta)
    return meta


def _scene_key(scene) -> str:
    return hashlib.sha256(json.dumps(scene, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def render_cached(tdir, vd, scene, formats=("png",)) -> dict:
    """Renders are cached by scene content hash: a directory is never reused for a different scene."""
    out = vd / "renders" / _scene_key(scene)
    rep = out / "render.report.json"
    if rep.exists() and (set(formats) <= {"png"} or (out / "render.svg").exists()):
        return read_json(rep)
    return render(scene, tdir, out, isolate=True, formats=formats)


def _boxes_for(nodes, rb, ra, pad=1):
    boxes = []
    for nid in nodes:
        for r in (rb, ra):
            b = (r["bounds"].get(nid) or {}).get("rendered")
            if b:
                boxes.append([b[0] - pad, b[1] - pad, b[2] + 2 * pad, b[3] + 2 * pad])
    return boxes


def _intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _probe_requested(base, after, changes, rb, ra):
    """Check requested edits against the actual render, not just the model."""
    import numpy as np
    from PIL import Image

    from compare_render import delta_e

    img_a = np.asarray(Image.open(ra["png"]).convert("RGB"))
    img_b = np.asarray(Image.open(rb["png"]).convert("RGB"))
    out = []
    for c in (c for c in changes if c["kind"] == "requested"):
        p, res = c["path"], {"path": c["path"], "status": "unknown", "probe": "no render probe for this property"}
        nid = p.split(".")[1] if p.startswith("nodes.") else None
        if nid and p.endswith((".geometry.x", ".geometry.y")):
            ax = 0 if p.endswith(".x") else 1
            b0, b1 = (rb["bounds"].get(nid) or {}).get("rendered"), (ra["bounds"].get(nid) or {}).get("rendered")
            if b0 and b1:
                moved = b1[ax] - b0[ax]
                res = {"path": p, "status": "pass" if abs(moved - (c["after"] - c["before"])) <= 0.5 else "fail",
                       "probe": f"rendered bounds moved {moved}px (requested {c['after'] - c['before']})"}
        elif nid and p.endswith(".content"):
            fit = ra["fit"].get(nid, {})
            res = {"path": p, "status": "pass" if fit.get("status") in ("fits", "fitted") else "fail",
                   "probe": f"rendered; fit={fit.get('status')} size={fit.get('size')} lines={fit.get('lines')}"}
        elif nid and p.endswith(".asset"):
            b = (ra["bounds"].get(nid) or {}).get("rendered")
            if b:
                x, y, w, h = b
                changed = int(np.count_nonzero(np.abs(img_a[y:y + h, x:x + w].astype(int) - img_b[y:y + h, x:x + w].astype(int)).max(axis=2)))
                res = {"path": p, "status": "pass" if changed else "fail", "probe": f"{changed} pixels changed in the node region"}
        elif p.startswith("tokens.") and isinstance(c["after"], str) and c["after"].startswith("#"):
            target = [int(c["after"][i:i + 2], 16) for i in (1, 3, 5)]
            bound = [d["path"].split(".")[1] for d in changes if d["kind"] == "dependency" and d["why"] == "bound to the edited token"]
            hits = {}
            for nid2 in bound:
                b = (ra["bounds"].get(nid2) or {}).get("rendered")
                if b:
                    x, y, w, h = b
                    reg = img_a[y:y + h, x:x + w].reshape(-1, 3)
                    med = np.median(reg[np.abs(reg.astype(int) - target).max(axis=1) <= 6], axis=0) if len(reg) else None
                    hits[nid2] = bool(med is not None and not np.isnan(med).any() and delta_e(med, target) <= 1)
            res = {"path": p, "status": "pass" if hits and all(hits.values()) else ("unknown" if not hits else "fail"),
                   "probe": f"new color found in bound nodes: {hits}"}
        out.append(res)
    return out


def verify_change(tdir, vd, base, after, changes, mode) -> dict:
    rb, ra = render_cached(tdir, vd, base), render_cached(tdir, vd, after)
    authorized = {c["path"] for c in changes}
    actual = [p for p in diff_paths(base, after) if p.split(".")[0] not in IGNORED]
    unexplained = [p for p in actual if not any(p == a or p.startswith(a + ".") or a.startswith(p + ".") for a in authorized)]
    v = {"property_check": {"status": "fail" if unexplained else "pass", "changed_paths": actual, "unexplained": unexplained},
         "requested_edits": _probe_requested(base, after, changes, rb, ra),
         "renders": {"base": rb["png"], "variant": ra["png"]}}
    if mode == "reflow":
        W, H = after["canvas"]["width"], after["canvas"]["height"]
        outside = [n for n, b in ra["bounds"].items() if b["rendered"] and (b["rendered"][0] < 0 or b["rendered"][1] < 0
                   or b["rendered"][0] + b["rendered"][2] > W or b["rendered"][1] + b["rendered"][3] > H)]
        ro_b, ro_a = reading_order(base), reading_order(after)
        nodes_ = [n for n in after["nodes"] if n["type"] not in ("background", "group")]
        new_overlaps = []
        for i, n1 in enumerate(nodes_):
            for n2 in nodes_[i + 1:]:
                b1, b2 = (ra["bounds"].get(n1["id"]) or {}).get("rendered"), (ra["bounds"].get(n2["id"]) or {}).get("rendered")
                o1, o2 = (rb["bounds"].get(n1["id"]) or {}).get("rendered"), (rb["bounds"].get(n2["id"]) or {}).get("rendered")
                if b1 and b2 and o1 and o2 and _intersects(b1, b2) and not _intersects(o1, o2):
                    new_overlaps.append([n1["id"], n2["id"]])
        v["reflow_preserve"] = {"target_dims": [W, H], "outside_canvas": outside, "reading_order_preserved": ro_b == ro_a,
                                "reading_order": ro_a, "new_overlaps": new_overlaps,
                                "text_fit": {k: x["status"] for k, x in ra["fit"].items()},
                                "status": "pass" if not outside and ro_b == ro_a and not new_overlaps else "fail",
                                "note": "whole-image pixel comparison across aspect ratios is not an identity test"}
        checks = [v["property_check"]["status"], v["reflow_preserve"]["status"]]
    else:
        affected = sorted({c["path"].split(".")[1] for c in changes if c["path"].startswith("nodes.")})
        W, H = after["canvas"]["width"], after["canvas"]["height"]
        boxes = _boxes_for(affected, rb, ra)
        whole = any(n["type"] == "background" for n in base["nodes"] if n["id"] in affected)
        v["expected_influence"] = {"nodes": affected, "boxes": boxes, "declared_before_pixel_check": True,
                                   "whole_canvas": whole}
        if whole:
            v["pixel_preservation"] = {"status": "not_applicable", "note": "whole-canvas influence; relying on property/invariant checks"}
        else:
            pix = outside_influence(rb["png"], ra["png"], boxes, W, H)
            consequences = []
            for n in after["nodes"]:
                b = (ra["bounds"].get(n["id"]) or {}).get("rendered")
                if n["id"] not in affected and b and n["type"] != "background" and any(_intersects(b, x) for x in boxes) \
                        and (n.get("opacity", 1) < 1 or n.get("blend", "normal") != "normal"):
                    consequences.append({"node": n["id"], "why": "translucent/blended node over a changed region: its visible "
                                                                 "pixels change although its properties do not"})
            pix["compositing_consequences"] = consequences
            v["pixel_preservation"] = pix
        checks = [v["property_check"]["status"], v["pixel_preservation"]["status"]]
    checks += [r["status"] for r in v["requested_edits"]]
    v["status"] = "fail" if "fail" in checks else ("pass_with_unknowns" if "unknown" in checks else "pass")
    return v


def transact(tid, vid, patch, verify=True, dry_run=False) -> dict:
    errs = schema_errors(patch, "patch.schema.json")
    if errs:
        raise DnaError("patch does not match patch.schema.json", "invalid_patch", {"errors": errs})
    tdir = template_dir(tid)
    vd, meta, base = load_variant(tid, vid)
    if patch["base_revision"] != base["revision"]:
        raise DnaError(f"patch targets revision {patch['base_revision']} but the head is {base['revision']}",
                       "stale_base", {"head": base["revision"]})
    mode = "reflow" if any(o["op"] == "reflow" for o in patch["ops"]) else "adapt"
    nxt = max(meta["revisions"]) + 1
    txn = {"template": tid, "variant": vid, "base_revision": base["revision"], "revision": nxt,
           "intent": patch.get("intent"), "ops": patch["ops"], "created": now()}
    try:
        after, changes = apply_ops(base, patch["ops"], tdir)
        for aid in set(after["assets"]) - set(base["assets"]):
            changes.append({"path": f"assets.{aid}", "before": None, "after": after["assets"][aid]["sha256"],
                            "kind": "dependency", "why": "imported asset (content-hashed)", "op_index": None})
        lock_conf, overrides = check_locks(after, [c for c in changes if not c["path"].startswith(("locks.", "assets."))])
        con_conf, con_notes = check_constraints(base, after, mode, patch.get("relax", []))
        val = check_scene(after, tdir)
        txn.update(changes=changes, soft_lock_overrides=overrides, constraint_notes=con_notes,
                   validation={k: val[k] for k in ("errors", "warnings", "unsupported", "missing_assets", "editability")},
                   conflicts=lock_conf + con_conf + [{"validation": e} for e in val["errors"]])
        if not txn["conflicts"] and verify:
            after["revision"], after["base_revision"] = nxt, base["revision"]
            txn["verification"] = verify_change(tdir, vd, base, after, changes, mode)
            if txn["verification"]["status"] == "fail":
                txn["conflicts"].append({"verification": "failed", "detail": "see verification"})
    except DnaError as e:
        txn["conflicts"] = [e.as_dict()]
    if txn["conflicts"]:
        txn["status"] = "rejected"
        write_json(vd / "rejected" / f"txn-{now().replace(':', '')}.json", txn)
        raise DnaError("transaction rejected; the head is unchanged", "conflict", txn)
    txn["status"] = "dry_run" if dry_run else "committed"
    if not verify:
        txn["verification"] = {"status": "not_run"}
    if dry_run:
        return txn
    after["revision"], after["base_revision"] = nxt, base["revision"]
    write_json(rev_file(vd, nxt), after)
    write_json(vd / "transactions" / f"txn-{nxt:04d}.json", txn)
    meta["revisions"].append(nxt)
    meta["head"] = nxt
    meta["history"].append({"event": "commit", "head": nxt, "intent": patch.get("intent"), "at": now()})
    write_json(vd / "variant.json", meta)
    return txn


def undo(tid, vid) -> dict:
    vd, meta, head = load_variant(tid, vid)
    parent = head.get("base_revision")
    if head["revision"] == meta["baseline_revision"] or parent is None:
        raise DnaError("nothing to undo: the head is the variant's baseline", "nothing_to_undo")
    meta["history"].append({"event": "undo", "from": head["revision"], "head": parent, "at": now()})
    meta["head"] = parent
    write_json(vd / "variant.json", meta)
    return {"head": parent, "restored_file": str(rev_file(vd, parent)),
            "restored_sha256": hashlib.sha256(rev_file(vd, parent).read_bytes()).hexdigest()}


def export(tid, vid, formats=("png", "svg")) -> dict:
    tdir = template_dir(tid)
    vd, meta, scene = load_variant(tid, vid)
    out = vd / "exports" / f"rev-{scene['revision']:04d}"
    r = render(scene, tdir, out, formats=formats, name=slugify(meta["name"], 40))
    write_json(out / "scene.json", scene)
    return {"dir": str(out), "png": r["png"], "svg": r.get("svg"), "notes": r.get("export_notes", [])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new-variant"); s.add_argument("template"); s.add_argument("--task", required=True); s.add_argument("--name")
    s = sub.add_parser("apply"); s.add_argument("template"); s.add_argument("variant"); s.add_argument("patch")
    s.add_argument("--no-verify", action="store_true"); s.add_argument("--dry-run", action="store_true")
    for c in ("undo", "show"):
        s = sub.add_parser(c); s.add_argument("template"); s.add_argument("variant")
    s = sub.add_parser("name"); s.add_argument("template"); s.add_argument("variant"); s.add_argument("name")
    s = sub.add_parser("export"); s.add_argument("template"); s.add_argument("variant"); s.add_argument("--formats", default="png,svg")
    a = ap.parse_args()
    try:
        if a.cmd == "new-variant":
            r = new_variant(a.template, a.task, a.name)
        elif a.cmd == "apply":
            r = transact(a.template, a.variant, read_json(a.patch), not a.no_verify, a.dry_run)
        elif a.cmd == "undo":
            r = undo(a.template, a.variant)
        elif a.cmd == "name":
            vd, meta, _ = load_variant(a.template, a.variant)
            meta.update(name=a.name, name_status="user_supplied")
            write_json(vd / "variant.json", meta)
            r = meta
        elif a.cmd == "export":
            r = export(a.template, a.variant, a.formats.split(","))
        else:
            r = load_variant(a.template, a.variant)[1]
    except DnaError as e:
        print(json.dumps(e.as_dict(), indent=2, ensure_ascii=False, default=str))
        return 2
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
