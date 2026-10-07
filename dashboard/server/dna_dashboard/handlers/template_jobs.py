"""Template jobs: analysis proposals, assisted measurement, staged rebuild, versions, copies, edits, restore, import, migration.

Each runs under the template's lock (one step at a time per workspace) and talks to the engine only through engine.py.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import db, engine
from .. import enginelib as el
from .. import templates_svc as ts
from ..errors import AppError
from ..providers import for_capability, tracked
from ..scan_build import Builder
from ..worker import handler

SUGGEST = {"character": "character_theme", "usage": "usage_context"}


def _tpl(ctx):
    return ts.get(ctx.conn, ctx.input["template_id"])


def _update_draft(ctx, tid, **changes):
    with db.tx(ctx.conn):
        t = ts.get(ctx.conn, tid)
        d = dict(t["draft"] or {})
        d.update(changes)
        db.update(ctx.conn, "templates", tid, {"draft": d, "draft_revision": t["draft_revision"] + 1, "updated_at": db.now()})


@handler("template.analyze")
def analyze(ctx):
    t = _tpl(ctx)
    png = (ts.work_tdir(t) / "source" / "canonical.png").read_bytes()
    p = t["passport"] or {}
    brief = {k: (p.get(k) or {}).get("value") for k in ts.PASSPORT_KEYS if (p.get(k) or {}).get("status") in ("user_supplied", "user_confirmed")}
    prov = for_capability("analysis", ctx.input.get("provider"))
    ctx.stage("provider", f"asking {prov.label} for element proposals (a paid request)")
    with tracked(prov.name, "analysis", getattr(prov, "model", None), ctx.job["id"]) as tr:
        data, meta = prov.analyze(png, brief, tr)
    ctx.stage("proposals", f"{len(data.get('elements', []))} element proposals received")
    t = _tpl(ctx)
    d = t["draft"] or {}
    props = []
    for i, e in enumerate(data.get("elements", [])):
        if not e.get("bbox"):
            continue
        props.append(dict(e, key=el.common().slugify(e.get("key") or f"e{i + 1}", 30) or f"e{i + 1}", status="proposed",
                          source="mock" if meta.get("mock") else "ai"))
    keep_user = any(e.get("source") == "user" or e.get("edited") for e in d.get("elements", []))
    changes = {"analysis": data, "analysis_meta": meta, "proposals": props}
    if not keep_user:
        changes["elements"] = props
    changes["step"] = "scan"
    _update_draft(ctx, t["id"], **changes)
    with db.tx(ctx.conn):
        t = ts.get(ctx.conn, t["id"])
        pp = dict(t["passport"] or {})
        com = data.get("communication") or {}
        sugg = {"character": data.get("character_theme"), "usage": data.get("usage_context"), "goal": com.get("goal"),
                "literal_message": com.get("literal_message"), "takeaway": com.get("takeaway"),
                "mechanism": " -> ".join((com.get("mechanisms") or [{}])[0].get("chain", [])) if com.get("mechanisms") else None}
        for k, v in sugg.items():
            if v and not (pp.get(k) or {}).get("value"):
                pp[k] = {"value": v, "status": "suggested", "source": meta.get("provider"), "mock": bool(meta.get("mock"))}
        if not (pp.get("name") or {}).get("value") and data.get("suggested_name"):
            pp["name"] = {"value": data["suggested_name"], "status": "suggested"}
        db.update(ctx.conn, "templates", t["id"], {"passport": pp, "search_text": ts.search_text(dict(t, passport=pp))})
    ts.write_engine_passport(ts.get(ctx.conn, t["id"]))
    return "completed", {"proposals": len(props), "kept_user_elements": keep_user, "provider": meta}


@handler("template.measure")
def measure(ctx):
    t = _tpl(ctx)
    home = ts.workspace(t["id"])
    ctx.stage("prepare", "loading the reviewed elements")
    res = Builder(ctx, home, t["engine_id"], t["draft"] or {}, t["passport"] or {}).run()
    ctx.stage("annotate", "writing the annotated scan and report")
    engine.call("annotate", {"engine_id": t["engine_id"]}, home, cancel=ctx.cancelled)
    ctx.stage("validate", "validating the model")
    val = engine.call("validate", {"engine_id": t["engine_id"]}, home, cancel=ctx.cancelled)
    tdir = ts.work_tdir(t)
    pp = el.read_json(tdir / "passport.json")
    scene = el.read_json(tdir / "scene.json")
    pp["slots"] = [s["id"] for s in scene["slots"]]
    pp["unresolved"] = sorted(set(res["warnings"] + [f"not measured: {k}" for k in res["failures"]] +
                                  ([] if scene["scan"]["state"] == "complete" else ["scan review not confirmed or incomplete"])))
    if scene["scan"]["state"] == "complete" and val["valid"] and not pp.get("baseline_render"):
        pp["readiness"] = "scanned"
    el.write_json(tdir / "passport.json", pp)
    ts.write_engine_passport(t)
    summary = {"valid": val["valid"], "errors": val["errors"][:40], "warnings": val["warnings"][:40],
               "editability": val.get("editability"), "passport": val.get("passport"), "unsupported": val.get("unsupported")}
    _update_draft(ctx, t["id"], measure=res, validation=summary, step="rules")
    with db.tx(ctx.conn):
        db.update(ctx.conn, "templates", t["id"], {"readiness": pp["readiness"] if not t.get("current_version_id") else t["readiness"]})
    status = "needs_review" if res["failures"] or not val["valid"] else "completed"
    return status, {"measure": res, "validation": summary}


def _stage_home(t, stage_id) -> Path:
    return ts.root(t["id"]) / "staging" / stage_id / "home"


@handler("template.rebuild")
def rebuild(ctx):
    """Reconstruct in a staged copy of the workspace. The engine may approve a baseline there; nothing saved changes."""
    t = _tpl(ctx)
    mode = ctx.input.get("mode", "editable")
    stage_id = db.new_id("st")
    home = _stage_home(t, stage_id)
    ctx.stage("stage", "copying the draft into a staging store")
    shutil.copytree(ts.work_tdir(t), home / "templates" / t["engine_id"], ignore=shutil.ignore_patterns(".render", "renders", "exports"))
    ctx.stage("reconstruct", f"rendering the unchanged design ({mode}) and comparing it with the reference")
    rec = engine.call("reconstruct", {"engine_id": t["engine_id"], "mode": mode}, home, cancel=ctx.cancelled)
    ctx.stage("reproduce", "re-rendering in a fresh process to check reproducibility")
    rerun = engine.call("reconstruct", {"engine_id": t["engine_id"], "mode": mode}, home, cancel=ctx.cancelled)
    repro = rerun.get("reproduces_approved_baseline") or {"status": "unknown", "note": "no approved baseline to reproduce"}
    tdir = home / "templates" / t["engine_id"]
    summ = ts.summarize(tdir)
    rel = lambda p: str(Path(p).resolve().relative_to(tdir.resolve())) if p else None
    staged = {"stage_id": stage_id, "mode": mode, "readiness": rec["readiness"], "verdict": rec["verdict"], "pin_check": rec["pin_check"],
              "baseline": rel(rec["render"]), "artifacts": {Path(a).stem: rel(a) for a in rec["artifacts"]},
              "report": rel(rec["report"]), "svg_roundtrip": rec.get("svg_verification"), "reproducibility": repro,
              "approved_here": bool(rec.get("approved_baseline")), "summary": summ, "at": db.now()}
    _update_draft(ctx, t["id"], staged=staged, step="rebuild")
    if repro.get("status") == "fail":
        ctx.log(f"fresh-process re-render differs from the staged baseline by {repro.get('unequal_pixels')} px; "
                "kept as evidence, no exact claim", level="warning")
        return "needs_review", {"staged": staged, "reason": "the staged baseline did not reproduce in a fresh process"}
    return "completed", {"staged": staged}


@handler("template.save_version")
def save_version(ctx):
    t = _tpl(ctx)
    src = ctx.input.get("source", "workspace")
    acceptance = ctx.input.get("acceptance")
    if src == "stage":
        st = (t["draft"] or {}).get("staged") or {}
        if st.get("stage_id") != ctx.input.get("stage_id"):
            raise AppError("that staged rebuild is no longer the latest one; review the current rebuild before accepting", "stale_stage")
        home = _stage_home(t, st["stage_id"])
    else:
        home = ts.workspace(t["id"])
    dv = t.get("design_variant")
    head = None
    if dv:
        head = el.read_json(home / "templates" / t["engine_id"] / "variants" / dv / "variant.json")["head"]
    ctx.stage("seal", "exporting and validating an immutable version bundle")
    v = ts.create_version(ctx.conn, t, home, t["engine_id"], ctx.input.get("created_from", "accepted_rebuild" if src == "stage" else "saved_draft"),
                          parent_version_id=t.get("current_version_id"), acceptance=acceptance, design_variant=dv, design_head=head,
                          job_dir=ctx.dir)
    if src == "stage":
        ctx.stage("sync", "the accepted staged rebuild becomes the workspace state")
        w = ts.work_tdir(t)
        parked = w.with_name(w.name + f".before-{v['id']}")
        w.rename(parked)
        shutil.copytree(home / "templates" / t["engine_id"], w)
        shutil.rmtree(parked, ignore_errors=True)
    _update_draft(ctx, t["id"], step="saved", saved_version=v["id"])
    return "completed", {"version_id": v["id"], "number": v["number"], "readiness": v["readiness"]}


@handler("template.copy")
def copy(ctx):
    t = _tpl(ctx)
    pv = ts.version(ctx.conn, ctx.input["parent_version_id"])
    home = ts.workspace(t["id"])
    ctx.stage("import", f"importing version {pv['number']} of the original as a new identity")
    imp = engine.call("import_bundle", {"bundle": pv["bundle_path"], "as_id": t["engine_id"]}, home, cancel=ctx.cancelled)
    dv = pv.get("design_variant")
    if not dv:
        ctx.stage("variant", "opening a design variant for this copy's edits")
        dv = engine.call("new_variant", {"engine_id": t["engine_id"], "task": "template copy edits", "name": "design"}, home)["id"]
    with db.tx(ctx.conn):
        db.update(ctx.conn, "templates", t["id"], {"design_variant": dv})
    t = ts.get(ctx.conn, t["id"])
    check = {"bundle_valid": imp["status"] == "imported"}
    pp = el.read_json(ts.work_tdir(t) / "passport.json")
    inherited = pp.get("baseline_render")
    if inherited:
        # The new identity changes the model's content hash, so the engine approves a baseline for the copy's model.
        # The copy inherits the parent's claims only if that render is pixel-identical to the inherited baseline image.
        ctx.stage("verify", "checking that the inherited baseline reproduces here before its claims are inherited")
        rr = engine.call("reconstruct", {"engine_id": t["engine_id"], "mode": "exact" if (pp.get("baseline_match") or {}).get("profile") == "exact_pixels"
                                         else "editable"}, home, cancel=ctx.cancelled)
        new = (rr.get("approved_baseline") or {}).get("path") or inherited["path"]
        diff = el.pixel_diff(ts.work_tdir(t) / inherited["path"], ts.work_tdir(t) / new)
        check["reproduces_approved_baseline"] = dict(diff, inherited=inherited["path"], rendered=new)
        check["readiness_after_check"] = rr.get("readiness")
    head = el.read_json(ts.work_tdir(t) / "variants" / dv / "variant.json")["head"]
    v = ts.create_version(ctx.conn, t, home, t["engine_id"], "copy", parent_version_id=None, design_variant=dv, design_head=head,
                          acceptance={"inherited_from": pv["id"], "checks": check, "at": db.now()}, job_dir=ctx.dir)
    repro = (check.get("reproduces_approved_baseline") or {}).get("status")
    if repro == "fail":
        s = dict(v["summary"])
        s["eligibility"]["adapt"]["eligible"] = False
        s["eligibility"]["adapt"]["reasons"].append("the inherited baseline did not reproduce in this environment")
        with db.tx(ctx.conn):
            db.update(ctx.conn, "template_versions", v["id"], {"summary": s})
    _update_draft(ctx, t["id"], step="edit", copy_check=check)
    return ("needs_review" if repro == "fail" else "completed"), {"version_id": v["id"], "checks": check}


def _materialise_files(ctx, ops):
    """Replace ops reference asset ids; the engine needs a file path inside this job's folder."""
    from ..intake import get as get_asset, original_file

    out = []
    for op in ops:
        op = dict(op)
        if op.get("op") == "replace" and op.get("asset_id"):
            a = get_asset(ctx.conn, op.pop("asset_id"))
            dst = ctx.dir / "inputs" / f"{a['sha256'][:16]}{a['ext']}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original_file(a), dst)
            op["file"] = str(dst)
        if op.get("op") == "adapt" and op.get("font_sha256"):
            f = next((x for x in el.font_library() if x["sha256"] == op.pop("font_sha256")), None)
            if not f:
                raise AppError("the selected font is no longer in the font library", "missing_font")
            op["font"] = f["path"]
        out.append(op)
    return out


