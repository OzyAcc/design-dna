"""Acceptance demonstrations 15-22 (v2) + one explicitly UNVERIFIED host integration (23).

15 keep-everything-else headline move · 16 conflicting explicit lock · 17 long-text overflow + Arabic shaping/missing
glyphs · 18 accent token isolation · 19 image replacement (crop intent, mask, treatment, shadow handling) ·
20 bundle export/import after the working folder is removed · 21 renderer version drift + explicit migration ·
22 exported SVG rendered and checked. Inputs, outputs and transactions are retained per test folder.
"""
from __future__ import annotations

import json
import os
import shutil
import traceback
from pathlib import Path

import dna
import crash
import fontset
from apply_patch import load_variant, new_variant, transact
from bundle import Library, export_bundle, import_bundle, validate_bundle
from common import read_json, store_root, template_dir, write_json
from compare_render import decode, pixel_metrics
from render_static import render

T = "Editorial Product Spotlight"
TID = "editorial-product-spotlight"


def node(scene, nid):
    return next(n for n in scene["nodes"] if n["id"] == nid)


def folder(root, n, name):
    p = Path(root) / f"t{n:02d}-{name}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def keep_artifacts(o, txn, names=("base", "candidate")):
    v = txn.get("verification") or {}
    for k in names:
        if (v.get("renders") or {}).get(k):
            shutil.copy2(v["renders"][k], o / f"{k}.png")
    if (v.get("visual_changes") or {}).get("artifact"):
        shutil.copy2(v["visual_changes"]["artifact"], o / "visual_diff.png")
    write_json(o / "transaction.json", txn)


def txn_of(r):
    tid, vid = dna.current()
    return read_json(template_dir(tid) / "variants" / vid / "transactions" / f"txn-{r['revision']:04d}.json")


def t15(root, fx, record, expect_error):
    o = folder(root, 15, "keep-everything-else")
    dna.run(f'use "{T}" for task "Nudge headline"')
    tid, vid = dna.current()
    _, _, before = load_variant(tid, vid)
    r = dna.run("move headline by x=0px y=-3px keep everything else")
    txn = txn_of(r)
    keep_artifacts(o, txn)
    v, (_, _, after) = txn["verification"], load_variant(tid, vid)
    mc, vc = v["model_changes"], v["visual_changes"]
    hb, ha = node(before, "n-headline"), node(after, "n-headline")
    props = ("content", "font", "align", "fill", "tracking", "line_height", "direction", "fit")
    u = dna.run("undo last")
    record(15, "\"Move the headline up 3px and keep everything else\"", {
        "committed (the move is authorised, not blocked)": r["status"] == "committed",
        "scope recorded: keep everything_else": (txn.get("scope") or {}).get("keep") == "everything_else",
        "authorised = geometry.y + its baseline dependency only": mc["requested"] == ["nodes.n-headline.geometry.y"]
        and [d["path"] for d in mc["dependencies"]] == ["nodes.n-headline.first_baseline"] or mc,
        "every other property frozen and unchanged": mc["frozen"]["violations"] == [] and mc["frozen"]["frozen_leaf_paths"] > 100 or mc.get("frozen"),
        "headline content + typography preserved": all(hb[k] == ha[k] for k in props),
        "all other nodes identical": all(node(before, n["id"]) == n for n in after["nodes"] if n["id"] != "n-headline"),
        "no persistent locks were added": before["locks"] == after["locks"],
        "measured label->headline gap relaxed by the explicit edit and reported (42 -> 39)":
            [(n["constraint"], n["before"], n["after"]) for n in r["relaxed_constraints"]] == [("c-label-gap", 42, 39)] or r["relaxed_constraints"],
        "render shows exactly -3px": all(x["status"] == "pass" for x in v["requested_edits"]) or v["requested_edits"],
        "compared against the approved template baseline": vc["compared_against"].startswith("approved") or vc["compared_against"],
        "0 changed pixels outside the headline's footprint": vc["outside_influence"] == 0 or vc,
        "only the headline's pixels changed": [x["node"] for x in vc["by_node"]] == ["n-headline"] or vc["by_node"],
        "undo restores the previous revision": u["head"] == before["revision"],
    }, [o / "visual_diff.png", o / "transaction.json"])


