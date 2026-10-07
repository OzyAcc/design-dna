"""Output jobs: one isolated engine store per job, frozen inputs, actual checks.

Editable template adaptation: import the version bundle -> continue its design variant (or open one) -> ONE transaction
(keep everything else) with the resolved copy, the product photo and hidden slots -> engine verification against the
previous revision and the approved baseline -> PNG + SVG export with manifest and round trip. Only checks that ran and
passed are reported as passed; a refused transaction stays a review artifact.
Creative generation: a configured image provider makes a new image from the reference and the product photos. Its
provenance is recorded; no preservation or editability claim is made. creative_slot places a generated product scene
into the template's image slot and then runs the same engine adaptation and checks.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
from pathlib import Path

from PIL import Image

from .. import batches, config, db, engine
from .. import enginelib as el
from .. import templates_svc as ts
from ..engine import EngineError
from ..errors import AppError
from ..intake import canonical_file, get as get_asset
from ..providers import for_capability, tracked
from ..providers.openai_provider import request_size
from ..worker import handler

PRESERVE = ["treatment", "crop-intent", "anchor", "mask", "effects"]


def slugify(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n] or "x"


def out_name(inputs, rev, ext):
    return f"{slugify(inputs['product']['name'])}--{slugify(inputs['template']['name'])}--{inputs['language']}--v{rev}.{ext}"


def compile_ops(inputs, image_file=None, image_source="supplied", font_path=None) -> list[dict]:
    ops = []
    texts = {e["node"]: e["value"] for e in inputs["slots"] if not e["hidden"] and e["value"] is not None and not e["locked"]}
    hidden = [e["node"] for e in inputs["slots"] if e["hidden"]] + list(inputs.get("logos_hidden") or [])
    if inputs["language"] == "ar" and texts:
        ops.append({"op": "adapt", "language": "ar", "contents": texts, "font": font_path, "mirror_alignment": True})
    else:
        ops += [{"op": "set", "path": f"{node}.content", "value": val} for node, val in texts.items()]
    ops += [{"op": "set", "path": f"{node}.visible", "value": False} for node in hidden]
    if image_file:
        ops.append({"op": "replace", "node": inputs["image"]["node"], "file": str(image_file), "preserve": PRESERVE, "source": image_source})
    return ops


def _font_path(inputs):
    f = inputs.get("arabic_font")
    if not f:
        return None
    hit = next((x for x in el.font_library() if x["sha256"] == f["sha256"]), None)
    if not hit:
        raise AppError("the Arabic font chosen for this batch is no longer in the font library", "missing_font")
    return hit["path"]


def _product_png(ctx, asset_id, name="product") -> Path:
    a = get_asset(ctx.conn, asset_id)
    dst = ctx.dir / "inputs" / f"{name}-{a['sha256'][:12]}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(canonical_file(a), dst)  # the oriented sRGB copy: what the pinned renderer can decode
    return dst


def _set_output(conn, oid, **values):
    values["updated_at"] = db.now()
    with db.tx(conn):
        db.update(conn, "outputs", oid, values)


def _file(path: Path, kind: str, name: str) -> dict:
    rec = {"kind": kind, "name": name, "path": str(path), "bytes": path.stat().st_size,
           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if path.suffix == ".png":
        with Image.open(path) as im:
            rec.update(width=im.width, height=im.height)
    return rec


def _import(ctx, v):
    ctx.stage("import", f"importing template version {v['number']} into an isolated store")
    engine.call("import_bundle", {"bundle": v["bundle_path"]}, ctx.home, cancel=ctx.cancelled)
    if v.get("design_variant"):
        st = engine.call("variant_state", {"engine_id": v["engine_id"], "variant": v["design_variant"]}, ctx.home)
        if v.get("design_head") is not None and st["meta"]["head"] != v["design_head"]:
            raise AppError("the version's design head does not match its bundle", "bundle_mismatch", 500)
        return v["design_variant"], st["meta"]["head"]
    m = engine.call("new_variant", {"engine_id": v["engine_id"], "task": f"output {ctx.input.get('output_id', '')}"[:80],
                                    "name": f"output {ctx.input.get('output_id', '')}"}, ctx.home)
    return m["id"], m["head"]


def summarize_checks(txn: dict, exp: dict | None) -> dict:
    v = txn.get("verification") or {}
    mc = v.get("model_changes") or {}
    vis = v.get("visual_changes") or {}
    vb = v.get("vs_approved_baseline") or {}
    out = {"path": "adapt", "verification_status": v.get("status"),
           "model_changes": {"status": mc.get("status"), "requested": mc.get("requested"), "unexplained": mc.get("unexplained"),
                             "frozen_leaf_paths": (mc.get("frozen") or {}).get("frozen_leaf_paths")},
           "requested_edits": v.get("requested_edits"),
           "visual_changes": {k: vis.get(k) for k in ("status", "compared_against", "changed_pixels", "inside_influence", "outside_influence", "note")},
           "vs_approved_baseline": {"model": (vb.get("model_changes") or {}).get("status"),
                                    "visual": {k: (vb.get("visual_changes") or {}).get(k) for k in ("status", "compared_against", "outside_influence", "note")}}
           if vb else None,
           "approved_baseline_reproduced": (v.get("approved_baseline") or {}).get("pinned_re_render_reproduces_it"),
           "pixel_locks": v.get("pixel_locks"), "renderer": {k: (v.get("renderer") or {}).get(k) for k in ("status", "pinned_at")},
           "constraints_relaxed": [n for n in txn.get("constraint_notes", []) if n.get("relaxed")]}
    if exp:
        sv = exp.get("svg_verification") or {}
        out["svg"] = {"roundtrip": sv.get("roundtrip_status"), "detail": {k: sv.get(k) for k in sv if k not in ("roundtrip_status", "roundtrip_png")}}
    return out


@handler("output.generate")
def generate(ctx):
    o = db.one(ctx.conn, "SELECT * FROM outputs WHERE id = ?", (ctx.input["output_id"],))
    if not o:
        raise AppError("output record missing", "not_found")
    _set_output(ctx.conn, o["id"], status="running")
    inputs = o["inputs"]
    v = ts.version(ctx.conn, o["template_version_id"])
    if v["bundle_sha256"] != inputs["template"]["bundle_sha256"]:
        raise AppError("the frozen template version bundle changed on disk; refusing to generate", "bundle_mismatch", 500)
    odir = config.get().outputs / o["id"]
    odir.mkdir(parents=True, exist_ok=True)
    if o["mode"] == "creative":
        return _creative(ctx, o, v, odir)
    variant, head = _import(ctx, v)
    image_file, source, prov_meta = None, "supplied", None
    if inputs.get("image") and inputs["image"].get("asset_id"):
        if o["mode"] == "creative_slot":
            image_file, prov_meta = _generated_slot_image(ctx, o, v)
            source = "generated"
        else:
            image_file = _product_png(ctx, inputs["image"]["asset_id"])
    ops = compile_ops(inputs, image_file, source, _font_path(inputs))
    if not ops:
        raise AppError("nothing to change for this output", "no_ops")
    patch = {"schema_version": "1.0.0", "base_revision": head, "keep": "everything_else",
             "intent": f"output {o['id']}: {inputs['product']['name']} on {inputs['template']['name']} v{inputs['template']['number']} ({inputs['language']})",
             "ops": ops}
    ctx.stage("transaction", "applying the copy and product image as one verified transaction in the pinned renderer")
    try:
        txn = engine.call("transact", {"engine_id": v["engine_id"], "variant": variant, "patch": patch}, ctx.home, cancel=ctx.cancelled)
    except EngineError as e:
        return _refused(ctx, o, odir, e, prov_meta)
    ctx.stage("export", "exporting PNG and self-contained SVG, then rendering the SVG to check it")
    exp = engine.call("export", {"engine_id": v["engine_id"], "variant": variant, "formats": ["png", "svg"]}, ctx.home, cancel=ctx.cancelled)
    ctx.stage("collect", "storing files and the check report")
    rev = o["revision"]
    files = []
    png = odir / out_name(inputs, rev, "png")
    shutil.copyfile(exp["png"], png)
    files.append(_file(png, "png", png.name))
    if exp.get("svg"):
        svg = odir / out_name(inputs, rev, "svg")
        shutil.copyfile(exp["svg"], svg)
        files.append(_file(svg, "svg", svg.name))
        src_man = Path(exp["svg"]).with_name(Path(exp["svg"]).name + ".manifest.json")  # written next to the SVG by svg_export
        if src_man.exists():
            man = odir / (svg.name + ".manifest.json")
            shutil.copyfile(src_man, man)
            files.append(_file(man, "svg_manifest", man.name))
    ev = odir / "evidence"
    ev.mkdir(exist_ok=True)
    vr = txn.get("verification") or {}
    for key, name in (("visual_changes", "visual_diff.png"), ("vs_approved_baseline", "visual_diff_vs_baseline.png")):
        art = ((vr.get(key) or {}).get("artifact") or ((vr.get(key) or {}).get("visual_changes") or {}).get("artifact"))
        if art and Path(art).exists():
            shutil.copyfile(art, ev / name)
            files.append(_file(ev / name, "evidence", f"evidence/{name}"))
    base = (vr.get("renders") or {}).get("base")
    if base and Path(base).exists():
        shutil.copyfile(base, ev / "before.png")
        files.append(_file(ev / "before.png", "evidence", "evidence/before.png"))
    checks = summarize_checks(txn, exp)
    lim = list(dict.fromkeys(inputs.get("warnings", []) + ts.version(ctx.conn, o["template_version_id"])["summary"]["eligibility"]["adapt"]["limitations"]))
    if prov_meta:
        lim.append("the product scene in the image slot was generated by an AI provider; resemblance is not proof of product identity")
    if checks["verification_status"] == "pass_with_unknowns":
        lim.append("some requested edits have no pixel probe (reported as unknown, not passed)")
    status = "completed" if checks["verification_status"] in ("pass", "pass_with_unknowns") else "needs_review"
    prov = {"path": o["mode"], "engine": {"variant": variant, "revision": txn["revision"], "base_revision": head,
                                          "transaction": f"variants/{variant}/transactions/txn-{txn['revision']:04d}.json"},
            "template_bundle_sha256": v["bundle_sha256"], "product_image": inputs.get("image"),
            "generated": prov_meta}
    _set_output(ctx.conn, o["id"], status=status, files=files, checks=checks, limitations=lim, provenance=prov, error=None)
    return status, {"output_id": o["id"], "files": [f["name"] for f in files], "verification": checks["verification_status"]}


def _refused(ctx, o, odir, e: EngineError, prov_meta):
    """A refused transaction is a review artifact with the engine's conflicts and options, never a final output."""
    txn = e.detail or {}
    conflicts = txn.get("conflicts") or [e.engine]
    files = []
    v = txn.get("verification") or {}
    cand = (v.get("renders") or {}).get("candidate")
    ev = odir / "refused"
    if cand and Path(cand).exists():
        ev.mkdir(exist_ok=True)
        shutil.copyfile(cand, ev / "refused-candidate.png")
        files.append(_file(ev / "refused-candidate.png", "refused_candidate", "refused/refused-candidate.png"))
        art = (v.get("visual_changes") or {}).get("artifact")
        if art and Path(art).exists():
            shutil.copyfile(art, ev / "visual_diff.png")
            files.append(_file(ev / "visual_diff.png", "evidence", "refused/visual_diff.png"))
    kind = "infrastructure" if any((c.get("code") if isinstance(c, dict) else None) in ("renderer_unavailable", "renderer_drift") for c in conflicts) else "conflict"
    err = {"kind": kind, "message": "the engine refused this output; nothing was committed", "conflicts": json.loads(json.dumps(conflicts, default=str))[:20]}
    checks = summarize_checks(txn, None) if v else {"path": "adapt", "verification_status": "not_run"}
    _set_output(ctx.conn, o["id"], status="needs_review", files=files, checks=checks, error=err,
                provenance={"path": o["mode"], "generated": prov_meta}, limitations=["refused by the engine: see conflicts"])
    return "needs_review", {"output_id": o["id"], "refused": True, "conflicts": err["conflicts"][:5]}


