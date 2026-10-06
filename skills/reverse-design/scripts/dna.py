"""Design DNA command interface (the formal, repeatable syntax; grammar in references/command-contract.md).

  python dna.py 'scan "C:/refs/poster.png" as "Editorial Product Spotlight"'
  python dna.py -f session.dna        # replay a script: one command per line, '#' comments

The current template/variant persists in <store>/session.json. Every edit command is one transaction:
validated, rendered, verified, then committed as an immutable revision (or rejected with options).
Ending an edit with "keep everything else" authorises only that edit (+ declared dependencies) and freezes every
other property for the transaction; explicit locks still conflict and are never removed implicitly.
Template text and metadata are data: nothing read from a template is executed.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_patch import export, load_variant, new_variant, transact, undo  # noqa: E402
from baseline import migrate_baseline, reconstruct  # noqa: E402,F401  (reconstruct is part of the public API)
from bundle import Library, export_bundle, import_bundle, validate_bundle  # noqa: E402
from common import SCAN_CATEGORIES, SCHEMA_VERSION, DnaError, load_evidence, read_json, store_root, template_dir, write_json  # noqa: E402
from index_templates import find, rebuild, resolve_template  # noqa: E402
from inspect_source import create_template  # noqa: E402
from verify_change import verify_change  # noqa: E402

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


def edit(ops, line, relax=None, keep=None):
    tid, vid = current()
    _, _, head = load_variant(tid, vid)
    patch = {"schema_version": SCHEMA_VERSION, "base_revision": head["revision"], "intent": line, "ops": ops}
    if relax:
        patch["relax"] = relax
    if keep:
        patch["keep"] = keep
    t = transact(tid, vid, patch)
    v = t["verification"]
    vis = (v.get("vs_approved_baseline") or v).get("visual_changes") or {}
    return {"status": "committed", "revision": t["revision"], "changes": [(c["path"], c["kind"]) for c in t["changes"]],
            "relaxed_constraints": [n for n in t.get("constraint_notes", []) if n.get("relaxed")],
            "verification": v["status"], "compared_against": vis.get("compared_against"),
            "changed_outside_influence": vis.get("outside_influence"),
            "transaction": f"variants/{vid}/transactions/txn-{t['revision']:04d}.json"}


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


KEEP = "keep everything else"


def run(line: str):
    keep = None
    if line.rstrip().lower().endswith(KEEP):
        line, keep = line.rstrip()[: -len(KEEP)].rstrip().rstrip(","), "everything_else"
    t = tokens(line)
    if not t:
        return None
    cmd, args = t[0].lower(), t[1:]
    E = lambda ops: edit(ops, line + (f" [{KEEP}]" if keep else ""), keep=keep)
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
        return E([{"op": "set", "path": path, "value": value}])
    if cmd == "replace":
        node = args[0].removesuffix(".asset")
        op = {"op": "replace", "node": node, "file": args[args.index("with") + 1]}
        if "preserve" in args:
            op["preserve"] = args[args.index("preserve") + 1].split(",")
        if "baked" in kv(args):
            op["baked_effects"] = kv(args)["baked"].split(",")
        return E([op])
    if cmd == "move":
        k = kv(args)
        return E([{"op": "move", "node": args[0], "dx": px(k.get("x", "0")), "dy": px(k.get("y", "0"))}])
    if cmd == "resize":
        k = kv(args)
        return E([{"op": "resize", "node": args[0], "w": px(k["w"]), "h": px(k["h"]), "anchor": k.get("anchor", "top-left")}])
    if cmd == "remove":
        return E([{"op": "remove", "node": args[0], "force": "force" in args}])
    if cmd == "add":
        op = {"op": "add", "node_def": read_json(args[0])}
        if "after" in args:
            op["after"] = args[args.index("after") + 1]
        return E([op])
    if cmd in ("lock", "unlock"):
        hard = "soft" not in args
        if cmd == "lock" and args[0] == "pixels":  # lock pixels x,y,w,h  -> verified against every later render
            return E([{"op": "lock", "target": "region", "kind": "pixel", "box": [float(v) for v in args[1].split(",")], "hard": True}])
        return E([{"op": cmd, "target": x, "hard": hard} if cmd == "lock" else {"op": cmd, "target": x}
                  for x in args[0].split(",")])
    if cmd == "adapt":
        k = kv(args)
        contents = {key: v.replace("\\n", "\n") for key, v in k.items() if key not in ("language", "font", "mirror")}
        op = {"op": "adapt", "language": k["language"], "contents": contents, "mirror_alignment": k.get("mirror", "yes") != "no"}
        if "font" in k:
            op["font"] = k["font"]
        return E([op])
    if cmd == "reflow":
        k = kv(args)
        w, h = (int(v) for v in k["canvas"].lower().split("x"))
        pres = args[args.index("preserve") + 1].split(",") if "preserve" in args else []
        bad = [p for p in pres if p not in PRESERVE_POLICIES]
        if bad:
            raise DnaError(f"unsupported preserve policy {bad}", "unsupported", {"supported": sorted(PRESERVE_POLICIES)})
        return E([{"op": "reflow", "canvas": [w, h], "preserve": pres}])
    if cmd == "compare":
        return compare_head_to_baseline()
    if cmd == "export":
        tid, vid = current()
        k = kv(args)
        return export(tid, vid, k.get("formats", "png,svg").split(","), k.get("svg-fonts", "embed"))
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
    if cmd == "migrate-baseline":  # migrate-baseline "<T>" [confirm]
        return migrate_baseline(resolve_template(args[0])["id"], confirm="confirm" in args)
    if cmd == "export-template":  # export-template "<T>" to <dir | file.dnab> [fonts=reference]
        return export_bundle(args[0], args[args.index("to") + 1], kv(args).get("fonts", "embed"))
    if cmd == "validate-bundle":  # validate-bundle <file> [font-dir=<dir>]
        return validate_bundle(args[0], [kv(args)["font-dir"]] if "font-dir" in kv(args) else [])
    if cmd == "import-template":  # import-template <file> [as <id>] [font-dir=<dir>]
        return import_bundle(args[0], args[args.index("as") + 1] if "as" in args else None,
                             [kv(args)["font-dir"]] if "font-dir" in kv(args) else [])
    if cmd == "bundles":  # bundles <library-dir>
        return Library(args[0]).entries()
    if cmd == "fetch":  # fetch "<id | name | alias>" from <library-dir>  -> newest bundle, imported
        lib = args[args.index("from") + 1]
        e = Library(lib).find(args[0])
        return dict(import_bundle(Path(lib) / e["bundle"]), bundle=e["bundle"])
    if cmd == "status":
        s = session()
        if s.get("variant"):
            _, meta, head = load_variant(s["template"], s["variant"])
            s.update(head=head["revision"], variant_name=meta["name"], history=meta["history"][-5:])
        return s
    raise DnaError(f"unknown command {cmd!r}", "bad_command", {"commands": [
        "scan", "inspect", "explain", "reconstruct", "use", "set", "replace", "move", "resize", "remove", "add", "lock",
        "unlock", "adapt", "reflow", "compare", "export", "undo", "save", "list", "find", "batch", "status",
        "migrate-baseline", "export-template", "validate-bundle", "import-template", "bundles", "fetch"]})


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