def t16(root, fx, record, expect_error):
    o = folder(root, 16, "explicit-lock-conflict")
    dna.run(f'use "{T}" for task "Locked headline"')
    tid, vid = dna.current()
    vd = template_dir(tid) / "variants" / vid
    r1 = dna.run("lock headline.geometry")
    ok, err = expect_error(lambda: dna.run("move headline by x=0px y=-3px keep everything else"), "lock-1-headline-geometry")
    _, _, h = load_variant(tid, vid)
    rejected = sorted((vd / "rejected").glob("*.json"))
    r2 = dna.run("unlock headline.geometry")
    r3 = dna.run("move headline by x=0px y=-3px keep everything else")
    u1, u2 = dna.run("undo last"), dna.run("undo last")
    _, _, back = load_variant(tid, vid)
    # pixel locks: a locked region (logo) survives an unrelated edit, and blocks an edit that would repaint it
    dna.run("lock pixels 860,1150,160,110")
    rp = dna.run('set headline.content = "Carry the\\nquiet certainty."')
    okp, errp = expect_error(lambda: dna.run("move logo by x=-6px y=0px"), "pixel_locks")
    pix = ((errp.detail if errp else {}).get("verification") or {}).get("pixel_locks") or [{}]
    write_json(o / "pixel-lock-conflict.json", errp.as_dict() if errp else {})
    write_json(o / "conflict.json", err.as_dict() if err else {})
    conf = json.dumps(err.detail if err else {}, default=str)
    record(16, "An explicit lock conflicts with a \"keep everything else\" edit", {
        "move rejected because of the explicit lock (named)": ok,
        "conflict says how to resolve (unlock …)": "unlock headline.geometry" in conf,
        "head unchanged and the lock still present (never silently removed)": h["revision"] == r1["revision"]
        and any(lk["target"] == "headline.geometry" for lk in h["locks"]),
        "rejected transaction recorded": bool(rejected),
        "explicit unlock, then the same edit commits": r2["status"] == "committed" and r3["status"] == "committed",
        "undo history intact (undo twice returns to the locked revision)": u1["head"] == r2["revision"] and u2["head"] == r1["revision"]
        and any(lk["target"] == "headline.geometry" for lk in back["locks"]),
        "pixel lock: an unrelated edit commits with 0 px changed in the locked region": rp["status"] == "committed",
        "pixel lock: moving the logo inside it is rejected with the changed-pixel count": okp and pix[0].get("status") == "fail"
        and pix[0].get("changed_pixels", 0) > 0 or pix,
    }, [o / "conflict.json", o / "pixel-lock-conflict.json"] + rejected[:1])


def shaping_probe(scene, tdir, nid, work):
    from playwright.sync_api import sync_playwright

    from render_static import _load, compile_svg
    from renderer_env import launch

    svg, _ = compile_svg(scene, tdir)
    with sync_playwright() as p:
        b, _ = launch(p)
        pg = b.new_page(viewport={"width": int(scene["canvas"]["width"]), "height": int(scene["canvas"]["height"])})
        _load(pg, svg, work)
        out = pg.evaluate("""(id) => { const t = document.querySelector('#' + id + ' text'); const fam = t.getAttribute('font-family');
            const w = (s) => { const e = document.createElementNS('http://www.w3.org/2000/svg', 'text'); e.setAttribute('font-family', fam);
              e.setAttribute('font-size', 80); e.textContent = s; document.querySelector('svg').appendChild(e);
              const v = e.getComputedTextLength(); e.remove(); return v; };
            return {joined: w('حقيبة يومية'), separated: w('ح\\u200cق\\u200cي\\u200cب\\u200cة ي\\u200cو\\u200cم\\u200cي\\u200cة'),
                    direction: t.getAttribute('direction')}; }""", nid)
        b.close()
    return out