@handler("template.edit")
def edit(ctx):
    t = _tpl(ctx)
    if t["role"] != "copy" or not t.get("design_variant"):
        raise AppError("original templates are read-only; make a copy to edit", "read_only")
    home = ts.workspace(t["id"])
    ops = _materialise_files(ctx, ctx.input["ops"])
    patch = {"schema_version": "1.0.0", "base_revision": ctx.input["base_revision"], "intent": ctx.input.get("intent") or "dashboard edit",
             "ops": ops}
    if ctx.input.get("keep", True):
        patch["keep"] = "everything_else"
    ctx.stage("transaction", "validating, rendering and verifying the edit in the pinned renderer")
    txn = engine.call("transact", {"engine_id": t["engine_id"], "variant": t["design_variant"], "patch": patch}, home, cancel=ctx.cancelled)
    v = txn.get("verification") or {}
    vis = (v.get("vs_approved_baseline") or {}).get("visual_changes") or v.get("visual_changes") or {}
    rec = {"revision": txn["revision"], "intent": patch["intent"], "ops": ctx.input["ops"], "changes": [
        {k: c.get(k) for k in ("path", "kind", "why")} for c in txn["changes"]][:200], "verification": v.get("status"),
        "outside_influence": vis.get("outside_influence"), "relaxed": [n for n in txn.get("constraint_notes", []) if n.get("relaxed")],
        "at": db.now()}
    d = (ts.get(ctx.conn, t["id"])["draft"] or {})
    previews = dict(d.get("head_previews") or {})
    cand = (v.get("renders") or {}).get("candidate")
    if cand and Path(cand).exists():  # the verified render of this revision, kept for the editor
        dst = ts.root(t["id"]) / "head-previews" / f"rev-{txn['revision']:04d}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cand, dst)
        previews[str(txn["revision"])] = str(dst)
    _update_draft(ctx, t["id"], edits=(d.get("edits") or []) + [rec], unsaved=True, head_previews=previews)
    return "completed", {"transaction": rec}


