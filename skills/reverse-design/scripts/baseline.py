"""Baselines: reconstruct + approve + pin, reproducibility checks, and explicit renderer migration.

reconstruct  renders the template model, compares it with the reference, and — when this model content has no
             approved baseline yet — approves the render and pins the renderer environment (passport.render_pin).
             Re-running on an unchanged model compares the new render with the approved one (reproducibility).
migrate      renders under the CURRENT environment even if it drifted, compares with the approved baseline and the
             reference, and reports. Nothing changes unless confirm=True; then the new pin + baseline are adopted
             and the migration (old pin, new pin, pixel differences) is recorded. Old baselines are never removed.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from common import DnaError, model_hash, now, read_json, template_dir, write_json
from compare_render import compare, decode, diff_where, pixel_metrics
from index_templates import rebuild
from render_static import render
from renderer_env import make_pin
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
        a, b = decode(tdir / approved["path"])[0], decode(r["png"])[0]
        pm = pixel_metrics(b, a)
        result["reproduces_approved_baseline"] = {"unequal_pixels": pm["unequal_pixels"], "status": "pass" if pm["unequal_pixels"] == 0 else "fail",
                                                  "approved": approved["path"], "where": diff_where(a, b) if pm["unequal_pixels"] else ""}
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


def migrate_baseline(tid, confirm=False) -> dict:
    tdir = template_dir(tid)
    scene, passport = read_json(tdir / "scene.json"), read_json(tdir / "passport.json")
    old_pin, approved = passport.get("render_pin"), passport.get("baseline_render")
    if not old_pin or not approved:
        raise DnaError("template has no pinned, approved baseline; run reconstruct first", "no_baseline")
    out = _out(tdir, scene["revision"], "migration")
    r = render(scene, tdir, out, isolate=True, formats=("png", "svg"), name="baseline", pin_policy="migrate")
    vs_old = compare(tdir / approved["path"], r["png"], out / "vs-approved", None, None, "exact_pixels", "editable_rendering")
    mode = "exact" if passport.get("baseline_match", {}).get("profile") == "exact_pixels" else "editable"
    rep, profile, how, edit_rep = _against_reference(tdir, scene, r, out, mode)
    report = {"pin_check": r["pin_check"], "candidate": r["png"],
              "vs_approved_baseline": {k: vs_old["checks"]["exact_pixels"][k] for k in ("unequal_pixels", "unequal_fraction", "max_channel_error")},
              "vs_reference": rep["overall"], "artifacts": str(out)}
    if not confirm:
        report["status"] = "migration_required" if r["pin_check"]["hard"] else "no_hard_drift"
        report["next"] = f"review {out}, then: migrate-baseline \"{passport['name']}\" confirm"
        return report
    passport.setdefault("render_migrations", []).append({
        "at": now(), "from": {k: old_pin.get(k) for k in ("channel", "browser_version", "pinned_at")},
        "to": {k: r["render_profile"].get(k) for k in ("channel", "browser_version")}, "hard_differences": r["pin_check"]["hard"],
        "vs_previous_baseline": report["vs_approved_baseline"], "previous_baseline": approved["path"], "evidence": str(out.relative_to(tdir))})
    passport["render_pin"] = make_pin(r["render_profile"], "baseline migration confirmed")
    passport["baseline_render"] = _approval(tdir, scene, r)
    passport["baseline_match"] = {"profile": profile, "status": rep["overall"]["status"], "how": how,
                                  "report": str((out / "compare" / "report.json").relative_to(tdir)).replace("\\", "/")}
    passport["readiness"] = _readiness(scene, profile, rep["overall"]["status"], edit_rep, passport)
    passport["updated"] = now()
    write_json(tdir / "passport.json", passport)
    rebuild()
    report["status"] = "migrated"
    return report