def _template_passport(v) -> dict:
    return el.read_json(ts.version_dir(v) / "passport.json")


def build_prompt(inputs, passport, purpose="artwork", include_text=False) -> str:
    val = lambda k: (passport.get(k) or {}).get("value") if isinstance(passport.get(k), dict) else None
    style = "; ".join(f"{k}: {val(k)}" for k in ("character", "theme", "mechanism") if val(k))
    prod = inputs["product"]
    facts = "; ".join(f for f in prod.get("facts") or [] if f)
    lines = []
    if purpose == "artwork":
        lines.append("Create a new finished marketing image for the product shown in the product photo(s).")
        lines.append("Use the first image (the reference design) only for its visual approach: composition, palette, lighting, "
                     "depth and mood" + (f" ({style})" if style else "") + ". Do not copy its product, text, logo or brand.")
    else:
        lines.append("Create a photograph of the product shown in the product photo(s), styled to sit inside an existing layout.")
        lines.append("Match the reference design's lighting, palette and mood" + (f" ({style})" if style else "") + ".")
    lines.append(f"Product: {prod['name']}." + (f" Description: {prod['description']}" if prod.get("description") else ""))
    if facts:
        lines.append(f"Product facts (use only these; add no other claims): {facts}.")
    if inputs.get("instructions"):
        lines.append("Instructions: " + " / ".join(inputs["instructions"]))
    lines.append("Keep the product's shape, colour, material and identifying details exactly as in the product photo.")
    if include_text:
        txt = [e["value"] for e in inputs["slots"] if e.get("value") and not e.get("hidden")]
        lines.append("Include exactly this text and no other: " + " | ".join(txt))
    else:
        lines.append("Do not add any text, letters, numbers, logos, watermarks or brand names.")
    return "\n".join(lines)


