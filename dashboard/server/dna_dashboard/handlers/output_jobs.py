"""Output jobs: one isolated engine store per job, frozen inputs, actual checks.

Editable template adaptation: import the version bundle -> continue its design variant (or open one) -> ONE transaction
(keep everything else) with the resolved copy, the product photo and hidden slots -> engine verification against the
previous revision and the approved baseline -> PNG + SVG export with manifest and round trip. Only checks that ran and
passed are reported as passed; a refused transaction stays a review artifact.
Creative generation: a configured image provider makes a new image from the reference and the product photos, and
the output's text policy (chosen and frozen before submission) decides what happens to the approved copy:
  overlay  - the provider makes text-free artwork; the engine renders the template's own text (the approved copy) and
             shapes over it as live layers, verifies the transaction and exports PNG + SVG
  in_image - the provider is asked to draw the approved copy; raster text that a person confirms before approval
  none     - imagery only (the copy is not used; disclosed before submission)
creative_slot places a generated product scene into the template's image slot and runs the same engine checks.
Every paid provider call goes through provider_call: its result is stored durably before anything is built from it,
so a recovered job resumes from it instead of paying again. Before a request whose result the engine must accept,
the template's renderer pin is checked and the transaction is dry-run with a stand-in for the paid image, so drift,
copy that does not fit, locks and failed checks refuse the output before any request is made.
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
from ..faults import crash_point
from ..intake import canonical_file, get as get_asset
from ..providers import for_capability, provider_call
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
    policy = creative_policy(inputs) if o["mode"] == "creative" else None
    if o["mode"] == "creative" and policy != "overlay":
        return _creative_raster(ctx, o, v, odir, policy)
    variant, head = _import(ctx, v)
    # the engine must accept the paid result: check what it can before paying (a recovered attempt that resumes from a
    # stored result has already paid, so it goes straight on, and a refusal keeps that result as evidence)
    if o["mode"] in ("creative", "creative_slot") and not _requested_before(ctx):
        refused = _refuse_on_drift(ctx, o, v, variant) or _refuse_before_paying(ctx, o, v, variant, head, odir)
        if refused:
            return refused
    image_file, source, prov_meta, artwork = None, "supplied", None, None
    if o["mode"] == "creative":
        artwork, prov_meta = _generated_artwork(ctx, o, v)
        ops = compile_overlay_ops(inputs, ts.version_scene(v), artwork, _font_path(inputs))
    else:
        if inputs.get("image") and inputs["image"].get("asset_id"):
            if o["mode"] == "creative_slot":
                image_file, prov_meta = _generated_slot_image(ctx, o, v)
                source = "generated"
            else:
                image_file = _product_png(ctx, inputs["image"]["asset_id"])
        ops = compile_ops(inputs, image_file, source, _font_path(inputs))
    if not ops:
        raise AppError("nothing to change for this output", "no_ops")
    patch = _patch(o, head, ops)
    ctx.stage("transaction", "applying the copy and " + ("the generated artwork" if artwork else "product image")
              + " as one verified transaction in the pinned renderer")
    try:
        txn = engine.call("transact", {"engine_id": v["engine_id"], "variant": variant, "patch": patch}, ctx.home, cancel=ctx.cancelled)
    except EngineError as e:
        paid = [(artwork, "generated-artwork.png")] if artwork else [(image_file, "generated-slot.png")] if source == "generated" else []
        return _refused(ctx, o, odir, e, prov_meta, keep=paid)  # a paid image is kept beside the refusal
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
    if artwork:
        shutil.copyfile(artwork, ev / "generated-artwork.png")
        files.append(_file(ev / "generated-artwork.png", "evidence", "evidence/generated-artwork.png"))
    checks = summarize_checks(txn, exp)
    lim = list(dict.fromkeys(inputs.get("warnings", []) + ts.version(ctx.conn, o["template_version_id"])["summary"]["eligibility"]["adapt"]["limitations"]))
    if artwork:
        checks["path"] = "creative_overlay"
        checks["text"] = {"policy": "overlay", "live_text": _copy_list(inputs),
                          "verified": "rendered by the engine from the approved copy as live text (see the SVG and its manifest)"}
        checks["artwork"] = {"generated": True, "preservation": "not_applicable: the background artwork is new", "provider": prov_meta.get("provider"),
                             "requested_size": prov_meta.get("size_requested")}
        lim = ["the background artwork is generated: no pixel preservation is claimed for it",
               "AI resemblance is not proof of the product's identity: compare it with the product photo"] + lim
        if prov_meta.get("mock"):
            lim.insert(0, "MOCK PROVIDER (test only): this is not a real generation")
    elif prov_meta:
        lim.append("the product scene in the image slot was generated by an AI provider; resemblance is not proof of product identity")
    if checks["verification_status"] == "pass_with_unknowns":
        lim.append("some requested edits have no pixel probe (reported as unknown, not passed)")
    status = "completed" if checks["verification_status"] in ("pass", "pass_with_unknowns") else "needs_review"
    prov = {"path": o["mode"], "engine": {"variant": variant, "revision": txn["revision"], "base_revision": head,
                                          "transaction": f"variants/{variant}/transactions/txn-{txn['revision']:04d}.json"},
            "template_bundle_sha256": v["bundle_sha256"], "product_image": inputs.get("image"),
            "generated": prov_meta}
    if artwork:
        prov.update(kind="generated", text_policy="overlay", prompt=prov_meta.get("prompt"), mock=bool(prov_meta.get("mock")))
    crash_point("after_artifact")
    _set_output(ctx.conn, o["id"], status=status, files=files, checks=checks, limitations=lim, provenance=prov, error=None)
    return status, {"output_id": o["id"], "files": [f["name"] for f in files], "verification": checks["verification_status"]}


def _patch(o, head, ops) -> dict:
    i = o["inputs"]
    return {"schema_version": "1.0.0", "base_revision": head, "keep": "everything_else",
            "intent": f"output {o['id']}: {i['product']['name']} on {i['template']['name']} v{i['template']['number']} ({i['language']})",
            "ops": ops}


def _refused(ctx, o, odir, e: EngineError, prov_meta, keep=(), before_provider=False):
    """A refused transaction is a review artifact with the engine's conflicts and options, never a final output.
    `keep` lists inputs worth keeping beside it (a paid, generated image is never thrown away)."""
    txn = e.detail or {}
    conflicts = txn.get("conflicts") or [e.engine]
    files = []
    for src, name in keep:
        (odir / "refused").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, odir / "refused" / name)
        files.append(_file(odir / "refused" / name, "evidence", f"refused/{name}"))
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
    codes = {c.get("code") for c in conflicts if isinstance(c, dict)}
    abl = v.get("approved_baseline") or {}
    not_reproduced, repro = abl.get("pinned_re_render_reproduces_it") is False, None
    if not_reproduced:  # audit A2: the pinned renderer did not reproduce the approved baseline
        tdir = ctx.home / "templates" / ts.version(ctx.conn, o["template_version_id"])["engine_id"]
        approved, rerender = tdir / abl["path"], Path((v.get("renders") or {}).get("base") or "")
        if approved.exists() and rerender.is_file():
            repro = el.pixel_diff(approved, rerender)
            ev.mkdir(exist_ok=True)
            for src, name in ((approved, "approved-baseline.png"), (rerender, "baseline-re-render.png")):
                shutil.copyfile(src, ev / name)
                files.append(_file(ev / name, "evidence", f"refused/{name}"))
    if not_reproduced:
        where = f" in the box {repro['box']}" if repro and repro.get("box") else ""
        kind, msg = "baseline_not_reproduced", (
            "the pinned renderer did not reproduce this template's approved baseline in this run"
            + (f" ({repro['unequal_pixels']} px differ, max channel error {repro['max_channel_error']}{where})" if repro else "")
            + ". Nothing was committed and no tolerance was applied. Retry this output; if it repeats, rebuild the template to "
              "re-check its reproducibility.")
    elif "renderer_drift" in codes:
        kind, msg = "renderer_drift", ("the renderer differs from this template's pinned baseline, so preservation cannot be checked; "
                                       "preview and confirm a renderer migration on the template page, then retry")
    elif "renderer_unavailable" in codes:
        kind, msg = "infrastructure", "no Chromium-based browser could be launched; nothing was committed"
    else:
        kind, msg = "conflict", "the engine refused this output; nothing was committed"
    if before_provider:
        msg += ". This was checked before the image request, so nothing was requested from the provider"
    err = {"kind": kind, "message": msg, "conflicts": json.loads(json.dumps(conflicts, default=str))[:20]}
    if repro is not None:
        err["baseline_reproduction"] = repro
    checks = summarize_checks(txn, None) if v else {"path": "adapt", "verification_status": "not_run"}
    _set_output(ctx.conn, o["id"], status="needs_review", files=files, checks=checks, error=err,
                provenance={"path": o["mode"], "generated": prov_meta},
                limitations=["refused by the engine: see conflicts"] + (["refused before generation (no paid request)"] if before_provider else []))
    return "needs_review", {"output_id": o["id"], "refused": True, "before_provider": before_provider, "conflicts": err["conflicts"][:5]}


def _template_passport(v) -> dict:
    return el.read_json(ts.version_dir(v) / "passport.json")


def creative_policy(inputs) -> str:
    """The frozen text policy of a creative output. Outputs submitted before policies existed asked for no text."""
    return inputs.get("creative_text") or "none"


def _copy(inputs) -> list[dict]:
    return [e for e in inputs["slots"] if e.get("value") and not e.get("hidden") and not e.get("unused")]


def _copy_list(inputs) -> list[dict]:
    """The copy an output shows, one entry per slot (several slots can share a role)."""
    return [{"slot_id": e["slot_id"], "role": e["role"], "value": e["value"]} for e in _copy(inputs)]


def copy_used(o) -> bool:
    """Whether an output's copy reaches it: not for imagery only, nor for creative outputs frozen before text policies."""
    return not (o["mode"] == "creative" and creative_policy(o["inputs"] or {}) == "none")