@handler("template.render_head")
def render_head(ctx):
    """Render the copy's current design head in the pinned renderer (nothing is committed)."""
    t = _tpl(ctx)
    home = ts.workspace(t["id"])
    st = engine.call("variant_state", {"engine_id": t["engine_id"], "variant": t["design_variant"]}, home)
    head = st["meta"]["head"]
    ctx.stage("render", f"rendering revision {head}")
    res = engine.call("preview", {"engine_id": t["engine_id"], "variant": t["design_variant"], "ops": [], "out": str(ctx.dir / "head")},
                      home, cancel=ctx.cancelled)
    dst = ts.root(t["id"]) / "head-previews" / f"rev-{head:04d}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(res["png"], dst)
    d = ts.get(ctx.conn, t["id"])["draft"] or {}
    _update_draft(ctx, t["id"], head_previews=dict(d.get("head_previews") or {}, **{str(head): str(dst)}))
    return "completed", {"revision": head}


@handler("template.undo")
def undo(ctx):
    t = _tpl(ctx)
    res = engine.call("undo", {"engine_id": t["engine_id"], "variant": t["design_variant"]}, ts.workspace(t["id"]))
    d = (ts.get(ctx.conn, t["id"])["draft"] or {})
    _update_draft(ctx, t["id"], edits=(d.get("edits") or []) + [{"undo_to": res["head"], "at": db.now()}], unsaved=True)
    return "completed", res


