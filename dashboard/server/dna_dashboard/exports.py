"""Downloads: selected outputs or a whole run as a ZIP with a readable manifest.

The ZIP holds only the chosen outputs' files (renders, SVG + manifest, evidence) and two manifests: manifest.json
(stable ids, hashes, product, template version, language, copy, mode, check status, limitations) and MANIFEST.txt
(the same, readable). It never includes credentials, other uploads, engine stores or temporary files.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from . import config, db
from .errors import AppError

FINAL = ("completed",)


def output_manifest_entry(o: dict) -> dict:
    from .handlers.output_jobs import copy_used

    inp = o["inputs"] or {}
    used = copy_used(o)
    return {"output_id": o["id"], "revision": o["revision"], "pair_id": o["pair_id"], "status": o["status"], "review": o["review_state"],
            "mode": o["mode"], "language": o["language"], "text_policy": inp.get("creative_text") if o["mode"] == "creative" else None,
            "product": {"id": o["product_id"], "name": (inp.get("product") or {}).get("name")},
            "template": {"id": o["template_id"], "name": (inp.get("template") or {}).get("name"), "version_id": o["template_version_id"],
                         "version": (inp.get("template") or {}).get("number"), "bundle_sha256": (inp.get("template") or {}).get("bundle_sha256")},
            "copy": [{"slot": e["slot_id"], "role": e["role"], "text": e["value"], "source": e["source"], "hidden": e["hidden"],
                      "used": used and not e.get("unused")} for e in inp.get("slots", [])],
            "instructions": inp.get("instructions"), "checks": (o.get("checks") or {}).get("verification_status") or (o.get("checks") or {}).get("path"),
            "limitations": o.get("limitations") or [], "provenance": {k: v for k, v in (o.get("provenance") or {}).items() if k != "prompt"},
            "files": [{"name": f["name"], "kind": f["kind"], "sha256": f["sha256"], "bytes": f["bytes"],
                       "width": f.get("width"), "height": f.get("height")} for f in o.get("files") or []]}


def build_zip(conn, output_ids: list[str], include_evidence=True, label="outputs") -> tuple[bytes, str]:
    if not output_ids:
        raise AppError("choose at least one output", "nothing_selected")
    outs = []
    for oid in output_ids:
        o = db.one(conn, "SELECT * FROM outputs WHERE id = ?", (oid,))
        if not o:
            raise AppError(f"output {oid} was not found", "not_found", 404)
        outs.append(o)
    root = config.get().outputs.resolve()
    buf = io.BytesIO()
    manifest = {"generated_by": "Design DNA dashboard", "exported_at": db.now(), "outputs": []}
    names = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for o in outs:
            entry = output_manifest_entry(o)
            folder = f"{o['id']}" if o["status"] not in FINAL else ""
            for f in o.get("files") or []:
                if f["kind"] in ("evidence", "refused_candidate") and not include_evidence:
                    continue
                p = Path(f["path"]).resolve()
                if root not in p.parents or not p.exists():
                    continue  # only files the app wrote for this output
                arc = (f"{'review/' + folder + '/' if folder else ''}" + (f"evidence/{o['id']}/{Path(f['name']).name}" if f["kind"] in ("evidence",)
                                                                           else f["name"]))
                if arc in names:
                    arc = f"{o['id']}/{arc}"
                names.add(arc)
                z.write(p, arc)
                f["archive_path"] = arc
            entry["archive_paths"] = [f.get("archive_path") for f in o.get("files") or [] if f.get("archive_path")]
            manifest["outputs"].append(entry)
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        lines = ["Design DNA export", f"exported {manifest['exported_at']}", ""]
        for e in manifest["outputs"]:
            lines += [f"{e['output_id']} (revision {e['revision']}) — {e['status']}, review: {e['review']}",
                      f"  product: {e['product']['name']}   template: {e['template']['name']} v{e['template']['version']}   "
                      f"language: {e['language']}   mode: {e['mode']}",
                      f"  checks: {e['checks']}"]
            lines += [f"  {c['role']}: {('(hidden)' if c['hidden'] else repr(c['text']))}  [{c['source']}]"
                      + ("" if c["used"] else "  (not used: imagery only)") for c in e["copy"]]
            lines += [f"  limitation: {x}" for x in e["limitations"]]
            lines += [f"  file: {p}" for p in e["archive_paths"]] + [""]
        z.writestr("MANIFEST.txt", "\n".join(lines))
    return buf.getvalue(), f"design-dna-{label}.zip"