def _creative(ctx, o, v, odir):
    inputs = o["inputs"]
    prov = for_capability("image_generation", ctx.input.get("provider"))
    ref = (ts.version_dir(v) / "source" / "canonical.png").read_bytes()
    imgs = [("reference.png", ref, "image/png")]
    for i, aid in enumerate([inputs["product"]["primary_asset_id"]] + list(inputs["product"].get("detail_asset_ids") or [])[:3]):
        if aid:
            imgs.append((f"product-{i}.png", _product_png(ctx, aid, f"product{i}").read_bytes(), "image/png"))
    W, H = int(inputs["template"]["canvas"]["width"]), int(inputs["template"]["canvas"]["height"])
    size = request_size(W, H)
    prompt = build_prompt(inputs, _template_passport(v), "artwork", bool(ctx.input.get("include_text")))
    ctx.stage("provider", f"requesting a creative image from {prov.label} (a paid request)")
    with tracked(prov.name, "image_generation", getattr(prov, "model", None), ctx.job["id"]) as tr:
        png_bytes, meta = prov.generate(imgs, prompt, size, tr)
    ctx.stage("collect", "storing the generated image and its provenance")
    path = odir / out_name(inputs, o["revision"], "png")
    with Image.open(io.BytesIO(png_bytes)) as im:
        im.save(path, "PNG")
        rw, rh = im.size
    files = [_file(path, "png", path.name)]
    checks = {"path": "creative", "provider_returned_image": True, "dimensions": {"template": [W, H], "requested": size, "returned": [rw, rh]},
              "preservation": "not_applicable: a new image, not an adaptation of the template model",
              "editability": "none: a single raster image", "comparison": "not run (no deterministic baseline applies)"}
    lim = ["creative result: layout, typography and colours are not verified against the template",
           "AI resemblance is not proof of the product's identity: compare it with the product photo",
           "text in the image was not requested" if not ctx.input.get("include_text") else "text inside the image is not live or editable"]
    if [rw, rh] != [W, H]:
        lim.append(f"returned at {rw}x{rh}; the template is {W}x{H} (no resampling was applied)")
    provenance = {"path": "creative", "kind": "generated", "provider": meta, "prompt": prompt,
                  "inputs": [{"role": "reference", "sha256": v["bundle_sha256"]}] + [{"role": n, "sha256": hashlib.sha256(b).hexdigest()} for n, b, _ in imgs[1:]],
                  "mock": bool(meta.get("mock"))}
    if meta.get("mock"):
        lim.insert(0, "MOCK PROVIDER (test only): this is not a real generation")
    _set_output(ctx.conn, o["id"], status="completed", files=files, checks=checks, limitations=lim, provenance=provenance, error=None)
    return "completed", {"output_id": o["id"], "provider": meta.get("provider"), "request_id": meta.get("request_id")}


