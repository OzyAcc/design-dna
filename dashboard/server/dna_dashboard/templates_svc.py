"""Template records, workspaces and immutable versions.

Layout under <data>/templates/<template id>/:
  workspace/            an engine store (DESIGN_DNA_HOME) holding the mutable draft or working copy
  staging/<stage id>/   staged rebuilds: a copy of the workspace template where `reconstruct` may approve a baseline
                        without touching any saved version
  versions/vN-*.dnab    sealed version bundles (validated .dnab), never rewritten
  versions/vN/          a read-only extraction of that bundle used to show its artifacts

A version is what batches select and jobs freeze. Generation always imports the version's bundle into its own store.
"""
from __future__ import annotations

import json
import math
import shutil
import zipfile
from pathlib import Path

from PIL import Image

from . import config, db, engine
from . import enginelib as el
from .errors import AppError, conflict, not_found

READINESS_LABEL = {"scan_in_progress": "Draft / scan in progress", "scanned": "Scanned", "partial_baseline": "Partial rebuild",
                   "editable_close": "Editable match", "exact_pixels": "Exact pixel match"}
PASSPORT_KEYS = ("character", "goal", "theme", "audience_assumptions", "channels", "literal_message", "takeaway", "mechanism",
                 "usage", "unsuitable_for", "medium", "preserve")
ENGINE_PASSPORT_KEYS = ("character", "goal", "theme", "audience_assumptions", "channels", "literal_message", "takeaway", "mechanism",
                        "usage", "unsuitable_for", "medium")


def root(tid) -> Path:
    return config.get().templates / tid


def workspace(tid) -> Path:
    return root(tid) / "workspace"


def work_tdir(tpl) -> Path:
    return workspace(tpl["id"]) / "templates" / tpl["engine_id"]


def get(conn, tid) -> dict:
    t = db.one(conn, "SELECT * FROM templates WHERE id = ?", (tid,))
    if not t:
        raise not_found("template", tid)
    return t


def version(conn, vid) -> dict:
    v = db.one(conn, "SELECT * FROM template_versions WHERE id = ?", (vid,))
    if not v:
        raise not_found("template version", vid)
    return v


def versions(conn, tid) -> list[dict]:
    return db.all_(conn, "SELECT * FROM template_versions WHERE template_id = ? ORDER BY number DESC", (tid,))


def busy(conn, tid) -> dict | None:
    return db.one(conn, "SELECT id, kind, stage FROM jobs WHERE lock_key = ? AND status IN ('queued', 'running') ORDER BY created_at LIMIT 1",
                  (f"template:{tid}",))


def ensure_idle(conn, tid):
    j = busy(conn, tid)
    if j:
        raise conflict("this template is busy with another step; wait for it to finish", "template_busy", job=j)


def search_text(t: dict) -> str:
    p = t.get("passport") or {}
    vals = [t.get("name", "")] + [str((p.get(k) or {}).get("value") or "") for k in PASSPORT_KEYS] + list(t.get("tags") or [])
    return " ".join(vals).lower()


def labeled(value, status="user_supplied"):
    return {"value": value, "status": status}


# ------------------------------------------------------------------ creation
def create_from_asset(conn, asset: dict, name: str, name_status="user_supplied") -> dict:
    from .intake import original_file

    if asset["role"] != "inspiration":
        raise AppError("a template is created from an inspiration image (this asset was added as a product input)", "wrong_role")
    tid = db.new_id("tp")
    engine_id = el.common().slugify(name or "template", 40) + "-" + tid[-6:]
    home = workspace(tid)
    home.mkdir(parents=True, exist_ok=True)
    src_dir = root(tid) / "intake"
    src_dir.mkdir(parents=True, exist_ok=True)
    src = src_dir / f"source{asset['ext']}"
    shutil.copyfile(original_file(asset), src)
    res = engine.call("create_template", {"source": str(src), "name": name, "name_status": name_status, "engine_id": engine_id},
                      home, timeout=180)
    meta = res["metadata"]
    W, H = meta["oriented_width"], meta["oriented_height"]
    g = math.gcd(W, H)
    t = {"id": tid, "engine_id": res["template_id"], "name": name, "role": "original", "source_asset_id": asset["id"],
         "passport": {"name": labeled(name, name_status)}, "draft": {"step": "purpose", "intake": {
             "metadata": meta, "canonical": res["canonical"], "candidate_artwork_bounds": res["candidate_artwork_bounds"]}},
         "readiness": "scan_in_progress", "width": W, "height": H, "aspect_ratio": f"{W // g}:{H // g}", "tags": [],
         "created_at": db.now(), "updated_at": db.now()}
    t["search_text"] = search_text(t)
    db.insert(conn, "templates", t)
    return get(conn, tid)