def t17(root, fx, record, expect_error):
    o = folder(root, 17, "overflow-arabic")
    dna.run(f'use "{T}" for task "Overflow and Arabic"')
    tid, vid = dna.current()
    _, _, h0 = load_variant(tid, vid)
    ok1, e1 = expect_error(lambda: dna.run('set cta.content = "Shop the complete autumn edit today"'), "fit_conflict")
    ok2, e2 = expect_error(lambda: dna.run('set headline.content = "صُنعت لكلّ يوم"'), "lacks glyphs")
    ok3, e3 = expect_error(lambda: dna.run('set label.content = "موسم جديد"'), "breaks joining")
    long_ar = "تصميم يدوم لكل يوم ولكل مناسبة ولكل رحلة\\nحقيبة يومية فاخرة 2026"  # > 920 px at 84 px: must overflow
    arabic_font = fontset.path("arabic")
    ok4, e4 = expect_error(lambda: dna.run(f'adapt language=ar headline="{long_ar}" font="{arabic_font}"'), "fit_conflict")
    _, _, h1 = load_variant(tid, vid)
    patch = o / "arabic-fit.json"
    write_json(patch, {"schema_version": "1.0.0", "base_revision": h1["revision"], "intent": "long Arabic headline, readable fit allowed",
                       "ops": [{"op": "set", "path": "headline.fit", "value": {"policy": "fit", "min_size": 56, "max_lines": 2}},
                               {"op": "adapt", "language": "ar", "contents": {"headline": long_ar.replace("\\n", "\n")},
                                "font": arabic_font}]})
    r = dna.run(f'batch "{patch}"')
    txn = txn_of(r)
    keep_artifacts(o, txn)
    fit = read_json(Path(txn["verification"]["renders"]["candidate"]).with_name("render.report.json"))["fit"]["n-headline"]
    _, _, after = load_variant(tid, vid)
    probe = shaping_probe(after, template_dir(tid), "n-headline", o / "probe")
    write_json(o / "results.json", {"latin_overflow": e1.as_dict() if e1 else None, "missing_glyphs": e2.as_dict() if e2 else None,
                                    "tracking": e3.as_dict() if e3 else None, "arabic_overflow": e4.as_dict() if e4 else None,
                                    "fit": fit, "shaping": probe})
    record(17, "Long-text overflow, Arabic shaping and missing glyphs", {
        "long Latin CTA under strict fit -> fit_conflict, nothing shrunk": ok1,
        "Arabic in a font without Arabic glyphs -> rejected, glyphs listed": ok2,
        "Arabic in a tracked label -> rejected (tracking breaks joining)": ok3,
        "long Arabic under strict fit -> fit_conflict": ok4,
        "nothing committed by the four rejections": h1["revision"] == h0["revision"],
        "declared fit policy: committed, size within [min, declared)": r["status"] == "committed" and fit["status"] == "fitted"
        and 56 <= fit["size"] < fit["declared_size"] or fit,
        "Arabic shaped (joined width differs from ZWNJ-separated) and rtl": abs(probe["joined"] - probe["separated"]) > 1 and probe["direction"] == "rtl" or probe,
    }, [o / "candidate.png", o / "results.json"])


