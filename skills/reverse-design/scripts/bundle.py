"""Portable template bundles (.dnab) and storage backends. Storage is separate from the design engine.

  python bundle.py export   "<id | name>" --to <file.dnab | library-dir> [--fonts embed|reference]
  python bundle.py validate <file.dnab> [--font-dir DIR ...]
  python bundle.py import   <file.dnab> [--as-id ID] [--font-dir DIR ...]
  python bundle.py list     <library-dir>
  python bundle.py get      "<id | name | alias>" --from <library-dir> [--import] [--font-dir DIR ...]

A bundle is a ZIP: manifest.json (schemas/bundle.schema.json) + template/<files>. It carries the passport, scene,
source reference, content-hashed assets, font references + hashes (font bytes embedded, or referenced and resolved
by hash on import), scan evidence, the approved baseline, renderer pin + migrations, and every variant with all
revisions, transactions and rejected transactions. Render caches and exports are excluded (re-creatable).
Every file is hash-listed; import verifies every hash and the model before writing anything.

Host persistence seam: `StorageBackend` (put/get/list of whole bundles). `FilesystemBackend` is implemented and
tested — any mounted persistent folder works with it. A host-specific file store (e.g. ChatGPT Work) needs a small
adapter implementing the same three methods: that integration is UNVERIFIED here.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (SCHEMA_VERSION, TOOL_VERSION, DnaError, now, read_json, sha256_bytes, sha256_file,  # noqa: E402
                    template_dir, write_json)

BUNDLE_VERSION = "1.0.0"
EXCLUDE_PARTS = {".render", "renders", "exports", "__pycache__"}
FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
             Path("/Library/Fonts"), Path.home() / "Library/Fonts", Path("/System/Library/Fonts"),
             Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts", Path.home() / ".local/share/fonts"]


# ------------------------------------------------------------------ storage seam
class StorageBackend(Protocol):
    """What a host must provide to persist bundles: whole-file put/get/list. Nothing else touches host storage."""

    def put(self, name: str, data: bytes) -> str: ...

    def get(self, name: str) -> bytes: ...

    def list(self) -> list[str]: ...


class FilesystemBackend:
    """Bundles as files in a folder. Never overwrites: each export is a new `<id>@<timestamp>.dnab`."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, data: bytes) -> str:
        p = self.root / name
        if p.exists():
            raise DnaError(f"{p} exists; bundles are immutable", "immutable_conflict")
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return str(p)

    def get(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def list(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("*.dnab"))


def _fonts_used(tdir):
    ids = {}
    scenes = [tdir / "scene.json"] + sorted(tdir.glob("variants/*/revisions/rev-*.json"))
    for sp in scenes:
        for aid, a in read_json(sp)["assets"].items():
            if a["kind"] == "font":
                ids[a["path"]] = {"asset": aid, "sha256": a["sha256"], "names": a.get("font_names"), "path": a["path"]}
    return ids


def _collect(tdir, fonts):
    font_paths = set(_fonts_used(tdir)) if fonts == "reference" else set()
    for f in sorted(tdir.rglob("*")):
        rel = f.relative_to(tdir).as_posix()
        if f.is_file() and not (EXCLUDE_PARTS & set(f.relative_to(tdir).parts)) and rel not in font_paths and not f.name.endswith(".tmp"):
            yield rel, f


def export_bundle(ref, dest, fonts="embed") -> dict:
    from index_templates import resolve_template

    tid = resolve_template(ref)["id"]
    tdir = template_dir(tid)
    passport = read_json(tdir / "passport.json")
    used = _fonts_used(tdir)
    files = [(rel, f) for rel, f in _collect(tdir, fonts)]
    variants = {}
    for vj in sorted(tdir.glob("variants/*/variant.json")):
        v = read_json(vj)
        variants[v["id"]] = {"name": v["name"], "head": v["head"], "revisions": v["revisions"], "baseline_revision": v["baseline_revision"]}
    manifest = {"schema_version": SCHEMA_VERSION, "bundle_version": BUNDLE_VERSION, "engine": TOOL_VERSION,
                "template_id": tid, "name": passport["name"], "aliases": passport.get("aliases", []), "readiness": passport["readiness"],
                "exported_at": now(), "render_pin": passport.get("render_pin"), "baseline_render": passport.get("baseline_render"),
                "fonts": [dict(v, embedded=fonts == "embed", bytes=(tdir / v["path"]).stat().st_size if (tdir / v["path"]).exists() else None)
                          for v in used.values()],
                "variants": variants, "files": [{"path": rel, "sha256": sha256_file(f), "bytes": f.stat().st_size} for rel, f in files]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for rel, f in files:
            z.write(f, "template/" + rel)
    name = f"{tid}@{_dt.datetime.now().strftime('%Y%m%dT%H%M%S')}{'-fontref' if fonts == 'reference' else ''}.dnab"
    dest = Path(dest)
    path = FilesystemBackend(dest).put(name, buf.getvalue()) if dest.suffix != ".dnab" else _write_new(dest, buf.getvalue())
    return {"bundle": path, "template_id": tid, "name": passport["name"], "files": len(files), "bytes": len(buf.getvalue()),
            "fonts": fonts, "variants": list(variants)}


def _write_new(p, data):
    if p.exists():
        raise DnaError(f"{p} exists; bundles are immutable", "immutable_conflict")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


def _safe(name):
    if name.startswith(("/", "\\")) or ".." in name.split("/") or ":" in name or "\\" in name:
        raise DnaError(f"unsafe path in bundle: {name!r}", "path_traversal")
    return name


def find_fonts(wanted: dict, font_dirs=(), search_system=True) -> dict:
    """wanted: sha256 -> bytes. Scans the given dirs first, then the platform font folders; size first, then hash."""
    found = {}
    for d in [Path(x) for x in font_dirs] + (FONT_DIRS if search_system else []):
        if len(found) == len(wanted) or not d.exists():
            continue
        for f in d.rglob("*"):
            if f.suffix.lower() in (".ttf", ".otf", ".ttc") and f.is_file():
                try:
                    size = f.stat().st_size
                except OSError:
                    continue
                if size in wanted.values():
                    h = sha256_file(f)
                    if h in wanted and h not in found:
                        found[h] = f
    return found


def validate_bundle(path, font_dirs=(), search_system=True) -> dict:
    from validate_model import check_scene, schema_errors

    errors, warnings = [], []
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        errors += [f"manifest: {e}" for e in schema_errors(manifest, "bundle.schema.json")]
        listed = {f["path"]: f for f in manifest.get("files", [])}
        names = {n[len("template/"):] for n in z.namelist() if n.startswith("template/")}
        for n in names:
            _safe(n)
        errors += [f"unlisted file in bundle: {n}" for n in sorted(names - set(listed))]
        errors += [f"missing file: {n}" for n in sorted(set(listed) - names)]
        for n in sorted(names & set(listed)):
            if sha256_bytes(z.read("template/" + n)) != listed[n]["sha256"]:
                errors.append(f"hash mismatch: {n}")
        ref_fonts = {f["sha256"]: f["bytes"] for f in manifest.get("fonts", []) if not f["embedded"]}
        resolved = find_fonts(ref_fonts, font_dirs, search_system) if ref_fonts else {}
        fonts = [dict(f, resolved=str(resolved[f["sha256"]]) if f["sha256"] in resolved else (None if not f["embedded"] else "embedded"))
                 for f in manifest.get("fonts", [])]
        for f in fonts:
            if f["resolved"] is None:
                errors.append(f"referenced font {f['names'].get('full') if f.get('names') else f['asset']} "
                              f"(sha256 {f['sha256'][:12]}) not found; pass --font-dir with the original file")
        model = {}
        if not errors:
            with tempfile.TemporaryDirectory() as tmp:
                t = Path(tmp)
                for n in names:
                    (t / n).parent.mkdir(parents=True, exist_ok=True)
                    (t / n).write_bytes(z.read("template/" + n))
                for f in fonts:
                    if f["resolved"] not in (None, "embedded"):
                        (t / f["path"]).parent.mkdir(parents=True, exist_ok=True)
                        (t / f["path"]).write_bytes(Path(f["resolved"]).read_bytes())
                rep = check_scene(read_json(t / "scene.json"), t)
                errors += [f"scene: {e}" for e in rep["errors"]]
                errors += [f"passport: {e}" for e in schema_errors(read_json(t / "passport.json"), "template.schema.json")]
                if (t / "evidence/evidence.json").exists():
                    errors += [f"evidence: {e}" for e in schema_errors(read_json(t / "evidence/evidence.json"), "evidence.schema.json")]
                br = manifest.get("baseline_render")
                if br and (not (t / br["path"]).exists() or sha256_file(t / br["path"]) != br["sha256"]):
                    errors.append("approved baseline render missing or altered")
                for vid, v in manifest.get("variants", {}).items():
                    revs = set(v["revisions"])
                    for r in v["revisions"]:
                        s = read_json(t / f"variants/{vid}/revisions/rev-{r:04d}.json")
                        if r != v["baseline_revision"] and s.get("base_revision") not in revs:
                            errors.append(f"variant {vid}: revision {r} has an unknown parent")
                    head = read_json(t / f"variants/{vid}/revisions/rev-{v['head']:04d}.json")
                    errors += [f"variant {vid} head: {e}" for e in check_scene(head, t)["errors"]]
                    model[vid] = {"head": v["head"], "revisions": len(revs)}
    return {"valid": not errors, "errors": errors, "warnings": warnings, "template_id": manifest.get("template_id"),
            "name": manifest.get("name"), "fonts": fonts, "variants": model, "files": len(listed)}


def import_bundle(path, as_id=None, font_dirs=()) -> dict:
    from index_templates import rebuild

    rep = validate_bundle(path, font_dirs)
    if not rep["valid"]:
        raise DnaError("bundle failed validation; nothing was imported", "invalid_bundle", rep)
    tid = as_id or rep["template_id"]
    dest = template_dir(tid)
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        if dest.exists():
            same = all((dest / f["path"]).exists() and sha256_file(dest / f["path"]) == f["sha256"] for f in manifest["files"])
            if same and not as_id:
                return {"status": "already_present", "template_id": tid, "dir": str(dest)}
            raise DnaError(f"template id {tid!r} already exists with different content", "id_collision",
                           {"options": ["import with --as-id <new-id>"]})
        for f in manifest["files"]:
            out = dest / _safe(f["path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read("template/" + f["path"]))
    for f in rep["fonts"]:
        if f["resolved"] not in (None, "embedded"):
            (dest / f["path"]).parent.mkdir(parents=True, exist_ok=True)
            (dest / f["path"]).write_bytes(Path(f["resolved"]).read_bytes())
    if as_id:
        for sp in [dest / "scene.json"] + sorted(dest.glob("variants/*/revisions/rev-*.json")):
            s = read_json(sp)
            s["template_id"] = tid
            write_json(sp, s)
        for vj in dest.glob("variants/*/variant.json"):
            v = read_json(vj)
            v["template"] = tid
            write_json(vj, v)
        p = read_json(dest / "passport.json")
        p["id"] = tid
        p.setdefault("aliases", [])
        write_json(dest / "passport.json", p)
    p = read_json(dest / "passport.json")
    p.setdefault("imports", []).append({"bundle": Path(path).name, "at": now(), "exported_at": manifest["exported_at"]})
    write_json(dest / "passport.json", p)
    rebuild()
    return {"status": "imported", "template_id": tid, "dir": str(dest), "files": len(manifest["files"]),
            "fonts_resolved": [f for f in rep["fonts"] if not f["embedded"]], "variants": rep["variants"]}


class Library:
    """Retrieval by stable id, name or alias across a folder of bundles (newest export wins)."""

    def __init__(self, backend):
        self.backend = backend if hasattr(backend, "list") else FilesystemBackend(backend)

    def entries(self) -> list[dict]:
        out = []
        for name in self.backend.list():
            with zipfile.ZipFile(io.BytesIO(self.backend.get(name))) as z:
                m = json.loads(z.read("manifest.json"))
            out.append({"bundle": name, "template_id": m["template_id"], "name": m["name"], "aliases": m.get("aliases", []),
                        "readiness": m.get("readiness"), "exported_at": m["exported_at"], "variants": list(m.get("variants", {}))})
        return out

    def find(self, ref: str) -> dict:
        r = ref.strip().lower()
        hits = [e for e in self.entries() if r in ([e["template_id"], e["name"].lower()] + [x.lower() for x in e["aliases"]])]
        if len({h["template_id"] for h in hits}) > 1:
            raise DnaError(f"{ref!r} matches several templates", "ambiguous_target", {"candidates": hits})
        if not hits:
            raise DnaError(f"no bundle for {ref!r}", "unknown_template")
        return max(hits, key=lambda e: e["exported_at"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("export"); s.add_argument("ref"); s.add_argument("--to", required=True); s.add_argument("--fonts", choices=["embed", "reference"], default="embed")
    for c in ("validate", "import"):
        s = sub.add_parser(c); s.add_argument("bundle"); s.add_argument("--font-dir", action="append", default=[])
        if c == "import":
            s.add_argument("--as-id")
    s = sub.add_parser("list"); s.add_argument("library")
    s = sub.add_parser("get"); s.add_argument("ref"); s.add_argument("--from", dest="library", required=True)
    s.add_argument("--import", dest="do_import", action="store_true"); s.add_argument("--font-dir", action="append", default=[])
    a = ap.parse_args()
    try:
        if a.cmd == "export":
            r = export_bundle(a.ref, a.to, a.fonts)
        elif a.cmd == "validate":
            r = validate_bundle(a.bundle, a.font_dir)
        elif a.cmd == "import":
            r = import_bundle(a.bundle, a.as_id, a.font_dir)
        elif a.cmd == "list":
            r = Library(a.library).entries()
        else:
            e = Library(a.library).find(a.ref)
            r = import_bundle(Path(a.library) / e["bundle"], None, a.font_dir) if a.do_import else e
    except DnaError as e:
        print(json.dumps(e.as_dict(), indent=2, ensure_ascii=False, default=str))
        return 2
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    return 0 if not isinstance(r, dict) or r.get("valid", True) else 1


if __name__ == "__main__":
    sys.exit(main())