def write_engine_passport(t: dict) -> None:
    """Mirror the labelled passport fields into the workspace's passport.json (engine schema: {value, status})."""
    pp_path = work_tdir(t) / "passport.json"
    if not pp_path.exists():
        return
    pp = el.read_json(pp_path)
    p = t.get("passport") or {}
    if (p.get("name") or {}).get("value"):
        pp["name"] = p["name"]["value"]
        pp["name_status"] = p["name"].get("status", "user_supplied") if p["name"].get("status") in ("user_supplied", "suggested", "user_confirmed") else "user_supplied"
    for k in ENGINE_PASSPORT_KEYS:
        v = p.get(k)
        if isinstance(v, dict) and v.get("value") not in (None, "", []):
            st = v.get("status", "user_supplied")
            pp[k] = {"value": v["value"], "status": st if st in ("user_supplied", "user_confirmed", "suggested", "observed", "inferred", "unknown") else "suggested"}
        elif k in pp and (v is None or v.get("value") in (None, "", [])):
            pp.pop(k)
    pp["updated"] = db.now()
    el.write_json(pp_path, pp)


def save_draft(conn, tid: str, base_revision: int, changes: dict) -> dict:
    """Optimistic save: the client sends the draft_revision it edited; a stale revision is refused, never merged blindly."""
    with db.tx(conn):
        t = get(conn, tid)
        if base_revision != t["draft_revision"]:
            raise conflict("this draft was changed elsewhere since you opened it; reload to see the latest version",
                           "stale_draft", current_revision=t["draft_revision"])
        upd = {"draft_revision": t["draft_revision"] + 1, "updated_at": db.now()}
        if "name" in changes and changes["name"]:
            upd["name"] = str(changes["name"])[:120]
            t["passport"]["name"] = labeled(upd["name"], "user_supplied")
        if "passport" in changes:
            for k, v in (changes["passport"] or {}).items():
                if k in PASSPORT_KEYS:
                    t["passport"][k] = v if isinstance(v, dict) else labeled(v)
            upd["passport"] = t["passport"]
        elif "name" in upd:
            upd["passport"] = t["passport"]
        if "draft" in changes:
            d = dict(t["draft"] or {})
            for k, v in (changes["draft"] or {}).items():
                if k in ("step", "elements", "review_confirmed", "rules", "notes", "scan_mode", "supporting_assets", "default_copy",
                         "default_instructions"):
                    d[k] = v
            upd["draft"] = d
        for k in ("tags", "collection_id", "medium"):
            if k in changes:
                upd[k] = changes[k]
        merged = dict(t, **upd)
        upd["search_text"] = search_text(merged)
        db.update(conn, "templates", tid, upd)
    t = get(conn, tid)
    write_engine_passport(t)
    return t


# ------------------------------------------------------------------ versions
def _safe_extract(bundle: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    with zipfile.ZipFile(bundle) as z:
        for n in z.namelist():
            if not n.startswith("template/") or n.endswith("/"):
                continue
            rel = n[len("template/"):]
            if rel.startswith(("/", "\\")) or ".." in rel.split("/") or ":" in rel or "\\" in rel:
                raise AppError(f"unsafe path in bundle: {rel!r}", "unsafe_bundle")
            out = (dest / rel).resolve()
            if base not in out.parents:
                raise AppError(f"unsafe path in bundle: {rel!r}", "unsafe_bundle")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))


