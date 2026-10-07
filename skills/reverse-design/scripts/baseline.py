"""Baselines: reconstruct + approve + pin, reproducibility checks, and explicit renderer migration.

reconstruct  renders the template model, compares it with the reference, and — when this model content has no
             approved baseline yet — approves the render and pins the renderer environment (passport.render_pin).
             Re-running on an unchanged model compares the new render with the approved one (reproducibility).
migrate      renders under the CURRENT environment even if it drifted, compares with the approved baseline and the
             reference, and stores an immutable preview record (preview id, candidate hash, base revision + model hash,
             old pin, new renderer fingerprint). Nothing else changes. confirm names that preview: the reviewed candidate
             itself is adopted (never a second render), and only while the model, the old pin, the candidate file and
             the live renderer fingerprint still match the record; otherwise a new preview is required. The migration
             (old pin, new pin, pixel differences, preview id) is recorded. Old baselines are never removed.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from common import DnaError, model_hash, now, read_json, sha256_bytes, sha256_file, template_dir, write_immutable, write_json
from compare_render import compare, decode, pixel_metrics
from index_templates import rebuild
from render_static import current_environment, render
from renderer_env import fingerprint, make_pin, requested_channel
from validate_model import editability_report


def _stamp():
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _out(tdir, rev, tag=None) -> Path:
    first = Path(tdir) / "baseline" / f"rev-{rev:04d}"
    if tag is None and not first.exists():
        return first
    return Path(tdir) / "baseline" / f"rev-{rev:04d}-{tag or 'run'}-{_stamp()}"


def _against_reference(tdir, scene, r, out, mode):
    reuse = any(a["source"] == "reference_crop" for a in scene["assets"].values())
    profile = "exact_pixels" if mode == "exact" else "editable_close"
    edit_rep = editability_report(scene)
    how = "copying" if edit_rep["reference_background_shortcut"] else ("mixed" if reuse else "editable_rendering")
    rep = compare(Path(tdir) / scene["source"]["canonical"]["path"], r["png"], out / "compare", scene, r, profile, how, edit_rep)
    return rep, profile, how, edit_rep


def _readiness(scene, profile, status, edit_rep, passport) -> str:
    """Promotion needs a passing verdict AND a complete scan AND independently editable slots; otherwise partial."""
    reasons = []
    if status != "pass":
        reasons.append(f"{profile} verdict: {status}")
    if scene["scan"]["state"] != "complete":
        reasons.append("scan coverage incomplete")
    if edit_rep["overall"] != "pass":
        reasons.append(f"editability: {edit_rep['overall']}" + (" (pixel identity achieved by copying)" if edit_rep.get("reference_background_shortcut") else ""))
    if reasons:
        passport["unresolved"] = sorted(set(passport.get("unresolved", [])) | {f"not promoted: {r}" for r in reasons})
        return "partial_baseline"
    return "exact_pixels" if profile == "exact_pixels" else "editable_close"


def _approval(tdir, scene, r):
    return {"path": str(Path(r["png"]).relative_to(tdir)).replace("\\", "/"), "sha256": r["png_sha256"],
            "revision": scene["revision"], "scene_sha256": model_hash(scene), "approved_at": now(),
            "renderer": f"{r['render_profile']['channel']} {r['render_profile']['browser_version']}"}


def reconstruct(tid, mode="editable") -> dict:
    tdir = template_dir(tid)
    scene, passport = read_json(tdir / "scene.json"), read_json(tdir / "passport.json")
    approved = passport.get("baseline_render")
    same_model = bool(approved) and approved.get("scene_sha256") == model_hash(scene)
    out = _out(tdir, scene["revision"], "rerun" if same_model else None)
    r = render(scene, tdir, out, isolate=True, formats=("png", "svg"), name="baseline")
    rep, profile, how, edit_rep = _against_reference(tdir, scene, r, out, mode)
    st = rep["overall"]["status"]
    result = {"render": r["png"], "svg": r.get("svg"), "svg_verification": (r.get("svg_verification") or {}).get("roundtrip_status"),
              "report": str(out / "compare" / "report.json"), "verdict": rep["overall"], "pin_check": r["pin_check"],
              "artifacts": [str(out / "compare" / f) for f in ("side_by_side.png", "overlay_50.png", "diff_heatmap.png")]}
    if same_model:
        pm = pixel_metrics(decode(r["png"])[0], decode(tdir / approved["path"])[0])
        result["reproduces_approved_baseline"] = {"unequal_pixels": pm["unequal_pixels"], "status": "pass" if pm["unequal_pixels"] == 0 else "fail",
                                                  "approved": approved["path"]}
    else:
        passport["baseline_render"] = _approval(tdir, scene, r)
        passport["render_pin"] = make_pin(r["render_profile"], "baseline approved by reconstruct")
        passport.update(revision=scene["revision"], editability_coverage=edit_rep,
                        baseline_match={"profile": profile, "status": st, "how": how,
                                        "report": str((out / "compare" / "report.json").relative_to(tdir)).replace("\\", "/")})
        passport["readiness"] = _readiness(scene, profile, st, edit_rep, passport)
        result["approved_baseline"] = passport["baseline_render"]
    passport["updated"] = now()
    write_json(tdir / "passport.json", passport)
    rebuild()
    result["readiness"] = passport["readiness"]
    return result


def _rel(tdir, p) -> str:
    return str(Path(p).relative_to(tdir)).replace("\\", "/")


def _digest(obj) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode())


def migration_previews(tdir) -> list[dict]:
    """Every migration preview recorded for a template, oldest first (each one is an immutable file)."""
    out = []
    for f in sorted(Path(tdir).glob("baseline/*/migration-preview.json")):
        p = read_json(f)
        p["record"] = _rel(tdir, f)
        out.append(p)
    return sorted(out, key=lambda p: p["created"])


def migrate_baseline(tid, confirm=False, preview_id=None) -> dict:
    """Preview (default): render under the current environment, compare, and store an immutable preview record.
    confirm: adopt exactly the candidate of the named preview; nothing is re-rendered at confirmation."""
    tdir = template_dir(tid)
    scene, passport = read_json(tdir / "scene.json"), read_json(tdir / "passport.json")
    old_pin, approved = passport.get("render_pin"), passport.get("baseline_render")
    if not old_pin or not approved:
        raise DnaError("template has no pinned, approved baseline; run reconstruct first", "no_baseline")
    if confirm:
        return _confirm_migration(tdir, scene, passport, preview_id)
    out = _out(tdir, scene["revision"], "migration")
    r = render(scene, tdir, out, isolate=True, formats=("png", "svg"), name="baseline", pin_policy="migrate")
    vs_old = compare(tdir / approved["path"], r["png"], out / "vs-approved", None, None, "exact_pixels", "editable_rendering")
    mode = "exact" if passport.get("baseline_match", {}).get("profile") == "exact_pixels" else "editable"
    rep, profile, how, edit_rep = _against_reference(tdir, scene, r, out, mode)
    fp = fingerprint(r["render_profile"])
    preview = {
        "kind": "migration_preview", "template_id": tid, "created": now(),
        "base": {"revision": scene["revision"], "scene_sha256": model_hash(scene)},
        "old_pin": old_pin, "old_pin_sha256": _digest(old_pin), "approved_baseline": approved,
        "candidate": {"path": _rel(tdir, r["png"]), "sha256": r["png_sha256"], "svg": _rel(tdir, r["svg"]) if r.get("svg") else None},
        "new_fingerprint": fp, "new_fingerprint_sha256": _digest(fp), "render_profile": r["render_profile"],
        "pin_check": r["pin_check"],
        "vs_approved_baseline": {k: vs_old["checks"]["exact_pixels"][k] for k in ("unequal_pixels", "unequal_fraction", "max_channel_error")},
        "vs_reference": {"profile": profile, "status": rep["overall"]["status"], "how": how, "verdict": rep["overall"],
                         "report": _rel(tdir, out / "compare" / "report.json")},
        "artifacts": _rel(tdir, out)}
    preview["preview_id"] = "mp-" + _digest({k: preview[k] for k in ("template_id", "created", "base", "old_pin_sha256", "candidate",
                                                                     "new_fingerprint_sha256")})[:16]
    write_immutable(out / "migration-preview.json", json.dumps(preview, indent=2, ensure_ascii=False, default=str).encode())
    report = {"status": "migration_required" if r["pin_check"]["hard"] else "no_hard_drift", "preview_id": preview["preview_id"],
              "pin_check": r["pin_check"], "candidate": r["png"], "candidate_sha256": r["png_sha256"],
              "vs_approved_baseline": preview["vs_approved_baseline"], "vs_reference": rep["overall"], "artifacts": str(out),
              "preview_record": _rel(tdir, out / "migration-preview.json"),
              "next": f"review {out}, then: migrate-baseline \"{passport['name']}\" confirm preview={preview['preview_id']}"}
    return report


def _stale(preview_id, reason, **detail):
    return DnaError(f"migration preview {preview_id} no longer describes this template: {reason}; nothing was changed",
                    "stale_preview", dict(detail, fix="run migrate-baseline again (a new preview), review it, then confirm that preview"))


def _confirm_migration(tdir, scene, passport, preview_id) -> dict:
    previews = migration_previews(tdir)
    if not preview_id:
        latest = previews[-1]["preview_id"] if previews else None
        raise DnaError("confirmation must name the reviewed preview; a second, unseen render is never adopted", "preview_required",
                       {"latest_preview": latest, "fix": f'migrate-baseline "{passport["name"]}" confirm preview=<preview id>'})
    p = next((x for x in previews if x["preview_id"] == preview_id), None)
    if p is None:
        raise DnaError(f"no migration preview {preview_id!r} for this template", "unknown_preview",
                       {"previews": [x["preview_id"] for x in previews]})
    if any(m.get("preview_id") == preview_id for m in passport.get("render_migrations", [])):
        raise DnaError(f"preview {preview_id} was already confirmed", "preview_already_confirmed")
    if model_hash(scene) != p["base"]["scene_sha256"] or scene["revision"] != p["base"]["revision"]:
        raise _stale(preview_id, "the template model changed since the preview", base=p["base"], current_revision=scene["revision"])
    if _digest(passport.get("render_pin")) != p["old_pin_sha256"] or passport.get("baseline_render") != p["approved_baseline"]:
        raise _stale(preview_id, "the pinned renderer or approved baseline changed since the preview")
    cand = tdir / p["candidate"]["path"]
    if not cand.exists() or sha256_file(cand) != p["candidate"]["sha256"]:
        raise DnaError(f"the reviewed candidate of {preview_id} is missing or altered; it cannot be adopted", "changed_candidate",
                       {"expected_sha256": p["candidate"]["sha256"], "fix": "run a new migration preview"})
    live = fingerprint(current_environment(scene, tdir, requested_channel(passport.get("render_pin"))))
    if _digest(live) != p["new_fingerprint_sha256"]:
        diff = [k for k in sorted(set(live) | set(p["new_fingerprint"])) if live.get(k) != p["new_fingerprint"].get(k)]
        raise _stale(preview_id, "the renderer environment differs from the one that produced the reviewed candidate", changed=diff)
    old_pin, approved = passport["render_pin"], passport["baseline_render"]
    passport.setdefault("render_migrations", []).append({
        "at": now(), "preview_id": preview_id, "preview_record": p["record"],
        "from": {k: old_pin.get(k) for k in ("channel", "browser_version", "pinned_at")},
        "to": {k: p["render_profile"].get(k) for k in ("channel", "browser_version")}, "hard_differences": p["pin_check"]["hard"],
        "previous_pin": old_pin, "previous_baseline": approved["path"], "previous_baseline_sha256": approved["sha256"],
        "candidate_sha256": p["candidate"]["sha256"], "vs_previous_baseline": p["vs_approved_baseline"], "evidence": p["artifacts"]})
    passport["render_pin"] = make_pin(p["render_profile"], f"baseline migration confirmed ({preview_id})")
    passport["baseline_render"] = {"path": p["candidate"]["path"], "sha256": p["candidate"]["sha256"], "revision": scene["revision"],
                                   "scene_sha256": p["base"]["scene_sha256"], "approved_at": now(),
                                   "renderer": f"{p['render_profile']['channel']} {p['render_profile']['browser_version']}",
                                   "migration_preview": preview_id}
    vr = p["vs_reference"]
    passport["baseline_match"] = {"profile": vr["profile"], "status": vr["status"], "how": vr["how"], "report": vr["report"]}
    passport["readiness"] = _readiness(scene, vr["profile"], vr["status"], editability_report(scene), passport)
    passport["updated"] = now()
    write_json(tdir / "passport.json", passport)
    rebuild()
    return {"status": "migrated", "preview_id": preview_id, "adopted": p["candidate"], "previous_baseline": approved["path"],
            "vs_approved_baseline": p["vs_approved_baseline"], "readiness": passport["readiness"]}