def t18(root, fx, record, expect_error):
    o = folder(root, 18, "token-isolation")
    dna.run(f'use "{T}" for task "Accent token isolation"')
    tid, vid = dna.current()
    _, _, before = load_variant(tid, vid)
    r = dna.run('set tokens.accent.primary = "#FFD400" keep everything else')
    txn = txn_of(r)
    keep_artifacts(o, txn)
    _, _, after = load_variant(tid, vid)
    v = txn["verification"]
    mc, vc = v["model_changes"], v["visual_changes"]
    a, _ = decode(v["renders"]["base"])
    b, _ = decode(v["renders"]["candidate"])
    hero = (slice(430, 1050), slice(140, 940))
    changed_nodes = {x["node"] for x in vc["by_node"]}
    record(18, "Accent token change preserves every unrelated property", {
        "model: only tokens.accent.primary.value changed": mc["actual_changed_paths"] == ["tokens.accent.primary.value"] or mc["actual_changed_paths"],
        "visual dependencies = the two bound fills (declared, authorise no model change)":
            sorted(d["path"] for d in mc["visual_dependencies"]) == ["nodes.n-accent-bar.fill", "nodes.n-cta-pill.fill"] and mc["dependencies"] == [],
        "every node and every other token identical": before["nodes"] == after["nodes"]
        and {k: t for k, t in before["tokens"].items() if k != "accent.primary"} == {k: t for k, t in after["tokens"].items() if k != "accent.primary"},
        "visual: 0 changed pixels outside the bound footprints": vc["outside_influence"] == 0 or vc,
        "visual: changed pixels only in bound nodes + overlapping text/sheen": changed_nodes <= {"n-accent-bar", "n-cta-pill", "n-cta-text", "n-sheen"} or changed_nodes,
        "photo untouched (0 changed pixels in the hero frame)": int((abs(a[hero].astype(int) - b[hero].astype(int)).max(axis=2) > 0).sum()) == 0,
        "compared against the approved template baseline": vc["compared_against"].startswith("approved"),
    }, [o / "visual_diff.png", o / "transaction.json"])


def t19(root, fx, record, expect_error):
    o = folder(root, 19, "image-replacement")
    dna.run(f'use "{T}" for task "Hero replacement"')
    tid, vid = dna.current()
    _, _, before = load_variant(tid, vid)
    r = dna.run(f'replace hero.asset with "{fx / "bag2.png"}" preserve treatment,crop-intent,anchor,mask,effects keep everything else')
    txn = txn_of(r)
    keep_artifacts(o, txn)
    _, _, after = load_variant(tid, vid)
    rb = read_json(Path(txn["verification"]["renders"]["base"]).with_name("render.report.json"))
    ra = read_json(Path(txn["verification"]["renders"]["candidate"]).with_name("render.report.json"))
    hb, ha = node(before, "n-hero"), node(after, "n-hero")
    ok_d, err = expect_error(lambda: dna.run(f'replace hero.asset with "{fx / "bag_baked.png"}" baked=cast_shadow'), "double_shadow")
    _, _, still = load_variant(tid, vid)
    patch = o / "cutout.json"
    write_json(patch, {"schema_version": "1.0.0", "base_revision": still["revision"], "intent": "cutout with its own baked shadow",
                       "ops": [{"op": "set", "path": "hero.effects.cast_shadow.enabled", "value": False},
                               {"op": "replace", "node": "hero", "file": str(fx / "bag_baked.png"), "baked_effects": ["cast_shadow"]}]})
    fixed = dna.run(f'batch "{patch}"')
    rc = read_json(Path(fixed["verification"]["renders"]["candidate"]).with_name("render.report.json"))
    fp = lambda rep: rep["bounds"]["n-hero"]["rendered"]
    shutil.copy2(fixed["verification"]["renders"]["candidate"], o / "cutout.png")
    record(19, "Image replacement keeps crop intent, mask, treatment and shadow handling", {
        "placement (fit + focal = crop intent), mask, treatment, effects, geometry unchanged":
            all(hb[k] == ha[k] for k in ("placement", "mask", "treatment", "effects", "geometry")),
        "aspect change declared (note; authorises nothing)": any(d["path"].endswith(".placement") for d in txn["verification"]["model_changes"]["notes"]),
        "shadow kept: rendered footprint (frame + shadow) identical": fp(rb) == fp(ra) or [fp(rb), fp(ra)],
        "0 changed pixels outside the hero's footprint": txn["verification"]["visual_changes"]["outside_influence"] == 0,
        "baked shadow + live shadow rejected as double_shadow": ok_d and still["revision"] == after["revision"],
        "explicit fix (disable live shadow) commits; footprint shrinks to the frame": fixed["status"] == "committed"
        and fp(rc)[3] < fp(ra)[3],
    }, [o / "visual_diff.png", o / "cutout.png", o / "transaction.json"])