def _content_locked(scene, n) -> list[str]:
    """Hard locks that would refuse a change to this node's content/asset/visibility (reported in preflight)."""
    if not n:
        return []
    out = []
    for lk in scene.get("locks", []):
        if not lk.get("hard") or lk["kind"] == "pixel":
            continue
        t = lk["target"]
        if t == "content" and n.get("type") in ("text", "image", "background"):
            out.append(lk["id"])
        elif t.split(".")[0] in (n["id"], n.get("alias")) and (t.count(".") == 0 or t.split(".", 1)[1] in ("content", "asset", "visible")):
            out.append(lk["id"])
    return out


def summarize(tdir: Path, design_variant=None, design_head=None) -> dict:
    """What batches and the inspector need from a template version, read from its canonical files."""
    scene = el.read_json(tdir / "scene.json")
    pp = el.read_json(tdir / "passport.json")
    if design_variant and (tdir / "variants" / design_variant / "variant.json").exists():
        meta = el.read_json(tdir / "variants" / design_variant / "variant.json")
        head = design_head if design_head is not None else meta["head"]
        scene = el.read_json(tdir / "variants" / design_variant / "revisions" / f"rev-{head:04d}.json")
    nodes = {n["id"]: n for n in scene["nodes"]}
    slots = []
    for s in scene["slots"]:
        n = nodes.get(s["node"]) or {}
        lim = s.get("limits") or {}
        slots.append({"id": s["id"], "role": s["role"], "type": s["type"], "node": s["node"], "limits": lim,
                      "required": bool(lim.get("required", s["type"] == "text" and s["role"] in ("headline", "title"))),
                      "locked": _content_locked(scene, n),
                      "fit": (n.get("fit") or {}).get("policy", s.get("fit", "strict")), "min_size": (n.get("fit") or {}).get("min_size"),
                      "template_text": n.get("content") if n.get("type") == "text" else None,
                      "lang": n.get("lang"), "direction": n.get("direction"), "geometry": n.get("geometry")})
    br = pp.get("baseline_render")
    ed = el.editability(scene)
    readiness = pp["readiness"]
    adapt_reasons, adapt_limits = [], []
    if not scene["slots"]:
        adapt_reasons.append("the template has no replaceable slots")
    if not br:
        adapt_reasons.append("no approved rebuild baseline: run Rebuild and compare first")
    if not pp.get("render_pin"):
        adapt_reasons.append("no pinned renderer")
    if readiness == "partial_baseline":
        adapt_limits.append("partial rebuild: " + "; ".join(pp.get("unresolved", [])[:4]))
    if ed["overall"] != "pass":
        adapt_limits.append(f"editability {ed['overall']}: some slots are not independently editable")
    missing_fonts = [a["id"] for a in scene["assets"].values() if a["kind"] == "font" and not (tdir / a["path"]).exists()]
    if missing_fonts:
        adapt_reasons.append(f"font files missing: {missing_fonts}")
    return {"canvas": {"width": scene["canvas"]["width"], "height": scene["canvas"]["height"]}, "readiness": readiness,
            "readiness_label": READINESS_LABEL.get(readiness, readiness), "slots": slots, "scan_state": scene["scan"]["state"],
            "baseline": {"approved": br, "match": pp.get("baseline_match"), "pin": {k: (pp.get("render_pin") or {}).get(k) for k in
                                                                                    ("channel", "browser_version", "pinned_at", "text_rendering")}},
            "editability": {"overall": ed["overall"], "slots": ed["slots"]}, "unresolved": pp.get("unresolved", []),
            "locks": scene.get("locks", []), "scene_sha256": el.model_hash(scene), "engine_revision": scene.get("revision"),
            "eligibility": {"adapt": {"eligible": not adapt_reasons, "reasons": adapt_reasons, "limitations": adapt_limits},
                            "creative": {"eligible": True, "reasons": [], "limitations": [
                                "creative results are new images: no pixel preservation or editability is claimed"]}}}