def _generated_slot_image(ctx, o, v):
    inputs = o["inputs"]
    prov = for_capability("image_generation", ctx.input.get("provider"))
    node = next(n for n in el.read_json(ts.version_dir(v) / "scene.json")["nodes"] if n["id"] == inputs["image"]["node"])
    g = node["geometry"]
    size = request_size(int(g["w"]), int(g["h"]))
    imgs = [("reference.png", (ts.version_dir(v) / "source" / "canonical.png").read_bytes(), "image/png"),
            ("product.png", _product_png(ctx, inputs["product"]["primary_asset_id"]).read_bytes(), "image/png")]
    prompt = build_prompt(inputs, _template_passport(v), "slot")
    ctx.stage("provider", f"requesting slot imagery from {prov.label} (a paid request)")
    with tracked(prov.name, "image_generation", getattr(prov, "model", None), ctx.job["id"]) as tr:
        png_bytes, meta = prov.generate(imgs, prompt, size, tr)
    f = ctx.dir / "inputs" / "generated-slot.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(png_bytes)) as im:
        im.convert("RGB").save(f, "PNG")
    meta = dict(meta, prompt=prompt, sha256=hashlib.sha256(f.read_bytes()).hexdigest(), slot=inputs["image"]["slot_id"])
    return f, meta


