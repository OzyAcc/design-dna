#!/usr/bin/env python3
"""Design DNA installer for every supported AI tool (Python 3.10+, standard library only).

  python install.py list                                   # every target, how it installs, what is installed
  python install.py install --target claude-code,cursor    # skill folders (user scope)
  python install.py install --target codex --method plugin # host package managers: codex | copilot | gemini-cli | claude-code
  python install.py install --target gemini-cli --method extension --from github   # straight from GitHub
  python install.py install --target copilot --scope project --project ~/code/my-repo
  python install.py install --target detected              # every tool found on this machine
  python install.py update                                 # refresh every copy this installer put in place
  python install.py uninstall --target cursor              # removes only unmodified copies it installed
  python install.py doctor [--target …]                    # Python, packages, Chromium, store, visible copies
  python install.py package --target chatgpt|all           # upload zips, plugins, extension, instruction kit
  python install.py docs [--check]                         # regenerate the compatibility tables and host guides

Every write supports --dry-run. Folders the installer did not create, or copies with local edits, are never
overwritten or removed: --force moves them to ~/design-dna/backups first.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "hosts"))
import hostkit as hk  # noqa: E402

UPLOAD_KINDS = ("upload", "instructions")


def targets_from(reg, spec: str | None, need=True) -> list[dict]:
    if not spec:
        if need:
            raise hk.HostError("choose --target (comma-separated ids, 'detected' or 'all'); see: python install.py list")
        return []
    if spec == "all":
        return list(reg["hosts"])
    if spec == "detected":
        found = [h for h in reg["hosts"] if (lambda d: d["paths"] or d["commands"])(hk.detect(h))]
        if not found:
            raise hk.HostError("no supported AI tool was detected on this machine; name one with --target")
        return found
    out = []
    for t in spec.split(","):
        h = hk.host(reg, t.strip())
        if h not in out:
            out.append(h)
    return out


def cmd_list(reg, a):
    rows = []
    for h in reg["hosts"]:
        det = hk.detect(h)
        installed = [v["path"] for v in hk.installs_visible_to(h)]
        rows.append({"id": h["id"], "name": h["name"], "methods": sorted({s["kind"] for s in h["surfaces"]}),
                     "skill_dir": h.get("skill_dirs", {}).get("user"), "detected": bool(det["paths"] or det["commands"]),
                     "installed": installed})
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"Design DNA {hk.version()}  ({hk.ROOT})\n")
    print(f"{'target':<13} {'tool':<44} {'methods':<28} {'found':<6} installed copy visible to it")
    for r in rows:
        print(f"{r['id']:<13} {r['name'][:43]:<44} {','.join(r['methods'])[:27]:<28} {'yes' if r['detected'] else '-':<6} "
              f"{'; '.join(r['installed']) or '-'}")
    print("\nGuides: docs/hosts/<target>.md   Compatibility: docs/hosts/COMPATIBILITY.md")
    return 0


def do_install(reg, a, update=False):
    hosts = targets_from(reg, a.target, need=not update)
    if update and not hosts:
        hosts = [h for h in reg["hosts"] if any(v["design_dna"] for v in hk.installs_visible_to(h, a.project))]
        if not hosts:
            print("nothing to update: no copy installed by this installer was found")
            return 0
    results, local = [], False
    for h in hosts:
        kinds = {s["kind"] for s in h["surfaces"]}
        if a.method in ("plugin", "extension"):
            results.append(hk.install_plugin(h, a.method, a.dry_run, a.yes, a.source, a.ref))
            local = True
        elif "skill-dir" in kinds:
            if update:
                dests = [Path(v["path"]) for v in hk.installs_visible_to(h, a.project) if v["design_dna"] and v["installed_for"] == h["id"]]
                dests = dests or ([hk.skill_dir(h, a.scope, a.project)] if a.target else [])
            else:
                dests = [hk.skill_dir(h, a.scope, a.project)]
            for d in dests:
                results.append(hk.install_skill_dir(h, hk.surface_for(h), d, a.dry_run, a.force))
            local = True
        else:
            pkgs = [s["package"] for s in h["surfaces"] if s["kind"] in UPLOAD_KINDS]
            out = Path(a.out).resolve()
            if a.dry_run:
                results.append({"host": h["id"], "dry_run": True, "actions": [f"build {p} in {out}" for p in pkgs]})
            else:
                man = hk.build_packages(pkgs, out)
                results.append({"host": h["id"], "packages": [str(out / v["file"]) for v in man["packages"].values()],
                                "next": [st for s in h["surfaces"] for st in s.get("steps", [])]})
    if local and not a.no_deps:
        results.append({"python_packages": hk.pip_install(a.dry_run)})
    report(results, a)
    failed = [r for r in results if r.get("status") == "failed" or (r.get("python_packages") or {}).get("code", 0) != 0]
    return 1 if failed else 0


def cmd_uninstall(reg, a):
    results = []
    for h in targets_from(reg, a.target):
        if a.method in ("plugin", "extension"):
            results.append(hk.uninstall_plugin(h, a.dry_run, a.source))
            continue
        if "skill_dirs" not in h:
            results.append({"host": h["id"], "actions": ["nothing installed locally: remove the uploaded skill in the tool's settings"]})
            continue
        results.append(hk.uninstall_skill_dir(h, hk.skill_dir(h, a.scope, a.project), a.dry_run, a.force))
    results.append({"kept": f"templates and bundles in {hk.store()} are never touched by uninstall"})
    report(results, a)
    return 0


def cmd_doctor(reg, a):
    ids = [h["id"] for h in targets_from(reg, a.target, need=False)]
    d = hk.doctor(ids, a.project, browser=not a.no_browser)
    if a.json:
        print(json.dumps(d, indent=2))
        return 0 if d["ok"] else 1
    py = d["python"]
    print(f"Design DNA {d['source']['version']} @ {d['source']['commit']}  ({d['source']['path']})")
    print(f"Python {py['python']}  packages: {'all present' if not py['missing'] else 'missing ' + ', '.join(py['missing'])}")
    print(f"Renderer: {d['renderer']}")
    print(f"Template store: {d['store']['path']} ({'writable' if d['store']['writable'] else 'NOT writable'})")
    for h in d["hosts"]:
        det = h["detected"]
        print(f"\n[{h['id']}] {h['name']}: {'found ' + ', '.join(det['paths'] + det['commands']) if det['paths'] or det['commands'] else 'not found on this machine'}")
        for v in h["visible_installs"] or [{"path": "no copy installed where this tool looks"}]:
            tag = "" if "design_dna" not in v else (f"  v{v['version']} @ {v['commit']}" if v["design_dna"] else "  (not installed by Design DNA)")
            print(f"  - {v['path']}{tag}")
    for w in d["warnings"]:
        print(f"WARNING: {w}")
    for e in d["errors"]:
        print(f"ERROR: {e}")
    print("\nOK" if d["ok"] else "\nProblems found (see ERROR lines).")
    return 0 if d["ok"] else 1


def cmd_package(reg, a):
    kinds = hk.package_kinds()
    if a.target in (None, "all"):
        ids = list(kinds)
    else:
        ids = []
        for t in a.target.split(","):
            t = t.strip()
            if t in kinds:
                ids.append(t)
                continue
            h = hk.host(reg, t)
            ids += [s["package"] for s in h["surfaces"] if s.get("package")] or ["skill"]
    man = hk.build_packages(list(dict.fromkeys(ids)), Path(a.out).resolve())
    print(json.dumps(man, indent=2))
    return 0


def cmd_docs(reg, a):
    import docgen

    changed = docgen.write_all(check=a.check)
    if a.check and changed:
        print("out of date (run: python install.py docs):\n  " + "\n  ".join(changed))
        return 1
    print("\n".join(f"{'stale' if a.check else 'wrote'} {c}" for c in changed) or "docs up to date")
    return 0


def report(results, a):
    if getattr(a, "json", False):
        print(json.dumps(results, indent=2, default=str))
        return
    for r in results:
        if "python_packages" in r:
            p = r["python_packages"]
            print(f"python packages: {'would run' if p.get('dry_run') else ('installed' if p.get('code') == 0 else 'FAILED')}: {' '.join(p['cmd'])}")
            if p.get("code"):
                print(p.get("out", ""))
            continue
        if "kept" in r:
            print(r["kept"])
            continue
        head = f"[{r.get('host')}]" + (" (dry run)" if r.get("dry_run") or r.get("status") == "dry_run" else "")
        print(head)
        for x in r.get("actions", []):
            print(f"  {x}")
        for c in r.get("commands", []):
            print(f"  $ {c}")
        for res in r.get("results", []):
            if "code" in res:
                print(f"    -> exit {res['code']}: {res['out'][-400:]}")
        if r.get("note"):
            print(f"  {r['note']}")
        if r.get("dest") and r.get("files"):
            print(f"  installed {r['files']} files, version {r['version']}" + (f"; previous copy moved to {r['backup']}" if r.get("backup") else ""))
        for p in r.get("packages", []):
            print(f"  package: {p}")
        for n in r.get("next", []):
            print(f"  next: {n}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--target", help="comma-separated target ids (python install.py list), 'detected' or 'all'")
    common.add_argument("--scope", choices=["user", "project"], default="user")
    common.add_argument("--project", help="project folder for --scope project")
    common.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    common.add_argument("--json", action="store_true")
    common.add_argument("--from", dest="source", choices=["local", "github"], default="local",
                        help="plugin/extension methods: build from this checkout (default) or install from the GitHub repository")
    common.add_argument("--ref", help="with --from github: a branch or tag (Copilot, Gemini CLI)")
    sub.add_parser("list", parents=[common])
    for name in ("install", "update"):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("--method", choices=["skill", "plugin", "extension"], default="skill")
        p.add_argument("--force", action="store_true", help="move foreign or locally edited copies to a backup and replace them")
        p.add_argument("--no-deps", action="store_true", help="do not pip-install the engine's Python packages")
        p.add_argument("--yes", action="store_true", help="unattended: answer a host CLI's confirmation for the package this installer just built "
                       "(Gemini CLI: trust the extension folder for this run)")
        p.add_argument("--out", default="dist/packages", help="where upload packages go (ChatGPT, Claude apps, instruction kit)")
    p = sub.add_parser("uninstall", parents=[common])
    p.add_argument("--method", choices=["skill", "plugin", "extension"], default="skill")
    p.add_argument("--force", action="store_true", help="move foreign or locally edited copies to a backup instead of refusing")
    p = sub.add_parser("doctor", parents=[common])
    p.add_argument("--no-browser", action="store_true", help="skip launching Chromium")
    p = sub.add_parser("package", parents=[common])
    p.add_argument("--out", default="dist/packages")
    p = sub.add_parser("docs")
    p.add_argument("--check", action="store_true", help="fail if generated docs are out of date")
    a = ap.parse_args(argv)
    try:
        reg = hk.load_registry()
        return {"list": cmd_list, "install": lambda r, x: do_install(r, x), "update": lambda r, x: do_install(r, x, update=True),
                "uninstall": cmd_uninstall, "doctor": cmd_doctor, "package": cmd_package, "docs": cmd_docs}[a.cmd](reg, a)
    except hk.HostError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