def t22(root, fx, record, expect_error):
    o = folder(root, 22, "svg-export")
    dna.run(f'use "{T}" for task "SVG export"')
    dna.run('set headline.content = "Carry the\\nquiet certainty."')
    tid, vid = dna.current()
    _, _, scene = load_variant(tid, vid)
    e = dna.run("export formats=png,svg")
    m, sv = e["svg_manifest"], e["svg_verification"]
    out_ref = render(scene, template_dir(tid), o / "fonts-referenced", formats=("png", "svg"), name="export", svg_fonts="reference")
    for f in (e["svg"], Path(e["svg"]).with_name(Path(e["svg"]).name + ".manifest.json"), sv["roundtrip_png"]):
        shutil.copy2(f, o / Path(f).name)
    text = Path(e["svg"]).read_text(encoding="utf-8")
    hero = next(x for x in m["elements"] if x["node"] == "n-hero")
    record(22, "Exported SVG: declared contents, self-contained, rendered and compared", {
        "single self-contained file (data URIs, no external references)": m["self_contained"] and "data:image/" in text and "data:font/" in text,
        "every element classified (live text / vector / embedded raster)": len(m["elements"]) == len(scene["nodes"])
        and m["counts"].get("live_text") == 3 and m["counts"].get("embedded_raster") == 1 and m["counts"].get("vector", 0) >= 5 or m["counts"],
        "shadow + treatment declared as filter effects on the raster": {"effect:drop_shadow", "treatment:saturate", "treatment:contrast"} <= set(hero["filter_effects"]),
        "not sold as an editable master": m["is_editable_master"] is False and "scene.json" in m["editability_statement"],
        "exported SVG rendered standalone = PNG export (0 px)": sv["roundtrip_status"] == "pass" or sv["pixels_vs_engine_png"],
        "live text in the SVG equals the model text": sv["live_text_status"] == "pass" or sv["live_text_matches_model"],
        "font-referenced variant declares fonts not embedded and still round-trips here":
            all(not f["embedded"] for f in out_ref["svg_manifest"]["fonts"]) and out_ref["svg_verification"]["roundtrip_status"] == "pass",
    }, [o / Path(e["svg"]).name, o / (Path(e["svg"]).name + ".manifest.json")], notes=f"self-contained svg: {m['bytes']} bytes")


