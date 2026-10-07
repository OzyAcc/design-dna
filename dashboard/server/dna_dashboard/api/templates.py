"""Template library, creation workflow, inspector data, copies, edits, versions, bundles and renderer migration."""
from __future__ import annotations

import shutil
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from .. import commands, config, db, engine, intake, jobs
from .. import enginelib as el
from .. import templates_svc as ts
from ..errors import AppError, conflict
from .deps import file_response, get_conn, under

router = APIRouter()


def _job(conn, kind, t, payload, priority=4):
    return jobs.public(jobs.enqueue(conn, kind, dict(payload, template_id=t["id"]), lock_key=f"template:{t['id']}",
                                    template_id=t["id"], priority=priority))


@router.get("/templates")
def list_templates(q: str = "", collection: str = "", medium: str = "", aspect: str = "", readiness: str = "", role: str = "",
                   archived: int = 0, sort: str = "recent", conn=Depends(get_conn)):
    sql, args = "SELECT * FROM templates WHERE (archived_at IS NOT NULL) = ?", [1 if archived else 0]
    for col, val in (("collection_id", collection), ("medium", medium), ("aspect_ratio", aspect), ("readiness", readiness), ("role", role)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    for w in [w for w in q.lower().split() if w][:8]:
        sql += " AND search_text LIKE ?"
        args.append(f"%{w}%")
    sql += " ORDER BY " + ("name COLLATE NOCASE" if sort == "name" else "updated_at DESC")
    rows = db.all_(conn, sql, args)
    facets = {"aspects": sorted({r["aspect_ratio"] for r in db.all_(conn, "SELECT DISTINCT aspect_ratio FROM templates") if r["aspect_ratio"]}),
              "media": sorted({r["medium"] for r in db.all_(conn, "SELECT DISTINCT medium FROM templates") if r["medium"]}),
              "collections": db.all_(conn, "SELECT * FROM collections ORDER BY name COLLATE NOCASE")}
    return {"templates": [ts.public(conn, t) for t in rows], "facets": facets}


class CreateReq(BaseModel):
    asset_id: str
    name: str
    name_status: str = "user_supplied"
    supporting_asset_ids: list[str] = []


@router.post("/templates")
def create(body: CreateReq, conn=Depends(get_conn)):
    a = intake.get(conn, body.asset_id)
    name = body.name.strip()[:120] or "Untitled template"
    t = ts.create_from_asset(conn, a, name, body.name_status if body.name_status in ("user_supplied", "suggested") else "user_supplied")
    if body.supporting_asset_ids:
        ts.save_draft(conn, t["id"], t["draft_revision"], {"draft": {"supporting_assets": body.supporting_asset_ids}})
    return ts.public(conn, ts.get(conn, t["id"]), full=True)


@router.get("/templates/{tid}")
def detail(tid: str, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    out = ts.public(conn, t, full=True)
    out["jobs"] = [jobs.public(j) for j in db.all_(conn, "SELECT * FROM jobs WHERE template_id = ? ORDER BY created_at DESC LIMIT 20", (tid,))]
    return out


@router.get("/templates/{tid}/model")
def model(tid: str, source: str = "current", conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if source == "current":
        source = f"v:{t['current_version_id']}" if t.get("current_version_id") else "work"
    if source == "work":
        view = ts.model_view(ts.work_tdir(t), t.get("design_variant"))
    elif source.startswith("v:"):
        v = ts.version(conn, source[2:])
        if v["template_id"] != tid:
            raise AppError("that version belongs to another template", "bad_version")
        view = ts.model_view(ts.version_dir(v), v.get("design_variant"), v.get("design_head"))
    elif source.startswith("stage:"):
        st = (t["draft"] or {}).get("staged") or {}
        if st.get("stage_id") != source[6:]:
            raise AppError("that staged rebuild is no longer available", "stale_stage", 404)
        view = ts.model_view(ts.root(tid) / "staging" / st["stage_id"] / "home" / "templates" / t["engine_id"])
    else:
        raise AppError("source must be current, work, v:<version id> or stage:<stage id>", "bad_source")
    view["source"] = source
    return ts.json_safe(view)


@router.get("/templates/{tid}/files/{source}/{path:path}")
def files(tid: str, source: str, path: str, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if source == "work":
        base = ts.work_tdir(t)
    elif source.startswith("v:"):
        v = ts.version(conn, source[2:])
        if v["template_id"] != tid:
            raise AppError("that version belongs to another template", "bad_version")
        base = ts.version_dir(v)
    elif source.startswith("stage:"):
        base = ts.root(tid) / "staging" / source[6:] / "home" / "templates" / t["engine_id"]
    else:
        raise AppError("unknown file source", "bad_source")
    return file_response(under(base, path))


class DraftReq(BaseModel):
    base_revision: int
    changes: dict[str, Any]


@router.patch("/templates/{tid}/draft")
def save_draft(tid: str, body: DraftReq, conn=Depends(get_conn)):
    return ts.public(conn, ts.save_draft(conn, tid, body.base_revision, body.changes), full=True)


class MetaReq(BaseModel):
    name: Optional[str] = None
    collection_id: Optional[str] = None
    tags: Optional[list[str]] = None
    medium: Optional[str] = None


@router.patch("/templates/{tid}")
def update_meta(tid: str, body: MetaReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    ch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "collection_id" in ch and ch["collection_id"] == "":
        ch["collection_id"] = None
    return ts.public(conn, ts.save_draft(conn, tid, t["draft_revision"], ch), full=True)


class AnalyzeReq(BaseModel):
    provider: Optional[str] = None


@router.post("/templates/{tid}/analyze")
def analyze(tid: str, body: AnalyzeReq, conn=Depends(get_conn)):
    from ..providers import for_capability

    t = ts.get(conn, tid)
    for_capability("analysis", body.provider)  # fail fast with the setup path when nothing is configured
    return _job(conn, "template.analyze", t, {"provider": body.provider})


@router.post("/templates/{tid}/measure")
def measure(tid: str, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if t["role"] == "copy":
        raise AppError("copies are edited with typed changes, not re-scanned", "read_only")
    els = [e for e in (t["draft"] or {}).get("elements", []) if e.get("status") != "rejected"]
    if not els:
        raise AppError("accept or draw at least one element before measuring", "no_elements")
    pending = [e.get("key") for e in els if e.get("status") == "proposed"]
    if pending:
        raise conflict("review every proposal first: accept or reject it (a proposal is not a finding)", "unreviewed_proposals",
                       elements=pending[:20])
    ts.ensure_idle(conn, tid)
    return _job(conn, "template.measure", t, {})


class RulesReq(BaseModel):
    base_revision: int
    slots: list[dict] = []
    locks: Optional[list[dict]] = None
    default_copy: Optional[dict[str, str]] = None
    default_instructions: Optional[str] = None
    review_confirmed: Optional[bool] = None


@router.put("/templates/{tid}/rules")
def rules(tid: str, body: RulesReq, conn=Depends(get_conn)):
    """Slot limits, fit policy, required flags and locks for a template being scanned. Saved versions stay unchanged;
    a copy's rules change through typed edits (with revisions) instead."""
    t = ts.get(conn, tid)
    if t["role"] == "copy":
        raise AppError("a copy's rules change through typed edits (lock/unlock, set ...fit) so they get revisions", "use_edits")
    ts.ensure_idle(conn, tid)
    tdir = ts.work_tdir(t)
    scene = el.read_json(tdir / "scene.json")
    nodes = {n["id"]: n for n in scene["nodes"]}
    by_id = {s["id"]: s for s in scene["slots"]}
    for s in body.slots:
        sl = by_id.get(s.get("id"))
        if not sl:
            raise AppError(f"unknown slot {s.get('id')!r}", "bad_slot")
        lim = dict(sl.get("limits") or {})
        for k in ("max_chars", "max_lines"):
            if k in s:
                if s[k] in (None, "", 0):
                    lim.pop(k, None)
                else:
                    lim[k] = int(s[k])
        if "required" in s:
            lim["required"] = bool(s["required"])
        sl["limits"] = lim
        n = nodes.get(sl["node"])
        if n and n["type"] == "text" and "fit_policy" in s:
            if s["fit_policy"] == "fit":
                mn = float(s.get("min_size") or 0)
                if not mn or mn >= n["font"]["size"]:
                    raise AppError("a size range needs a minimum size below the current size", "bad_fit")
                n["fit"] = {"policy": "fit", "min_size": mn, "max_lines": int(lim.get("max_lines") or n.get("fit", {}).get("max_lines") or 1)}
            else:
                n["fit"] = {"policy": "strict", "max_lines": int(lim.get("max_lines") or n.get("fit", {}).get("max_lines") or 1)}
            sl["fit"] = n["fit"]["policy"]
    if body.locks is not None:
        locks = []
        for i, lk in enumerate(body.locks):
            target = str(lk.get("target", "")).strip()
            if not target:
                continue
            locks.append({"id": f"lock-{i + 1}-{el.common().slugify(target, 40)}", "target": target, "kind": lk.get("kind", "property"),
                          "hard": bool(lk.get("hard", True)), **({"box": lk["box"]} if lk.get("kind") == "pixel" else {})})
        scene["locks"] = locks
    if body.review_confirmed is not None and scene["scan"]["state"] != "in_progress":
        cov_ok = all(c in scene["scan"]["coverage"] for c in el.constants()["categories"])
        scene["scan"]["state"] = "complete" if body.review_confirmed and cov_ok and not (t["draft"] or {}).get("measure", {}).get("failures") else "partial"
    val = engine.call("validate", {"engine_id": t["engine_id"], "scene": scene}, ts.workspace(tid), timeout=180)
    if not val["valid"]:
        raise AppError("these rules make the model invalid; nothing was saved", "invalid_rules", 422, {"errors": val["errors"][:20]})
    el.write_json(tdir / "scene.json", scene)
    ch = {"draft": {}}
    if body.default_copy is not None:
        ch["draft"]["default_copy"] = {k: v for k, v in body.default_copy.items() if v is not None}
    if body.default_instructions is not None:
        ch["draft"]["default_instructions"] = body.default_instructions
    if body.review_confirmed is not None:
        ch["draft"]["review_confirmed"] = body.review_confirmed
    pp = el.read_json(tdir / "passport.json")
    if scene["scan"]["state"] == "complete" and not pp.get("baseline_render"):
        pp["readiness"] = "scanned"
        el.write_json(tdir / "passport.json", pp)
    t = ts.save_draft(conn, tid, body.base_revision, ch)
    d = dict(t["draft"])
    d["validation"] = {"valid": val["valid"], "errors": val["errors"][:40], "warnings": val["warnings"][:40],
                       "editability": val.get("editability"), "passport": val.get("passport")}
    with db.tx(conn):
        db.update(conn, "templates", tid, {"draft": d})
    return ts.public(conn, ts.get(conn, tid), full=True)


class RebuildReq(BaseModel):
    mode: str = "editable"


@router.post("/templates/{tid}/rebuild")
def rebuild(tid: str, body: RebuildReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if body.mode not in ("editable", "exact"):
        raise AppError("mode must be editable or exact", "bad_mode")
    if not el.read_json(ts.work_tdir(t) / "scene.json")["nodes"]:
        raise AppError("measure the design before rebuilding it", "no_model")
    return _job(conn, "template.rebuild", t, {"mode": body.mode})


class AcceptReq(BaseModel):
    stage_id: str
    note: str = ""


@router.post("/templates/{tid}/accept")
def accept(tid: str, body: AcceptReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    st = (t["draft"] or {}).get("staged") or {}
    if st.get("stage_id") != body.stage_id:
        raise conflict("that staged rebuild is no longer the latest one", "stale_stage")
    acc = {"accepted_at": db.now(), "level": st.get("readiness"), "verdict": (st.get("verdict") or {}).get("status"),
           "reproducibility": (st.get("reproducibility") or {}).get("status"), "note": body.note[:500], "stage_id": body.stage_id}
    return _job(conn, "template.save_version", t, {"source": "stage", "stage_id": body.stage_id, "acceptance": acc})


class SaveVersionReq(BaseModel):
    note: str = ""


@router.post("/templates/{tid}/save-version")
def save_version(tid: str, body: SaveVersionReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    created = "edit" if t["role"] == "copy" else "saved_draft"
    return _job(conn, "template.save_version", t, {"source": "workspace", "created_from": created,
                                                   "acceptance": {"saved_at": db.now(), "note": body.note[:500], "kind": created}})


class CopyReq(BaseModel):
    version_id: Optional[str] = None
    name: Optional[str] = None


@router.post("/templates/{tid}/copy")
def copy(tid: str, body: CopyReq, conn=Depends(get_conn)):
    parent = ts.get(conn, tid)
    vid = body.version_id or parent.get("current_version_id")
    if not vid:
        raise AppError("save a version of this template before copying it", "no_version")
    v = ts.version(conn, vid)
    if v["template_id"] != tid:
        raise AppError("that version belongs to another template", "bad_version")
    nid = db.new_id("tp")
    name = (body.name or f"{parent['name']} (copy)")[:120]
    engine_id = el.common().slugify(name, 40) + "-" + nid[-6:]
    pp = dict(parent.get("passport") or {})
    pp["name"] = ts.labeled(name)
    rec = {"id": nid, "engine_id": engine_id, "name": name, "role": "copy", "parent_template_id": tid, "parent_version_id": vid,
           "collection_id": parent.get("collection_id"), "tags": parent.get("tags") or [], "passport": pp,
           "source_asset_id": parent.get("source_asset_id"), "draft": {"step": "copying", "default_copy": (v["summary"].get("defaults") or {}).get("copy", {}),
                                                                       "default_instructions": (v["summary"].get("defaults") or {}).get("instructions", "")},
           "readiness": v["readiness"], "width": parent.get("width"), "height": parent.get("height"), "aspect_ratio": parent.get("aspect_ratio"),
           "medium": parent.get("medium"), "created_at": db.now(), "updated_at": db.now()}
    rec["search_text"] = ts.search_text(rec)
    db.insert(conn, "templates", rec)
    t = ts.get(conn, nid)
    job = _job(conn, "template.copy", t, {"parent_version_id": vid})
    return {"template": ts.public(conn, t, full=True), "job": job}


@router.get("/templates/{tid}/design")
def design(tid: str, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if not t.get("design_variant"):
        raise AppError("this template has no design variant (only copies are edited)", "no_design")
    st = engine.call("variant_state", {"engine_id": t["engine_id"], "variant": t["design_variant"]}, ts.workspace(tid), timeout=120)
    meta = st["meta"]
    return {"head": meta["head"], "revisions": meta["revisions"], "history": meta["history"][-50:], "baseline_revision": meta["baseline_revision"],
            "scene": {k: st["head"].get(k) for k in ("nodes", "tokens", "slots", "locks", "canvas", "constraints", "revision")},
            "edits": (t["draft"] or {}).get("edits", [])[-50:], "unsaved": bool((t["draft"] or {}).get("unsaved"))}


@router.get("/templates/{tid}/head.png")
def head_png(tid: str, rev: int, conn=Depends(get_conn)):
    """The verified render of a copy's design revision (kept from its transaction, or rendered on request)."""
    t = ts.get(conn, tid)
    p = ((t["draft"] or {}).get("head_previews") or {}).get(str(rev))
    if not p:
        if rev == 0:
            pp = el.read_json(ts.work_tdir(t) / "passport.json")
            if pp.get("baseline_render"):
                return file_response(ts.work_tdir(t) / pp["baseline_render"]["path"])
        raise AppError("this revision has not been rendered yet", "missing_file", 404)
    return file_response(p)


@router.post("/templates/{tid}/render-head")
def render_head(tid: str, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if not t.get("design_variant"):
        raise AppError("only copies have a design head to render", "no_design")
    return _job(conn, "template.render_head", t, {}, priority=3)


class CompileReq(BaseModel):
    text: Optional[str] = None
    ops: Optional[list[dict]] = None
    keep: bool = True


@router.post("/templates/{tid}/compile")
def compile_edit(tid: str, body: CompileReq, conn=Depends(get_conn)):
    """Compile a request to typed ops and dry-run it (no render, nothing committed) so its scope can be reviewed."""
    t = ts.get(conn, tid)
    if t["role"] != "copy" or not t.get("design_variant"):
        raise AppError("original templates are read-only; make a copy to edit", "read_only")
    ts.ensure_idle(conn, tid)
    home = ts.workspace(tid)
    st = engine.call("variant_state", {"engine_id": t["engine_id"], "variant": t["design_variant"]}, home, timeout=120)
    comp = {"ops": body.ops, "compiled_by": "direct controls"} if body.ops else commands.compile_request(st["head"], body.text or "")
    patch = {"schema_version": "1.0.0", "base_revision": st["meta"]["head"], "intent": body.text or "inspector edit", "ops": comp["ops"]}
    if body.keep:
        patch["keep"] = "everything_else"
    try:
        dry = engine.call("transact", {"engine_id": t["engine_id"], "variant": t["design_variant"], "patch": patch, "verify": False,
                                       "dry_run": True}, home, timeout=300)
        scope = {"ok": True, "changes": [{k: c.get(k) for k in ("path", "kind", "why", "before", "after")} for c in dry["changes"]][:200],
                 "authorized_paths": dry.get("authorized_paths"), "relaxed": [n for n in dry.get("constraint_notes", []) if n.get("relaxed")],
                 "warnings": (dry.get("validation") or {}).get("warnings", [])[:20]}
    except engine.EngineError as e:
        txn = e.detail or {}
        scope = {"ok": False, "conflicts": ts.json_safe(txn.get("conflicts") or [e.engine])[:20], "message": e.message}
    return ts.json_safe({**comp, "base_revision": st["meta"]["head"], "scope": scope})


class EditReq(BaseModel):
    ops: list[dict]
    base_revision: int
    intent: str = ""
    keep: bool = True


@router.post("/templates/{tid}/edit")
def edit(tid: str, body: EditReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if t["role"] != "copy":
        raise AppError("original templates are read-only; make a copy to edit", "read_only")
    return _job(conn, "template.edit", t, {"ops": body.ops, "base_revision": body.base_revision, "intent": body.intent[:300], "keep": body.keep},
                priority=3)


@router.post("/templates/{tid}/undo")
def undo(tid: str, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    if t["role"] != "copy":
        raise AppError("only copies have edits to undo", "read_only")
    return _job(conn, "template.undo", t, {}, priority=3)


class RestoreReq(BaseModel):
    version_id: str


@router.post("/templates/{tid}/restore")
def restore(tid: str, body: RestoreReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    v = ts.version(conn, body.version_id)
    if v["template_id"] != tid:
        raise AppError("that version belongs to another template", "bad_version")
    return _job(conn, "template.restore", t, {"version_id": v["id"]})


@router.post("/templates/{tid}/archive")
def archive(tid: str, conn=Depends(get_conn)):
    ts.get(conn, tid)
    with db.tx(conn):
        db.update(conn, "templates", tid, {"archived_at": db.now(), "updated_at": db.now()})
    return ts.public(conn, ts.get(conn, tid))


@router.post("/templates/{tid}/unarchive")
def unarchive(tid: str, conn=Depends(get_conn)):
    ts.get(conn, tid)
    with db.tx(conn):
        db.update(conn, "templates", tid, {"archived_at": None, "updated_at": db.now()})
    return ts.public(conn, ts.get(conn, tid))


@router.get("/templates/{tid}/thumb")
def thumb(tid: str, conn=Depends(get_conn)):
    p = ts.thumb_file(conn, ts.get(conn, tid))
    if not p:
        raise AppError("no preview yet", "missing_file", 404)
    return file_response(p)


@router.get("/templates/{tid}/versions/{vid}/thumb")
def version_thumb(tid: str, vid: str, conn=Depends(get_conn)):
    v = ts.version(conn, vid)
    if v["template_id"] != tid:
        raise AppError("that version belongs to another template", "bad_version")
    return file_response(v["thumb_path"])


@router.get("/templates/{tid}/versions/{vid}/bundle")
def version_bundle(tid: str, vid: str, conn=Depends(get_conn)):
    v = ts.version(conn, vid)
    t = ts.get(conn, tid)
    if v["template_id"] != tid:
        raise AppError("that version belongs to another template", "bad_version")
    name = f"{el.common().slugify(t['name'], 40)}-v{v['number']}.dnab"
    return file_response(v["bundle_path"], name, inline=False)


@router.post("/templates/import")
async def import_bundle(file: UploadFile = File(...), conn=Depends(get_conn)):
    data = await file.read(config.get().max_upload_bytes * 8 + 1)
    if len(data) > config.get().max_upload_bytes * 8:
        raise AppError("the bundle is too large", "too_large", 413)
    if not data.startswith(b"PK"):
        raise AppError("that is not a Design DNA bundle (.dnab)", "not_a_bundle", 415)
    nid = db.new_id("tp")
    inbox = ts.root(nid) / "import"
    inbox.mkdir(parents=True, exist_ok=True)
    p = inbox / "upload.dnab"
    p.write_bytes(data)
    import zipfile

    try:
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            if "manifest.json" not in names:
                raise AppError("the archive has no manifest.json: not a Design DNA bundle", "not_a_bundle", 415)
            for n in names:
                if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/") or ":" in n:
                    raise AppError(f"the bundle contains an unsafe path ({n[:80]!r}); it was rejected", "unsafe_bundle", 422)
    except zipfile.BadZipFile:
        shutil.rmtree(ts.root(nid), ignore_errors=True)
        raise AppError("the file is not a valid ZIP archive", "not_a_bundle", 415)
    except AppError:
        shutil.rmtree(ts.root(nid), ignore_errors=True)
        raise
    rec = {"id": nid, "engine_id": "importing", "name": intake.safe_name(file.filename, "Imported template").removesuffix(".dnab")[:120],
           "role": "original", "draft": {"step": "importing"}, "passport": {}, "created_at": db.now(), "updated_at": db.now()}
    db.insert(conn, "templates", rec)
    t = ts.get(conn, nid)
    job = _job(conn, "template.import", t, {"bundle": str(p)})
    return {"template": ts.public(conn, t, full=True), "job": job}


class MigrationReq(BaseModel):
    version_id: Optional[str] = None


@router.post("/templates/{tid}/migrations")
def migration_preview(tid: str, body: MigrationReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    vid = body.version_id or t.get("current_version_id")
    if not vid:
        raise AppError("the template has no saved version to migrate", "no_version")
    mid = db.new_id("mg")
    db.insert(conn, "migrations", {"id": mid, "template_id": tid, "version_id": vid, "status": "previewing", "created_at": db.now(),
                                   "updated_at": db.now()})
    return {"migration_id": mid, "job": _job(conn, "template.migrate_preview", t, {"version_id": vid, "migration_id": mid})}


@router.get("/templates/{tid}/migrations")
def migrations(tid: str, conn=Depends(get_conn)):
    return db.all_(conn, "SELECT * FROM migrations WHERE template_id = ? ORDER BY created_at DESC", (tid,))


class ConfirmReq(BaseModel):
    preview_id: str


@router.post("/templates/{tid}/migrations/{mid}/confirm")
def migration_confirm(tid: str, mid: str, body: ConfirmReq, conn=Depends(get_conn)):
    t = ts.get(conn, tid)
    m = db.one(conn, "SELECT * FROM migrations WHERE id = ? AND template_id = ?", (mid, tid))
    if not m:
        raise AppError("migration not found", "not_found", 404)
    if m["preview_id"] != body.preview_id:
        raise conflict("confirm the preview you reviewed: that preview id does not belong to this migration", "preview_mismatch")
    return _job(conn, "template.migrate_confirm", t, {"migration_id": mid, "preview_id": body.preview_id})


@router.get("/templates/{tid}/migrations/{mid}/files/{path:path}")
def migration_files(tid: str, mid: str, path: str, conn=Depends(get_conn)):
    m = db.one(conn, "SELECT * FROM migrations WHERE id = ? AND template_id = ?", (mid, tid))
    if not m:
        raise AppError("migration not found", "not_found", 404)
    v = ts.version(conn, m["version_id"])
    return file_response(under(ts.root(tid) / "migrations" / mid / "home" / "templates" / v["engine_id"], path))


@router.get("/collections")
def collections(conn=Depends(get_conn)):
    return db.all_(conn, "SELECT c.*, (SELECT COUNT(*) FROM templates t WHERE t.collection_id = c.id AND t.archived_at IS NULL) AS templates "
                         "FROM collections c ORDER BY name COLLATE NOCASE")


class CollectionReq(BaseModel):
    name: str


@router.post("/collections")
def create_collection(body: CollectionReq, conn=Depends(get_conn)):
    name = body.name.strip()[:80]
    if not name:
        raise AppError("a collection needs a name", "bad_name")
    if db.one(conn, "SELECT id FROM collections WHERE name = ?", (name,)):
        raise conflict("a collection with that name exists", "duplicate_name")
    cid = db.new_id("cl")
    db.insert(conn, "collections", {"id": cid, "name": name, "created_at": db.now()})
    return db.one(conn, "SELECT * FROM collections WHERE id = ?", (cid,))
