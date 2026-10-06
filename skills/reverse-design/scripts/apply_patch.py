"""Transactions on template variants: typed ops -> locks/constraints/validation -> render + verify -> commit.

  python apply_patch.py new-variant <tid> --task "Launch this handbag" [--name NAME]
  python apply_patch.py apply <tid> <vid> <patch.json> [--no-verify] [--dry-run]
  python apply_patch.py undo <tid> <vid>
  python apply_patch.py name <tid> <vid> "Everyday Bag - Yellow Variant"
  python apply_patch.py export <tid> <vid> [--formats png,svg]
  python apply_patch.py show <tid> <vid>

Revisions are immutable files; undo moves the head pointer to the parent revision (nothing is deleted).
A rejected transaction is recorded under rejected/ with its conflicts and options.
A patch with "keep": "everything_else" authorises exactly the requested paths + their declared dependencies and
freezes every other property path for that transaction (explicit locks still apply and still conflict).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ID_RE, DnaError, deep, now, read_json, slugify, template_dir, write_json  # noqa: E402
from ops import apply_ops, check_constraints, check_locks  # noqa: E402
from render_static import render  # noqa: E402
from validate_model import check_scene, schema_errors  # noqa: E402
from verify_change import verify_change  # noqa: E402


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


def _origin(vd, meta, base):
    """The variant's starting model and every committed change since then (for the approved-baseline check)."""
    if base["revision"] == meta["baseline_revision"]:
        return None, []
    history, rev = [], base
    while rev["revision"] != meta["baseline_revision"]:
        history = read_json(vd / "transactions" / f"txn-{rev['revision']:04d}.json")["changes"] + history
        rev = read_json(rev_file(vd, rev["base_revision"]))
    return rev, history


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
    scope = patch.get("keep")
    txn = {"template": tid, "variant": vid, "base_revision": base["revision"], "revision": nxt,
           "intent": patch.get("intent"), "ops": patch["ops"], "scope": {"keep": scope} if scope else None, "created": now()}
    try:
        after, changes = apply_ops(base, patch["ops"], tdir)
        for aid in set(after["assets"]) - set(base["assets"]):
            changes.append({"path": f"assets.{aid}", "before": None, "after": after["assets"][aid]["sha256"],
                            "kind": "dependency", "why": "imported asset (content-hashed)", "op_index": None})
        # authorised set is fixed BEFORE anything is checked: requested paths + declared dependencies
        txn["authorized_paths"] = sorted({c["path"] for c in changes})
        lock_conf, overrides = check_locks(base, after, changes)
        requested_nodes = {c["path"].split(".")[1] for c in changes if c["kind"] == "requested" and c["path"].startswith("nodes.")}
        con_conf, con_notes = check_constraints(base, after, mode, patch.get("relax", []), requested_nodes)
        val = check_scene(after, tdir)
        txn.update(changes=changes, soft_lock_overrides=overrides, constraint_notes=con_notes,
                   validation={k: val[k] for k in ("errors", "warnings", "unsupported", "missing_assets", "editability")},
                   conflicts=lock_conf + con_conf + [{"validation": e} for e in val["errors"]])
        if not txn["conflicts"] and verify:
            after["revision"], after["base_revision"] = nxt, base["revision"]
            origin, history = _origin(vd, meta, base)
            txn["verification"] = verify_change(tdir, vd, base, after, changes, mode, scope, origin, history + changes)
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


def export(tid, vid, formats=("png", "svg"), svg_fonts="embed") -> dict:
    tdir = template_dir(tid)
    vd, meta, scene = load_variant(tid, vid)
    out = vd / "exports" / f"rev-{scene['revision']:04d}"
    if out.exists():
        import datetime as _dt

        out = out.with_name(f"{out.name}-{_dt.datetime.now():%Y%m%d-%H%M%S}")
    r = render(scene, tdir, out, formats=formats, name=slugify(meta["name"], 40), svg_fonts=svg_fonts)
    write_json(out / "scene.json", scene)
    return {"dir": str(out), "png": r["png"], "svg": r.get("svg"), "svg_manifest": r.get("svg_manifest"),
            "svg_verification": r.get("svg_verification"), "pin_check": r["pin_check"]}


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