def build_prompt(inputs, passport, purpose="artwork", text_policy="none", keep_clear=None) -> str:
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
    if text_policy == "in_image":
        txt = "; ".join(f'{e["role"]}: "{e["value"].replace(chr(10), " / ")}"' for e in _copy(inputs))
        lines.append("Include exactly this text, spelled exactly as written (\" / \" marks a line break), and no other text, "
                     f"letters, logos or watermarks: {txt}.")
    else:
        lines.append("Do not add any text, letters, numbers, logos, watermarks or brand names.")
    if keep_clear:
        lines.append("Keep these areas calm and free of important detail, because the design's own text and shapes will be drawn "
                     "over them: " + "; ".join(keep_clear) + ".")
    return "\n".join(lines)


def _keep_clear(inputs, scene) -> list[str]:
    """The regions the overlay will draw over (approved text and the template's shapes), as canvas percentages."""
    W, H = float(scene["canvas"]["width"]), float(scene["canvas"]["height"])
    text_nodes = {e["node"]: e["role"] for e in _copy(inputs)}
    out = []
    for n in scene["nodes"]:
        g = n.get("geometry")
        if not g or not n.get("visible", True) or not (n["id"] in text_nodes or n["type"] in ("shape", "path")):
            continue
        name = text_nodes.get(n["id"]) or n.get("alias") or n.get("role") or "shape"
        out.append(f"{name} (left {g['x'] / W:.0%}, top {g['y'] / H:.0%}, {g['w'] / W:.0%} wide, {g['h'] / H:.0%} tall)")
    return out