def create_version(conn, t: dict, home: Path, engine_id: str, created_from: str, *, parent_version_id=None, acceptance=None,
                   design_variant=None, design_head=None, job_dir: Path | None = None) -> dict:
    """Seal the given engine store's template as an immutable version: export bundle -> validate -> keep + extract."""
    vroot = root(t["id"]) / "versions"
    vroot.mkdir(parents=True, exist_ok=True)
    tmp = (job_dir or root(t["id"])) / "bundle-out"
    if tmp.exists():
        shutil.rmtree(tmp)
    exp = engine.call("export_bundle", {"engine_id": engine_id, "dest": str(tmp)}, home, timeout=600)
    val = engine.call("validate_bundle", {"bundle": exp["bundle"]}, home, timeout=600)
    if not val["valid"]:
        raise AppError("the exported bundle did not validate; no version was created", "invalid_bundle", 500, {"errors": val["errors"][:20]})
    # version numbers per template are serialised by the template's job lock; the files are written before the record
    n = (conn.execute("SELECT COALESCE(MAX(number), 0) FROM template_versions WHERE template_id = ?", (t["id"],)).fetchone()[0]) + 1
    dest = vroot / f"v{n}-{Path(exp['bundle']).name}"
    shutil.move(exp["bundle"], dest)
    dest.chmod(0o444)
    ex = vroot / f"v{n}"
    _safe_extract(dest, ex)
    summ = summarize(ex, design_variant, design_head)
    summ["bundle_validation"] = {"valid": True, "files": val["files"], "variants": val.get("variants")}
    d = t.get("draft") or {}
    slot_ids = {s["id"] for s in summ["slots"]}
    summ["defaults"] = {"copy": {k: v for k, v in (d.get("default_copy") or {}).items() if k in slot_ids},
                        "instructions": d.get("default_instructions") or "",
                        "preserve": ((t.get("passport") or {}).get("preserve") or {}).get("value")}
    thumb = vroot / f"v{n}.thumb.png"
    src_img = ex / summ["baseline"]["approved"]["path"] if summ["baseline"]["approved"] else ex / "source" / "canonical.png"
    with Image.open(src_img) as im:
        im = im.convert("RGBA")
        im.thumbnail((640, 640))
        im.save(thumb)
    with db.tx(conn):
        vid = db.new_id("tv")
        db.insert(conn, "template_versions", {
            "id": vid, "template_id": t["id"], "number": n, "bundle_path": str(dest), "bundle_sha256": el.common().sha256_file(dest),
            "engine_id": engine_id, "scene_sha256": summ["scene_sha256"], "design_variant": design_variant, "design_head": design_head,
            "readiness": summ["readiness"], "summary": summ, "created_from": created_from, "parent_version_id": parent_version_id,
            "acceptance": acceptance, "thumb_path": str(thumb), "created_at": db.now()})
        db.update(conn, "templates", t["id"], {"current_version_id": vid, "readiness": summ["readiness"], "updated_at": db.now()})
    return version(conn, vid)


def version_dir(v: dict) -> Path:
    return Path(v["bundle_path"]).parent / f"v{v['number']}"


def public_version(v: dict) -> dict:
    s = v.get("summary") or {}
    return {"id": v["id"], "template_id": v["template_id"], "number": v["number"], "readiness": v["readiness"],
            "readiness_label": READINESS_LABEL.get(v["readiness"], v["readiness"]), "created_from": v["created_from"],
            "parent_version_id": v["parent_version_id"], "acceptance": v["acceptance"], "created_at": v["created_at"],
            "bundle_sha256": v["bundle_sha256"], "scene_sha256": v["scene_sha256"], "design_variant": v["design_variant"],
            "design_head": v["design_head"], "canvas": s.get("canvas"), "slots": s.get("slots", []), "eligibility": s.get("eligibility"),
            "baseline": s.get("baseline"), "editability": s.get("editability"), "unresolved": s.get("unresolved", []),
            "thumb_url": f"/api/templates/{v['template_id']}/versions/{v['id']}/thumb",
            "download_url": f"/api/templates/{v['template_id']}/versions/{v['id']}/bundle"}


