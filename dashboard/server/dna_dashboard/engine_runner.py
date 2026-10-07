"""Subprocess entry point for engine operations (never imported by the web or worker process).

  python -m dna_dashboard.engine_runner <operation>   < request.json   > {"ok": true, "result": ...}

The parent sets DESIGN_DNA_HOME (an isolated store for this job or template workspace) and DNA_ENGINE_DIR before
starting this process, so engine modules read one store for their whole life. Requests are JSON data: file paths,
ids and typed operations. Nothing in a request is executed or interpolated into a shell.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ENGINE = Path(os.environ["DNA_ENGINE_DIR"])
sys.path.insert(0, str(ENGINE))

MARK = "@@DNA_RESULT@@"


def op_create_template(r):
    from inspect_source import create_template

    return create_template(Path(r["source"]), r["name"], r.get("name_status", "user_supplied"), r.get("engine_id"))


def op_reconstruct(r):
    from baseline import reconstruct

    return reconstruct(r["engine_id"], r.get("mode", "editable"))


def op_migrate_preview(r):
    from baseline import migrate_baseline

    return migrate_baseline(r["engine_id"])


def op_migrate_confirm(r):
    from baseline import migrate_baseline

    return migrate_baseline(r["engine_id"], confirm=True, preview_id=r["preview_id"])


def op_export_bundle(r):
    from bundle import export_bundle

    return export_bundle(r["engine_id"], r["dest"], r.get("fonts", "embed"))


def op_validate_bundle(r):
    from bundle import validate_bundle

    return validate_bundle(r["bundle"], r.get("font_dirs", []))


def op_import_bundle(r):
    from bundle import import_bundle

    return import_bundle(r["bundle"], r.get("as_id"), r.get("font_dirs", []))


def op_new_variant(r):
    from apply_patch import new_variant

    return new_variant(r["engine_id"], r["task"], r.get("name"))


def op_transact(r):
    from apply_patch import transact

    return transact(r["engine_id"], r["variant"], r["patch"], verify=r.get("verify", True), dry_run=r.get("dry_run", False))


def op_undo(r):
    from apply_patch import undo

    return undo(r["engine_id"], r["variant"])


def op_export(r):
    from apply_patch import export

    return export(r["engine_id"], r["variant"], tuple(r.get("formats", ("png", "svg"))), r.get("svg_fonts", "embed"))


def op_variant_state(r):
    from apply_patch import load_variant

    vd, meta, head = load_variant(r["engine_id"], r["variant"])
    return {"meta": meta, "head": head, "dir": str(vd)}


def op_validate(r):
    from common import read_json, template_dir
    from validate_model import check_scene, passport_report, schema_errors

    tdir = template_dir(r["engine_id"])
    scene = r.get("scene") or read_json(tdir / "scene.json")
    rep = check_scene(scene, tdir)
    for extra, schema in (("passport.json", "template.schema.json"), ("evidence/evidence.json", "evidence.schema.json")):
        if (tdir / extra).exists():
            errs = schema_errors(read_json(tdir / extra), schema)
            rep["errors"] += [f"{extra}: {e}" for e in errs]
            rep["valid"] = rep["valid"] and not errs
    if (tdir / "passport.json").exists():
        rep["passport"] = passport_report(read_json(tdir / "passport.json"))
    return rep


def op_preview(r):
    """Apply typed ops to a copy of a variant head (or the template scene) and render it: nothing is committed.
    Fit conflicts come back as structured errors with the engine's options."""
    from apply_patch import load_variant
    from common import read_json, template_dir
    from ops import apply_ops
    from render_static import render

    tdir = template_dir(r["engine_id"])
    base = load_variant(r["engine_id"], r["variant"])[2] if r.get("variant") else read_json(tdir / "scene.json")
    after, changes = apply_ops(base, r["ops"], tdir) if r.get("ops") else (base, [])
    res = render(after, tdir, r["out"], isolate=False, formats=("png",), name="preview")
    return {"png": res["png"], "fit": res["fit"], "fitted_sizes": res["fitted_sizes"], "pin_check": res["pin_check"],
            "warnings": res["warnings"], "changes": [{k: c.get(k) for k in ("path", "kind", "why")} for c in changes]}


def op_render_scene(r):
    from common import template_dir
    from render_static import render

    res = render(r["scene"], template_dir(r["engine_id"]), r["out"], isolate=r.get("isolate", False),
                 formats=tuple(r.get("formats", ("png",))), name=r.get("name", "render"))
    return {"png": res["png"], "png_sha256": res["png_sha256"], "fit": res["fit"], "pin_check": res["pin_check"]}


def op_annotate(r):
    import subprocess

    out = subprocess.run([sys.executable, str(ENGINE / "annotate_scan.py"), r["engine_id"]], capture_output=True, text=True)
    return {"returncode": out.returncode, "stdout": out.stdout[-2000:], "stderr": out.stderr[-2000:]}


def op_capabilities(r):
    import subprocess

    out = subprocess.run([sys.executable, str(ENGINE / "capabilities.py")], capture_output=True, text=True, timeout=180)
    return json.loads(out.stdout)


def op_fingerprint(r):
    from renderer_env import browser

    with browser(r.get("channel")) as (b, ch):
        return {"channel": ch, "version": b.version}


OPS = {k[3:]: v for k, v in globals().items() if k.startswith("op_")}


def _die_with_parent() -> None:
    """If the worker that started this step is killed, stop too (Linux), so an orphaned engine step can never keep
    writing into a store that a recovered job is about to use."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        import signal

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        return
    parent = os.environ.get("DNA_PARENT_PID")
    if parent and os.getppid() != int(parent):  # the parent already died before prctl took effect
        os._exit(3)


def main() -> int:
    _die_with_parent()
    name = sys.argv[1]
    req = json.loads(sys.stdin.read() or "{}")
    from common import DnaError

    try:
        res = {"ok": True, "result": OPS[name](req)}
    except DnaError as e:
        res = {"ok": False, "engine_error": e.as_dict()}
    except Exception as e:  # infrastructure failure: reported with its trace, never as a result
        res = {"ok": False, "crash": {"type": type(e).__name__, "message": str(e)[:2000], "trace": traceback.format_exc()[-4000:]}}
    sys.stdout.write("\n" + MARK + json.dumps(res, ensure_ascii=False, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