def t20(root, fx, record, expect_error):
    o = folder(root, 20, "bundle-roundtrip")
    lib = Path(root) / "bundle-library"
    b1 = export_bundle(T, lib, "embed")
    # its own folder: in one library the newest export wins by name, and which one is newer depends on the clock
    b2 = export_bundle(T, Path(root) / "bundle-library-fontref", "reference")
    fdirs = [fontset.font_dir()]  # where referenced fonts resolve by hash (the system folders are searched too)
    v1, v2 = validate_bundle(b1["bundle"]), validate_bundle(b2["bundle"], fdirs)
    v2_nosys = validate_bundle(b2["bundle"], search_system=False)
    import zipfile

    with zipfile.ZipFile(b1["bundle"]) as z:
        names = z.namelist()
        manifest = json.loads(z.read("manifest.json"))
    old = store_root()
    removed = old.with_name(old.name + "-removed")
    os.replace(old, removed)  # the working folder is moved out of reach (never deleted)
    fresh = Path(root) / "store-fresh"
    os.environ["DESIGN_DNA_HOME"] = str(fresh)
    empty_before = not (fresh / "templates").exists()
    lb = Library(lib)
    by_name, by_id = lb.find(T), lb.find(TID)
    imp = import_bundle(lib / by_name["bundle"])
    tdir = template_dir(TID)
    passport, scene = read_json(tdir / "passport.json"), read_json(tdir / "scene.json")
    rr = render(scene, tdir, o / "re-render", name="baseline")
    same = pixel_metrics(decode(rr["png"])[0], decode(tdir / passport["baseline_render"]["path"])[0])["unequal_pixels"]
    heads = {vid: read_json(tdir / f"variants/{vid}/variant.json")["head"] for vid in manifest["variants"]}
    edited = next(vid for vid, v in manifest["variants"].items() if v["head"] != v["baseline_revision"])
    dna.session({"template": TID, "variant": edited})
    u = dna.run("undo last")
    imp2 = import_bundle(b2["bundle"], as_id="editorial-fontref", font_dirs=fdirs)
    t2 = template_dir("editorial-fontref")
    rr2 = render(read_json(t2 / "scene.json"), t2, o / "re-render-fontref", name="baseline")
    same2 = pixel_metrics(decode(rr2["png"])[0], decode(tdir / passport["baseline_render"]["path"])[0])["unequal_pixels"]
    write_json(o / "results.json", {"bundles": [b1, b2], "validate": [v1, v2, v2_nosys], "import": [imp, imp2], "moved_store": str(removed),
                                    "library": lb.entries(), "baseline_re_render_unequal_px": [same, same2]})
    tops = {n.split("/")[1] for n in names if n.startswith("template/")}
    record(20, "Portable bundle: export, validate, remove working folder, retrieve by id/name, import, re-render", {
        "bundle holds passport, scene, source, assets, evidence, baseline, variants": {"passport.json", "scene.json", "source", "assets",
                                                                                       "evidence", "baseline", "variants"} <= tops or tops,
        "render caches excluded; every file hash-listed": not any("/renders/" in n for n in names) and len(manifest["files"]) == len(names) - 1,
        "both bundles validate (fonts embedded / referenced by hash)": v1["valid"] and v2["valid"] or [v1["errors"], v2["errors"]],
        "referenced fonts with no font source -> explicit missing-font errors": not v2_nosys["valid"] and any("not found" in e for e in v2_nosys["errors"]),
        "working folder moved away; fresh store empty before import": not old.exists() and empty_before,
        "library retrieval by name and by stable id agree": by_name["bundle"] == by_id["bundle"],
        "import restores the template; approved baseline re-renders identically (0 px)": imp["status"] == "imported" and same == 0 or [imp, same],
        "variants + revision history restored": heads == {k: v["head"] for k, v in manifest["variants"].items()},
        "undo works on an imported variant": isinstance(u.get("head"), int),
        "font-referenced bundle imports (fonts resolved by hash) and renders identically": imp2["status"] == "imported" and same2 == 0 or [imp2, same2],
    }, [o / "results.json"], notes=f"original working store moved to {removed}")


def launchable(channel) -> bool:
    from playwright.sync_api import sync_playwright

    from common import DnaError
    from renderer_env import launch

    try:
        with sync_playwright() as p:
            launch(p, channel)[0].close()
        return True
    except DnaError:
        return False


