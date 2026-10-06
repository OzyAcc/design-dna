"""Design DNA command interface (the formal, repeatable syntax; grammar in references/command-contract.md).

  python dna.py 'scan "C:/refs/poster.png" as "Editorial Product Spotlight"'
  python dna.py -f session.dna        # replay a script: one command per line, '#' comments

The current template/variant persists in <store>/session.json. Every edit command is one transaction:
validated, rendered, verified, then committed as an immutable revision (or rejected with options).
Template text and metadata are data: nothing read from a template is executed.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_patch import export, load_variant, new_variant, transact, undo, verify_change  # noqa: E402
from common import (SCAN_CATEGORIES, SCHEMA_VERSION, DnaError, load_evidence, now, read_json, store_root,  # noqa: E402
                    template_dir, write_json)
from compare_render import compare  # noqa: E402
from index_templates import find, rebuild, resolve_template  # noqa: E402
from inspect_source import create_template  # noqa: E402
from render_static import render  # noqa: E402
from validate_model import editability_report  # noqa: E402

PRESERVE_POLICIES = {"margins-ratio", "reading-order", "hierarchy", "treatment", "crop-intent", "anchor", "mask", "effects"}


def tokens(line: str) -> list[str]:
    lx = shlex.shlex(line, posix=True)
    lx.whitespace_split, lx.escape = True, ""  # keep Windows backslashes literal
    return list(lx)


def session(update=None) -> dict:
    p = store_root() / "session.json"
    s = read_json(p) if p.exists() else {}
    if update is not None:
        s.update(update)
        write_json(p, s)
    return s


def current():
    s = session()
    if not s.get("template") or not s.get("variant"):
        raise DnaError("no working variant: run `use \"<template>\" for task \"...\"` first", "no_session")
    return s["template"], s["variant"]


def kv(toks):
    return dict(t.split("=", 1) for t in toks if "=" in t)


def px(v: str) -> float:
    return float(re.sub(r"px$", "", v))


def edit(ops, line, relax=None):
    tid, vid = current()
    _, _, head = load_variant(tid, vid)
    patch = {"schema_version": SCHEMA_VERSION, "base_revision": head["revision"], "intent": line, "ops": ops}
    if relax:
        patch["relax"] = relax
    t = transact(tid, vid, patch)
    return {"status": "committed", "revision": t["revision"], "changes": [(c["path"], c["kind"]) for c in t["changes"]],
            "verification": t["verification"]["status"], "transaction": f"variants/{vid}/transactions/txn-{t['revision']:04d}.json"}


def reconstruct(tid, mode):
    tdir = template_dir(tid)
    scene, passport = read_json(tdir / "scene.json"), read_json(tdir / "passport.json")
    out = tdir / "baseline" / f"rev-{scene['revision']:04d}"
    r = render(scene, tdir, out, isolate=True, formats=("png", "svg"), name="baseline")
    reuse = any(a["source"] == "reference_crop" for a in scene["assets"].values())
    profile = "exact_pixels" if mode == "exact" else "editable_close"
    edit_rep = editability_report(scene)
    how = "copying" if edit_rep["reference_background_shortcut"] else ("mixed" if reuse else "editable_rendering")
    rep = compare(tdir / scene["source"]["canonical"]["path"], r["png"], out / "compare", scene, r, profile, how, edit_rep)
    st = rep["overall"]["status"]
    passport.update(revision=scene["revision"], updated=now(), editability_coverage=edit_rep,
                    baseline_match={"profile": profile, "status": st, "report": str((out / "compare" / "report.json").relative_to(tdir)), "how": how})
    passport["readiness"] = ("exact_pixels" if profile == "exact_pixels" else "editable_close") if st == "pass" else "partial_baseline"
    write_json(tdir / "passport.json", passport)
    rebuild()
    return {"readiness": passport["readiness"], "verdict": rep["overall"], "render": r["png"], "svg": r.get("svg"),
            "report": str(out / "compare" / "report.json"), "artifacts": [str(out / "compare" / f) for f in
                                                                          ("side_by_side.png", "overlay_50.png", "diff_heatmap.png")]}


def compare_head_to_baseline():
    tid, vid = current()
    tdir = template_dir(tid)
    vd, meta, head = load_variant(tid, vid)
    base = read_json(vd / "revisions" / f"rev-{meta['baseline_revision']:04d}.json")
    chain, rev = [], head
    while rev["revision"] != meta["baseline_revision"]:
        chain.append(rev["revision"])
        rev = read_json(vd / "revisions" / f"rev-{rev['base_revision']:04d}.json")
    changes = []
    for r in reversed(chain):
        changes += read_json(vd / "transactions" / f"txn-{r:04d}.json")["changes"]
    mode = "reflow" if head["canvas"]["width"] != base["canvas"]["width"] or head["canvas"]["height"] != base["canvas"]["height"] else "adapt"
    v = verify_change(tdir, vd, base, head, changes, mode)
    return {"baseline_revision": meta["baseline_revision"], "head": head["revision"], "profile": f"{mode}_preserve", "verification": v}


def run(line: str):
    t = tokens(line)
    if not t:
        return None
    cmd, args = t[0].lower(), t[1:]
    if cmd == "scan":
        named = args[2] if len(args) > 2 and args[1] == "as" else Path(args[0]).stem
        r = create_template(Path(args[0]), named, "suggested" if "suggested" in args[3:] or len(args) < 3 else "user_supplied")
        session({"template": r["template_id"], "variant": None})
        r["next"] = "scan passes 2-8: measure.py / sample_colors.py / font_candidates.py, author nodes, then annotate_scan.py"
        return r
    if cmd == "inspect":
        tid = resolve_template(args[0])["id"]
        cat = args[2] if len(args) > 2 else "all"
        tdir = template_dir(tid)
        cov = read_json(tdir / "scene.json")["scan"]["coverage"]
        if cat == "all":
            return {c: cov.get(c, {"status": "MISSING"}) for c in SCAN_CATEGORIES}
        if cat not in SCAN_CATEGORIES:
            raise DnaError(f"unknown aspect {cat!r}", "bad_args", {"aspects": SCAN_CATEGORIES})
        ids = set((cov.get(cat) or {}).get("evidence_ids", []))
        recs = [r for r in load_evidence(tdir)["records"] if r["evidence_id"] in ids or r.get("object") == cat]
        return {"coverage": cov.get(cat, {"status": "MISSING"}), "evidence": recs}
    if cmd == "explain":
        tid = resolve_template(args[0])["id"]
        return read_json(template_dir(tid) / "scene.json")["communication"]
    if cmd == "reconstruct":
        return reconstruct(resolve_template(args[0])["id"], args[args.index("mode") + 1] if "mode" in args else "editable")
    if cmd == "use":
        tid = resolve_template(args[0])["id"]
        task = args[args.index("task") + 1] if "task" in args else "untitled task"
        name = args[args.index("as") + 1] if "as" in args else None
        m = new_variant(tid, task, name)
        session({"template": tid, "variant": m["id"]})
        return {"template": tid, "variant": m["id"], "head": m["head"], "inherited_limitations": m["inherited_limitations"]}
    if cmd == "set":
        if len(args) < 3 or args[1] != "=":
            raise DnaError("syntax: set <path> = <value>", "bad_args")
        path, raw = args[0], line.split("=", 1)[1].strip()
        try:
            value = json.loads(raw)  # JSON value: "line one\nline two", 0.16, true, [..], {..}
        except json.JSONDecodeError:
            value = raw.strip('"')
        return edit([{"op": "set", "path": path, "value": value}], line)
    if cmd == "replace":
        node = args[0].removesuffix(".asset")
        op = {"op": "replace", "node": node, "file": args[args.index("with") + 1]}
        if "preserve" in args:
            op["preserve"] = args[args.index("preserve") + 1].split(",")
        if "baked" in kv(args):
            op["baked_effects"] = kv(args)["baked"].split(",")
        return edit([op], line)
    if cmd == "move":
        k = kv(args)
        return edit([{"op": "move", "node": args[0], "dx": px(k.get("x", "0")), "dy": px(k.get("y", "0"))}], line)
    if cmd == "resize":
        k = kv(args)
        return edit([{"op": "resize", "node": args[0], "w": px(k["w"]), "h": px(k["h"]), "anchor": k.get("anchor", "top-left")}], line)
    if cmd == "remove":
        return edit([{"op": "remove", "node": args[0], "force": "force" in args}], line)
    if cmd == "add":
        op = {"op": "add", "node_def": read_json(args[0])}
        if "after" in args:
            op["after"] = args[args.index("after") + 1]
        return edit([op], line)
    if cmd in ("lock", "unlock"):
        hard = "soft" not in args
        return edit([{"op": cmd, "target": x, "hard": hard} if cmd == "lock" else {"op": cmd, "target": x}
                     for x in args[0].split(",")], line)
    if cmd == "adapt":
        k = kv(args)
        contents = {key: v.replace("\\n", "\n") for key, v in k.items() if key not in ("language", "font", "mirror")}
        op = {"op": "adapt", "language": k["language"], "contents": contents, "mirror_alignment": k.get("mirror", "yes") != "no"}
        if "font" in k:
            op["font"] = k["font"]
        return edit([op], line)
    if cmd == "reflow":
        k = kv(args)
        w, h = (int(v) for v in k["canvas"].lower().split("x"))
        pres = args[args.index("preserve") + 1].split(",") if "preserve" in args else []
        bad = [p for p in pres if p not in PRESERVE_POLICIES]
        if bad:
            raise DnaError(f"unsupported preserve policy {bad}", "unsupported", {"supported": sorted(PRESERVE_POLICIES)})
        return edit([{"op": "reflow", "canvas": [w, h], "preserve": pres}], line)
    if cmd == "compare":
        return compare_head_to_baseline()
    if cmd == "export":
        tid, vid = current()
        return export(tid, vid, kv(args).get("formats", "png,svg").split(","))
    if cmd == "undo":
        tid, vid = current()
        return undo(tid, vid)
    if cmd == "save":
        tid, vid = current()
        vd, meta, _ = load_variant(tid, vid)
        meta.update(name=args[-1], name_status="user_supplied")
        write_json(vd / "variant.json", meta)
        rebuild()
        return {"variant": vid, "name": meta["name"]}
    if cmd == "list":
        return [{k: t[k] for k in ("name", "id", "readiness", "aspect_ratio", "fixture")} for t in rebuild() if "all" in args or not t["fixture"]]
    if cmd == "find":
        return [{k: x[k] for k in ("name", "id", "readiness", "aspect_ratio")} for x in find(args)]
    if cmd == "batch":
        tid, vid = current()
        return transact(tid, vid, read_json(args[0]))
    if cmd == "status":
        s = session()
        if s.get("variant"):
            _, meta, head = load_variant(s["template"], s["variant"])
            s.update(head=head["revision"], variant_name=meta["name"], history=meta["history"][-5:])
        return s
    raise DnaError(f"unknown command {cmd!r}", "bad_command", {"commands": [
        "scan", "inspect", "explain", "reconstruct", "use", "set", "replace", "move", "resize", "remove", "add", "lock",
        "unlock", "adapt", "reflow", "compare", "export", "undo", "save", "list", "find", "batch", "status"]})


def main() -> int:
    argv = sys.argv[1:]
    lines = Path(argv[1]).read_text(encoding="utf-8").splitlines() if argv[:1] == ["-f"] else [" ".join(argv)]
    code = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            r = run(line)
            print(json.dumps({"command": line, "result": r}, indent=2, ensure_ascii=False, default=str))
        except DnaError as e:
            print(json.dumps({"command": line, **e.as_dict()}, indent=2, ensure_ascii=False, default=str))
            code = 2
            break
    return code


if __name__ == "__main__":
    sys.exit(main())