@handler("template.restore")
def restore(ctx):
    """Restoring an old version makes a NEW head version with the same content; history is never rewritten."""
    t = _tpl(ctx)
    old = ts.version(ctx.conn, ctx.input["version_id"])
    home = ts.workspace(t["id"])
    ctx.stage("reset", f"loading version {old['number']} into the workspace")
    parked = home.with_name(f"workspace.before-restore-{ctx.job['id']}")
    home.rename(parked)
    try:
        engine.call("import_bundle", {"bundle": old["bundle_path"]}, home, cancel=ctx.cancelled)
    except Exception:
        shutil.rmtree(home, ignore_errors=True)
        parked.rename(home)
        raise
    shutil.rmtree(parked, ignore_errors=True)
    v = ts.create_version(ctx.conn, t, home, t["engine_id"], "restore", parent_version_id=old["id"], design_variant=old["design_variant"],
                          design_head=old["design_head"], acceptance={"restored_from": old["id"], "number": old["number"], "at": db.now()},
                          job_dir=ctx.dir)
    d = ts.get(ctx.conn, t["id"])["draft"] or {}
    _update_draft(ctx, t["id"], unsaved=False, edits=(d.get("edits") or []) + [{"restored_version": old["number"], "new_version": v["number"], "at": db.now()}])
    return "completed", {"version_id": v["id"], "number": v["number"], "restored_from": old["number"]}