def t21(root, fx, record, expect_error):
    o = folder(root, 21, "renderer-drift")
    lib = Path(root) / "bundle-library"
    e = Library(lib).find(T)
    import_bundle(lib / e["bundle"], as_id="drift-probe")
    tdir = template_dir("drift-probe")
    scene, pp = read_json(tdir / "scene.json"), read_json(tdir / "passport.json")
    pin = pp["render_pin"]
    sim = dict(pp, render_pin=dict(pin, browser_version="0.0.0.0-simulated"))
    write_json(tdir / "passport.json", sim)
    ok_sim, err_sim = expect_error(lambda: render(scene, tdir, o / "should-not-render"), "renderer_drift")
    write_json(tdir / "passport.json", pp)
    results = {"simulated": err_sim.as_dict() if err_sim else None}
    other = next((ch for ch in ("msedge", "chrome", "chromium") if ch != pin["channel"] and launchable(ch)), "msedge")
    os.environ["DESIGN_DNA_BROWSER"] = other
    try:
        ok_real, err_real = expect_error(lambda: render(scene, tdir, o / "should-not-render-2"), "renderer_drift")
        if not ok_real and err_real and err_real.code == "renderer_unavailable":
            record(21, "Renderer version drift", {}, status="unverified",
                   notes=f"no browser channel besides the pinned {pin['channel']} is installed: real channel drift UNVERIFIED")
            return
        m = new_variant("drift-probe", "edit under drift")
        _, _, head = load_variant("drift-probe", m["id"])
        ok_edit, err_edit = expect_error(lambda: transact("drift-probe", m["id"], {"schema_version": "1.0.0", "base_revision": head["revision"],
                                                                                    "ops": [{"op": "move", "node": "logo", "dx": -4, "dy": 0}]}), "renderer_drift")
        preview = dna.migrate_baseline("drift-probe")
        unchanged = read_json(tdir / "passport.json")["render_pin"] == pin
        done = dna.migrate_baseline("drift-probe", confirm=True, preview_id=preview["preview_id"])
        after = read_json(tdir / "passport.json")
        ok_new = render(scene, tdir, o / "renders-after-migration", name="baseline")["pin_check"]["status"] == "match"
    finally:
        os.environ.pop("DESIGN_DNA_BROWSER", None)
    os.environ["DESIGN_DNA_BROWSER"] = pin["channel"]  # the formerly pinned browser is now the drift
    try:
        ok_back, _ = expect_error(lambda: render(scene, tdir, o / "should-not-render-3"), "renderer_drift")
    finally:
        os.environ.pop("DESIGN_DNA_BROWSER", None)
    results.update(real=err_real.as_dict() if err_real else None, edit=err_edit.as_dict() if err_edit else None, preview=preview, migrated=done)
    write_json(o / "results.json", results)
    fields = {d["field"] for d in (err_real.detail["hard"] if err_real else [])}
    record(21, "Renderer drift is detected, reported and needs an explicit migration", {
        "simulated browser-version change -> renderer_drift (nothing rendered)": ok_sim and not (o / "should-not-render" / "render.png").exists(),
        f"real switch to {other} -> renderer_drift naming channel + version": ok_real and {"channel", "browser_version"} <= fields or fields,
        "an edit under drift is rejected (no silent switch)": ok_edit,
        "migration preview reports pixel differences and changes nothing": preview["status"] == "migration_required" and unchanged
        and preview["vs_approved_baseline"]["unequal_pixels"] is not None,
        "confirmed migration records old pin, new pin and differences": done["status"] == "migrated" and after["render_pin"]["channel"] == other
        and len(after.get("render_migrations", [])) == 1,
        "old approved baseline kept on disk": (tdir / pp["baseline_render"]["path"]).exists(),
        "new environment now matches; the old one is now the drift": ok_new and ok_back,
    }, [o / "results.json"], notes=f"pinned {pin['channel']} {pin['browser_version']} -> {other}; "
                                   f"{preview['vs_approved_baseline']['unequal_pixels']} px differ between renderers")


def run(root, fx, record, want, expect_error):
    for n, fn in ((15, t15), (16, t16), (17, t17), (18, t18), (19, t19), (22, t22), (20, t20), (21, t21)):
        if not want(n):
            continue
        try:
            fn(root, fx, record, expect_error)
        except Exception as e:  # a crash is a failed demonstration
            record(n, f"crashed: T{n:02d}", {"ran without crashing": crash.reason(e)}, notes=traceback.format_exc()[-1500:])
    if want(23):
        record(23, "Host persistent storage (e.g. ChatGPT Work file store) as a bundle backend", {}, status="unverified",
               notes="Bundles + FilesystemBackend are implemented and tested (T20). A host file store needs an adapter with "
                     "put/get/list; no such host was available here, so the integration is UNVERIFIED.")