@handler("pair.preview")
def preview(ctx):
    """Render one pair's resolved copy and product photo without committing anything: fit + a preview image."""
    b = batches.get(ctx.conn, ctx.input["batch_id"])
    p = batches.get_pair(ctx.conn, b["id"], ctx.input["pair_id"])
    r = batches.resolve(ctx.conn, b, p)
    v = ts.version(ctx.conn, p["template_version_id"])
    variant, _ = _import(ctx, v)
    image_file = _product_png(ctx, r["image"]["asset_id"]) if r.get("image") and r["image"].get("asset_id") else None
    ops = compile_ops(r, image_file, "supplied", _font_path(r) if r["language"] == "ar" and r.get("arabic_font") else None)
    out = ctx.dir / "preview"
    ctx.stage("render", "rendering the preview in the pinned renderer (nothing is committed)")
    prev = {"inputs_hash": r["inputs_hash"], "at": db.now(), "mode": r["mode"]}
    try:
        res = engine.call("preview", {"engine_id": v["engine_id"], "variant": variant, "ops": ops, "out": str(out)}, ctx.home, cancel=ctx.cancelled)
        dst = config.get().data_dir / "pair-previews" / p["id"] / f"{r['inputs_hash']}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(res["png"], dst)
        prev.update(status="fits", png=str(dst), fit={"status": "fits", "nodes": res["fit"], "fitted_sizes": res["fitted_sizes"]},
                    pin=res["pin_check"].get("status"))
        if res["fitted_sizes"]:
            prev["fit"]["status"] = "fitted"
    except EngineError as e:
        if e.code != "fit_conflict":
            raise
        prev.update(status="overflow", fit={"status": "overflow", "overflow": {k: f"{x['max_line_width']:.0f}px wide in a {x['box_w']:.0f}px box, "
                                                                                      f"{x['lines']} line(s)" for k, x in (e.detail.get("overflow") or {}).items()},
                                            "options": e.detail.get("options")})
    with db.tx(ctx.conn):
        db.update(ctx.conn, "batch_pairs", p["id"], {"preview": prev, "updated_at": db.now()})
    return "completed", {"pair_id": p["id"], "status": prev["status"]}


@handler("batch.draft_copy")
def draft_copy(ctx):
    b = batches.get(ctx.conn, ctx.input["batch_id"])
    req = {"outputs": []}
    targets = []
    for pid in ctx.input["pair_ids"]:
        p = batches.get_pair(ctx.conn, b["id"], pid)
        r = batches.resolve(ctx.conn, b, p)
        v = ts.version(ctx.conn, p["template_version_id"])
        pp = _template_passport(v)
        want = set(ctx.input.get("slot_ids") or [])
        slots = [{"slot_id": e["slot_id"], "role": e["role"], "max_chars": e["limits"].get("max_chars"), "max_lines": e["limits"].get("max_lines"),
                  "template_text_for_tone_only": e["template_text"]} for e in r["slots"] if not e["locked"] and (not want or e["slot_id"] in want)]
        if not slots:
            continue
        targets.append(p["id"])
        req["outputs"].append({"pair_id": p["id"], "language": r["language"], "product": r["product"] | {"facts": r["product"]["facts"]},
                               "template": {"name": r["template"]["name"], **{k: (pp.get(k) or {}).get("value") for k in
                                                                               ("character", "theme", "goal", "literal_message")
                                                                               if isinstance(pp.get(k), dict)}},
                               "instructions": r["instructions"], "slots": slots})
    if not req["outputs"]:
        raise AppError("no editable text slots to draft", "nothing_to_draft")
    prov = for_capability("copy", ctx.input.get("provider"))
    ctx.stage("provider", f"asking {prov.label} for copy drafts (a paid request)")
    with tracked(prov.name, "copy", getattr(prov, "copy_model", None), ctx.job["id"]) as tr:
        data, meta = prov.draft_copy(req, tr)
    n = 0
    with db.tx(ctx.conn):
        for pid in targets:
            p = batches.get_pair(ctx.conn, b["id"], pid)
            drafts = dict(p["ai_drafts"] or {})
            for d in data.get("drafts", []):
                if d.get("pair_id") == pid and d.get("slot_id"):
                    drafts[d["slot_id"]] = {"value": d.get("text", ""), "note": d.get("note", ""), "provider": meta.get("provider"),
                                            "model": meta.get("model"), "request_id": meta.get("request_id"), "mock": bool(meta.get("mock")),
                                            "at": db.now()}
                    n += 1
            db.update(ctx.conn, "batch_pairs", pid, {"ai_drafts": drafts, "updated_at": db.now()})
    return "completed", {"drafts": n, "provider": meta}