def compile_overlay_ops(inputs, scene, artwork=None, font_path=None) -> list[dict]:
    """Finished artwork with live text: the approved copy into the template's text slots, every image layer hidden (the
    generated artwork replaces the photos), and the background layer replaced by the generated artwork. Without
    `artwork` (a fit preview before submission) the template's own background stays."""
    ops = compile_ops(inputs, None, "supplied", font_path)
    hidden = {o["path"].rsplit(".", 1)[0] for o in ops if o["op"] == "set" and o["path"].endswith(".visible")}
    ops += [{"op": "set", "path": f"{n['id']}.visible", "value": False} for n in scene["nodes"]
            if n["type"] == "image" and n.get("visible", True) and n["id"] not in hidden]
    if artwork:
        bg = next(n["id"] for n in scene["nodes"] if n["type"] == "background")
        ops.append({"op": "replace", "node": bg, "file": str(artwork), "source": "generated"})
    return ops


def _requested_before(ctx) -> bool:
    return bool(db.one(ctx.conn, "SELECT 1 AS x FROM provider_requests WHERE job_id = ? LIMIT 1", (ctx.job["id"],)))


def _refuse_on_drift(ctx, o, v, variant):
    """Refuse before any paid request if the engine could not render the paid result under the template's pin."""
    ctx.stage("pin", "checking the template's pinned renderer before any paid request")
    d = engine.call("pin_check", {"engine_id": v["engine_id"], "variant": variant}, ctx.home, cancel=ctx.cancelled)
    if not d.get("hard"):
        return None
    err = {"kind": "renderer_drift", "message": "the renderer differs from this template's pinned baseline, so the result could not be "
                                                "checked; nothing was requested from the image provider. Preview and confirm a renderer "
                                                "migration on the template page, then retry",
           "conflicts": [{"code": "renderer_drift", "hard": d["hard"], "pinned_at": d.get("pinned_at")}]}
    _set_output(ctx.conn, o["id"], status="needs_review", files=[], error=err,
                checks={"path": o["mode"], "verification_status": "not_run", "renderer": {"status": "drift"}},
                provenance={"path": o["mode"], "generated": None}, limitations=["refused before generation: renderer drift (no paid request)"])
    return "needs_review", {"output_id": o["id"], "refused": True, "before_provider": True}