@handler("template.import")
def import_bundle(ctx):
    t = _tpl(ctx)
    home = ts.workspace(t["id"])
    ctx.stage("validate", "validating the bundle (hashes, paths, model, baseline, revision chains)")
    val = engine.call("validate_bundle", {"bundle": ctx.input["bundle"]}, home)
    if not val["valid"]:
        _update_draft(ctx, t["id"], import_error={"errors": val["errors"][:30]})
        with db.tx(ctx.conn):
            db.update(ctx.conn, "templates", t["id"], {"archived_at": db.now()})
        raise AppError("the bundle failed validation; nothing was imported", "invalid_bundle", 422, {"errors": val["errors"][:30]})
    ctx.stage("import", "importing into a fresh workspace")
    imp = engine.call("import_bundle", {"bundle": ctx.input["bundle"]}, home)
    eid = imp["template_id"]
    tdir = home / "templates" / eid
    pp = el.read_json(tdir / "passport.json")
    scene = el.read_json(tdir / "scene.json")
    W, H = int(scene["canvas"]["width"]), int(scene["canvas"]["height"])
    import math

    g = math.gcd(W, H)
    passport = {"name": {"value": pp["name"], "status": pp.get("name_status", "user_supplied")}}
    for k in ts.ENGINE_PASSPORT_KEYS:
        if isinstance(pp.get(k), dict):
            passport[k] = {"value": pp[k].get("value"), "status": pp[k].get("status")}
    with db.tx(ctx.conn):
        db.update(ctx.conn, "templates", t["id"], {"engine_id": eid, "name": pp["name"], "passport": passport, "readiness": pp["readiness"],
                                                   "width": W, "height": H, "aspect_ratio": f"{W // g}:{H // g}",
                                                   "search_text": ts.search_text(dict(t, name=pp["name"], passport=passport))})
    t = ts.get(ctx.conn, t["id"])
    dv = next(iter(sorted(val.get("variants") or {})), None) if ctx.input.get("design_variant_from_bundle") else None
    v = ts.create_version(ctx.conn, t, home, eid, "import", acceptance={"bundle": Path(ctx.input["bundle"]).name,
                                                                        "validated": True, "at": db.now()}, design_variant=dv, job_dir=ctx.dir)
    _update_draft(ctx, t["id"], step="saved", imported={"bundle": Path(ctx.input["bundle"]).name, "files": val["files"]})
    return "completed", {"version_id": v["id"], "engine_id": eid, "readiness": v["readiness"]}


def _migration_home(t, mid) -> Path:
    return ts.root(t["id"]) / "migrations" / mid / "home"


@handler("template.migrate_preview")
def migrate_preview(ctx):
    t = _tpl(ctx)
    v = ts.version(ctx.conn, ctx.input["version_id"])
    mid = ctx.input["migration_id"]
    home = _migration_home(t, mid)
    ctx.stage("import", f"loading version {v['number']}")
    engine.call("import_bundle", {"bundle": v["bundle_path"]}, home)
    ctx.stage("preview", "rendering under the current renderer and comparing with the approved baseline")
    rep = engine.call("migrate_preview", {"engine_id": v["engine_id"]}, home, cancel=ctx.cancelled)
    with db.tx(ctx.conn):
        db.update(ctx.conn, "migrations", mid, {"preview_id": rep["preview_id"], "status": "previewed", "data": rep, "updated_at": db.now()})
    return "completed", {"migration_id": mid, "preview_id": rep["preview_id"], "status": rep["status"],
                         "vs_approved_baseline": rep["vs_approved_baseline"]}


@handler("template.migrate_confirm")
def migrate_confirm(ctx):
    t = _tpl(ctx)
    m = db.one(ctx.conn, "SELECT * FROM migrations WHERE id = ?", (ctx.input["migration_id"],))
    v = ts.version(ctx.conn, m["version_id"])
    if t.get("current_version_id") != v["id"]:
        raise AppError("the template has a newer version than the one this migration previewed; preview again", "stale_preview")
    home = _migration_home(t, m["id"])
    ctx.stage("confirm", f"adopting the reviewed candidate of preview {m['preview_id']}")
    res = engine.call("migrate_confirm", {"engine_id": v["engine_id"], "preview_id": ctx.input["preview_id"]}, home)
    nv = ts.create_version(ctx.conn, t, home, v["engine_id"], "migration", parent_version_id=v["id"], design_variant=v["design_variant"],
                           design_head=v["design_head"], acceptance={"migration": m["id"], "preview_id": ctx.input["preview_id"],
                                                                     "at": db.now()}, job_dir=ctx.dir)
    with db.tx(ctx.conn):
        db.update(ctx.conn, "migrations", m["id"], {"status": "confirmed", "data": dict(m["data"] or {}, confirmed=res), "updated_at": db.now()})
    return "completed", {"version_id": nv["id"], "migrated": res}