def public(conn, t: dict, full=False) -> dict:
    cur = version(conn, t["current_version_id"]) if t.get("current_version_id") else None
    p = t.get("passport") or {}
    out = {"id": t["id"], "name": t["name"], "role": t["role"], "engine_id": t["engine_id"], "parent_template_id": t["parent_template_id"],
           "parent_version_id": t["parent_version_id"], "collection_id": t["collection_id"], "tags": t.get("tags") or [],
           "passport": p, "readiness": t["readiness"], "readiness_label": READINESS_LABEL.get(t["readiness"], t["readiness"]),
           "status": "archived" if t.get("archived_at") else ("library" if cur else "draft"), "archived_at": t.get("archived_at"),
           "aspect_ratio": t.get("aspect_ratio"), "width": t.get("width"), "height": t.get("height"), "medium": t.get("medium"),
           "created_at": t["created_at"], "updated_at": t["updated_at"], "current_version": public_version(cur) if cur else None,
           "thumb_url": f"/api/templates/{t['id']}/thumb", "source_asset_id": t.get("source_asset_id"),
           "busy": busy(conn, t["id"])}
    if full:
        out["draft"] = t.get("draft") or {}
        out["draft_revision"] = t["draft_revision"]
        out["design_variant"] = t.get("design_variant")
        out["versions"] = [public_version(v) for v in versions(conn, t["id"])]
        if t.get("parent_template_id"):
            par = db.one(conn, "SELECT id, name FROM templates WHERE id = ?", (t["parent_template_id"],))
            pv = db.one(conn, "SELECT id, number FROM template_versions WHERE id = ?", (t["parent_version_id"],)) if t.get("parent_version_id") else None
            out["lineage"] = {"parent": par, "parent_version": pv}
        out["children"] = db.all_(conn, "SELECT id, name FROM templates WHERE parent_template_id = ?", (t["id"],))
    return out


def thumb_file(conn, t: dict) -> Path | None:
    if t.get("current_version_id"):
        v = version(conn, t["current_version_id"])
        if v.get("thumb_path") and Path(v["thumb_path"]).exists():
            return Path(v["thumb_path"])
    p = work_tdir(t) / "source" / "thumb.png"
    return p if p.exists() else None


def model_view(tdir: Path, design_variant=None, design_head=None) -> dict:
    """Inspector payload: scene parts, passport, coverage and evidence (as data), plus artifact paths relative to tdir."""
    scene = el.read_json(tdir / "scene.json")
    if design_variant and (tdir / "variants" / design_variant / "variant.json").exists():
        meta = el.read_json(tdir / "variants" / design_variant / "variant.json")
        scene = el.read_json(tdir / "variants" / design_variant / "revisions" / f"rev-{(design_head if design_head is not None else meta['head']):04d}.json")
    pp = el.read_json(tdir / "passport.json")
    evid = el.load_evidence(tdir)["records"]
    arts = {"reference": "source/canonical.png", "annotated": "evidence/annotated.png" if (tdir / "evidence/annotated.png").exists() else None}
    br = pp.get("baseline_render")
    if br and (tdir / br["path"]).exists():
        bdir = Path(br["path"]).parent
        arts["baseline"] = br["path"]
        for k in ("side_by_side", "overlay_50", "diff_heatmap"):
            p = bdir / "compare" / f"{k}.png"
            arts[k] = str(p) if (tdir / p).exists() else None
        crops = sorted((tdir / bdir / "compare" / "crops").glob("*.png")) if (tdir / bdir / "compare" / "crops").exists() else []
        arts["crops"] = {c.stem: str(c.relative_to(tdir)) for c in crops}
        rep = tdir / (pp.get("baseline_match") or {}).get("report", "") if (pp.get("baseline_match") or {}).get("report") else None
        arts["report"] = el.read_json(rep) if rep and rep.exists() else None
    return {"scene": {k: scene.get(k) for k in ("canvas", "tokens", "nodes", "slots", "constraints", "locks", "communication", "scan",
                                                "verification", "revision")},
            "assets": {k: {kk: a.get(kk) for kk in ("id", "kind", "source", "path", "width", "height", "font_names", "derived_from", "baked_effects")}
                       for k, a in scene["assets"].items()},
            "passport": pp, "evidence": evid, "artifacts": arts, "constants": el.constants(),
            "migrations": pp.get("render_migrations", [])}


def json_safe(o):
    return json.loads(json.dumps(o, default=str))