def _refuse_before_paying(ctx, o, v, variant, head, odir):
    """Dry-run the transaction the paid result will go into, with the template's own background (overlay) or the
    product photo (a generated slot photo) in its place. Copy that does not fit, a lock or a failed check refuses the
    output now, before any request is paid for. The paid result can still be refused later for reasons of its own."""
    inputs = o["inputs"]
    if o["mode"] == "creative":  # the stand-in replaces the background too, so locks on it are checked before paying
        ops = compile_overlay_ops(inputs, ts.version_scene(v), _stand_in_artwork(ctx, inputs), _font_path(inputs))
    else:
        stand_in = _product_png(ctx, inputs["image"]["asset_id"]) if inputs.get("image") and inputs["image"].get("asset_id") else None
        ops = compile_ops(inputs, stand_in, "supplied", _font_path(inputs))
    if not ops:
        return None
    ctx.stage("precheck", "checking the copy and the template's rules in the pinned renderer before any paid request")
    try:
        engine.call("transact", {"engine_id": v["engine_id"], "variant": variant, "patch": _patch(o, head, ops), "dry_run": True},
                    ctx.home, cancel=ctx.cancelled)
    except EngineError as e:
        return _refused(ctx, o, odir, e, None, before_provider=True)
    return None


def _stand_in_artwork(ctx, inputs) -> Path:
    """A canvas-sized checkerboard: it changes every pixel of any background, so the dry run meets every lock the paid
    artwork would."""
    W, H = int(inputs["template"]["canvas"]["width"]), int(inputs["template"]["canvas"]["height"])
    f = ctx.dir / "inputs" / "stand-in-artwork.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    tile = Image.new("RGB", (16, 16), (214, 32, 160))
    tile.paste((32, 180, 96), (0, 0, 8, 8))
    tile.paste((32, 180, 96), (8, 8, 16, 16))
    im = Image.new("RGB", (W, H))
    for x in range(0, W, 16):
        for y in range(0, H, 16):
            im.paste(tile, (x, y))
    im.save(f, "PNG")
    return f


def _generate_image(ctx, o, prov, imgs, prompt, size, call_key):
    """One paid image request for this output, made at most once (resumed from its stored result after a crash)."""
    png, meta = provider_call(ctx.job["id"], call_key, prov.name, "image_generation", getattr(prov, "model", None),
                              lambda tr: prov.generate(imgs, prompt, size, tr), "bytes")
    if meta.get("resumed_from_checkpoint"):
        ctx.log(f"resumed from the stored provider result {meta['resumed_from_checkpoint']}: nothing was requested again")
    return png, meta


def _artwork_request(ctx, o, v):
    inputs = o["inputs"]
    prov = for_capability("image_generation", ctx.input.get("provider"))
    ref = (ts.version_dir(v) / "source" / "canonical.png").read_bytes()
    imgs = [("reference.png", ref, "image/png")]
    for i, aid in enumerate([inputs["product"]["primary_asset_id"]] + list(inputs["product"].get("detail_asset_ids") or [])[:3]):
        if aid:
            imgs.append((f"product-{i}.png", _product_png(ctx, aid, f"product{i}").read_bytes(), "image/png"))
    W, H = int(inputs["template"]["canvas"]["width"]), int(inputs["template"]["canvas"]["height"])
    return prov, imgs, (W, H), request_size(W, H)


def _generated_artwork(ctx, o, v):
    """overlay: text-free artwork for the whole canvas, leaving the regions the design draws over calm."""
    inputs = o["inputs"]
    prov, imgs, _, size = _artwork_request(ctx, o, v)
    prompt = build_prompt(inputs, _template_passport(v), "artwork", "overlay", _keep_clear(inputs, ts.version_scene(v)))
    ctx.stage("provider", f"requesting text-free artwork from {prov.label} (a paid request); the approved copy is added as live text")
    png_bytes, meta = _generate_image(ctx, o, prov, imgs, prompt, size, f"creative:{o['id']}")
    f = ctx.dir / "inputs" / "generated-artwork.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(png_bytes)) as im:
        im.convert("RGB").save(f, "PNG")
        rw, rh = im.size
    meta = dict(meta, prompt=prompt, sha256=hashlib.sha256(f.read_bytes()).hexdigest(), returned=[rw, rh],
                inputs=[{"role": "reference", "sha256": v["bundle_sha256"]}] + [{"role": n, "sha256": hashlib.sha256(b).hexdigest()} for n, b, _ in imgs[1:]])
    return f, meta


def _creative_raster(ctx, o, v, odir, policy):
    """in_image or none: the provider's image is the output."""
    inputs = o["inputs"]
    prov, imgs, (W, H), size = _artwork_request(ctx, o, v)
    prompt = build_prompt(inputs, _template_passport(v), "artwork", policy)
    ctx.stage("provider", f"requesting a creative image from {prov.label} (a paid request)")
    png_bytes, meta = _generate_image(ctx, o, prov, imgs, prompt, size, f"creative:{o['id']}")
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
           "AI resemblance is not proof of the product's identity: compare it with the product photo"]
    if policy == "in_image":
        checks["text"] = {"policy": "in_image", "requested": _copy_list(inputs),
                          "verified": "not checked automatically (no OCR): confirm it matches the approved copy before approving"}
        lim.append("the text was drawn by the image model: it is not live or editable and may be misspelled; confirm it matches "
                   "the approved copy before approving")
    elif "creative_text" not in inputs:  # frozen before text policies existed: nobody chose imagery only
        checks["text"] = {"policy": "none", "legacy": True, "note": "submitted before text policies existed: no text was requested"}
        lim.append("submitted before text policies existed: no text was requested and the copy was not used")
    else:
        checks["text"] = {"policy": "none", "note": "imagery only, chosen before submission: the copy was not used"}
        lim.append("imagery only (chosen before submission): no text was requested and the copy fields were not used")
    if [rw, rh] != [W, H]:
        lim.append(f"returned at {rw}x{rh}; the template is {W}x{H} (no resampling was applied)")
    provenance = {"path": "creative", "kind": "generated", "text_policy": policy, "provider": meta, "prompt": prompt,
                  "inputs": [{"role": "reference", "sha256": v["bundle_sha256"]}] + [{"role": n, "sha256": hashlib.sha256(b).hexdigest()} for n, b, _ in imgs[1:]],
                  "mock": bool(meta.get("mock"))}
    if meta.get("mock"):
        lim.insert(0, "MOCK PROVIDER (test only): this is not a real generation")
    crash_point("after_artifact")
    _set_output(ctx.conn, o["id"], status="completed", files=files, checks=checks, limitations=lim, provenance=provenance, error=None)
    return "completed", {"output_id": o["id"], "provider": meta.get("provider"), "request_id": meta.get("request_id")}


def _generated_slot_image(ctx, o, v):
    inputs = o["inputs"]
    prov = for_capability("image_generation", ctx.input.get("provider"))
    node = next(n for n in ts.version_scene(v)["nodes"] if n["id"] == inputs["image"]["node"])
    g = node["geometry"]
    size = request_size(int(g["w"]), int(g["h"]))
    imgs = [("reference.png", (ts.version_dir(v) / "source" / "canonical.png").read_bytes(), "image/png"),
            ("product.png", _product_png(ctx, inputs["product"]["primary_asset_id"]).read_bytes(), "image/png")]
    prompt = build_prompt(inputs, _template_passport(v), "slot")
    ctx.stage("provider", f"requesting slot imagery from {prov.label} (a paid request)")
    png_bytes, meta = _generate_image(ctx, o, prov, imgs, prompt, size, f"slot:{o['id']}")
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
    if r["mode"] == "creative" and r.get("creative_text") != "overlay":
        raise AppError("this output's text is not rendered by the template (text drawn by the image model, or imagery only): "
                       "there is no fit to check", "no_preview")
    variant, _ = _import(ctx, v)
    font = _font_path(r) if r["language"] == "ar" and r.get("arabic_font") else None
    if r["mode"] == "creative":  # live text over artwork: check the copy fits; the artwork is only made at submission
        ops = compile_overlay_ops(r, ts.version_scene(v), None, font)
    else:
        image_file = _product_png(ctx, r["image"]["asset_id"]) if r.get("image") and r["image"].get("asset_id") else None
        ops = compile_ops(r, image_file, "supplied", font)
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
    data, meta = provider_call(ctx.job["id"], "copy", prov.name, "copy", getattr(prov, "copy_model", None),
                               lambda tr: prov.draft_copy(req, tr), "json")
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
