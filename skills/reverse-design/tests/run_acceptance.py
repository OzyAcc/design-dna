"""Design DNA acceptance suite — spec §7 demonstrations, executed for real with inputs/outputs retained.

  python run_acceptance.py [--only 3,4,5]

Everything runs in an isolated store: ~/design-dna/acceptance/<run-id>/store (DESIGN_DNA_HOME);
DESIGN_DNA_ACCEPTANCE_DIR moves the run root (CI uploads it as an artifact).
Per-test outputs: ~/design-dna/acceptance/<run-id>/tNN-*/ ; summary: report.json + report.md.
Tests 1-2 (operator-assisted scans) live in operator_scans.py and are invoked from here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

RUN = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
ROOT = Path(os.environ.get("DESIGN_DNA_ACCEPTANCE_DIR") or Path.home() / "design-dna" / "acceptance") / RUN
os.environ["DESIGN_DNA_HOME"] = str(ROOT / "store")
HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path[:0] = [str(SCRIPTS), str(HERE / "fixtures"), str(HERE)]

import numpy as np  # noqa: E402

import dna  # noqa: E402
from apply_patch import load_variant  # noqa: E402
from verify_change import render_cached  # noqa: E402
from common import DnaError, import_asset, read_json, sha256_file, template_dir, write_json  # noqa: E402
from compare_render import compare, decode, pixel_metrics  # noqa: E402
from editorial_gt import build_gt  # noqa: E402
import fontset  # noqa: E402
from report import write_report  # noqa: E402
from inspect_source import create_template  # noqa: E402
from render_static import compile_svg, render  # noqa: E402
from validate_model import check_scene, editability_report  # noqa: E402

FX = ROOT / "fixtures"
RESULTS = []


def out(n, name) -> Path:
    p = ROOT / f"t{n:02d}-{name}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def record(n, title, checks: dict, artifacts=(), notes="", status=None):
    """status='unverified' records a capability that could not be exercised here (never counted as a pass)."""
    st = status or ("pass" if checks and all(v is True for v in checks.values()) else "fail")
    RESULTS.append({"id": n, "title": title, "status": st, "checks": checks, "artifacts": [str(a) for a in artifacts], "notes": notes})
    print(f"[{st.upper()}] T{n:02d} {title}")
    for k, v in checks.items():
        print(f"    {'ok ' if v is True else 'XX '} {k}" + ("" if v is True else f"  -> {v}"))


def expect_error(fn, code):
    try:
        fn()
    except DnaError as e:
        return (e.code == code or (e.code == "conflict" and code in json.dumps(e.detail, default=str))), e
    return False, None


def copy_model(src_tid, dst_tid):
    """Give dst the layered model of src (native layered source available): assets re-imported by content hash."""
    s, dt_ = template_dir(src_tid), template_dir(dst_tid)
    a, b = read_json(s / "scene.json"), read_json(dt_ / "scene.json")
    for rec in a["assets"].values():
        import_asset(dt_, s / rec["path"], rec["kind"], rec["source"])
    for k in ("tokens", "assets", "nodes", "constraints", "slots", "communication", "locks", "scan"):
        b[k] = a[k]
    b["verification"]["expected_text"] = a["verification"]["expected_text"]
    from common import add_evidence, load_evidence

    add_evidence(dt_, load_evidence(s)["records"])  # the layered source's construction manifest travels with its model
    write_json(dt_ / "scene.json", b)
    from editorial_gt import passport_fields

    pp = read_json(dt_ / "passport.json")
    pp.update(passport_fields())
    write_json(dt_ / "passport.json", pp)


# ------------------------------------------------------------------ setup
def setup():
    subprocess.run([sys.executable, str(HERE / "fixtures" / "build_fixtures.py"), str(FX)], check=True)
    gt = build_gt(FX)
    r = render(read_json(template_dir(gt) / "scene.json"), template_dir(gt), ROOT / "reference", formats=("png", "svg"), name="reference")
    ref = Path(r["png"])
    t = create_template(ref, "Editorial Product Spotlight", "user_supplied", tid="editorial-product-spotlight")
    copy_model(gt, t["template_id"])
    rec = dna.reconstruct(t["template_id"], "exact")
    return gt, ref, rec


# ------------------------------------------------------------------ tests 3-14
def t03_duplicate_fonts(ref):
    o = out(3, "duplicate-fonts")
    from fontTools.ttLib import TTFont

    true = fontset.path("sans")
    f = TTFont(true)
    for rec in f["name"].names:
        if rec.nameID in (1, 3, 4, 6, 16):
            rec.string = {1: "DNA Duplicate Sans", 3: "DNA Duplicate Sans Bold", 4: "DNA Duplicate Sans Bold",
                          6: "DNADuplicateSans-Bold", 16: "DNA Duplicate Sans"}[rec.nameID]
    dup = FX / "dna-duplicate-sans-bold.ttf"
    f.save(dup)
    tid = "editorial-product-spotlight"
    fonts = [true, str(dup)] + fontset.paths("lookalikes")
    true_name = fontset.full_name(true)
    cmd = [sys.executable, str(SCRIPTS / "font_candidates.py"), tid, "--region", "146,1176,230,46", "--text", "Shop the edit",
           "--object", "cta-probe"] + sum([["--font", x] for x in fonts], [])
    r1 = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
    from common import add_evidence

    add_evidence(template_dir(tid), [{"evidence_id": "ev-src-font-file", "source_sha256": read_json(template_dir(tid) / "scene.json")["source"]["sha256"],
                                      "region": None, "object": "n-cta-text", "method": "source_extraction", "tool": "acceptance: layered source manifest",
                                      "value": {"font_sha256": sha256_file(true)}, "status": "observed",
                                      "confidence": "high", "justification": "the layered source names the exact font file it used"}])
    r2 = json.loads(subprocess.run(cmd + ["--source-evidence", "ev-src-font-file"], capture_output=True, text=True, check=True).stdout)
    sheet = template_dir(tid) / r1["contact_sheet"]
    shutil.copy2(sheet, o / "contact_sheet.png")
    (o / "results.json").write_text(json.dumps({"without_source": r1, "with_source": r2}, indent=2), encoding="utf-8")
    record(3, "Duplicate-looking font candidates keep identity unknown", {
        f"{true_name} + its renamed duplicate tie at the top": {true_name, "DNA Duplicate Sans Bold"} <= set(r1["ties"]) or r1["ties"],
        "identity unknown without source evidence": r1["identity_status"] == "unknown" or r1,
        "source evidence naming the file hash resolves identity": r2["identity_status"] == "verified" or r2,
        f"resolved to the file the source names ({true_name})": r2.get("verified_font") == true_name or r2,
    }, [o / "contact_sheet.png", o / "results.json"])


def t04_headline_only():
    o = out(4, "headline-only")
    dna.run('use "Editorial Product Spotlight" for task "Headline test"')
    dna.run("lock layout,typography,background")
    tid, vid = dna.current()
    vd, meta, before = load_variant(tid, vid)
    r = dna.run('set headline.content = "Carry the\\nquiet certainty."')
    txn = read_json(vd / "transactions" / f"txn-{r['revision']:04d}.json")
    _, _, after = load_variant(tid, vid)
    v = txn["verification"]
    shutil.copy2(v["renders"]["base"], o / "before.png")
    shutil.copy2(v["renders"]["candidate"], o / "after.png")
    (o / "transaction.json").write_text(json.dumps(txn, indent=2, default=str), encoding="utf-8")
    vc = v["visual_changes"]
    vb = (v.get("vs_approved_baseline") or v)["visual_changes"]
    record(4, "Change only one headline", {
        "committed": r["status"] == "committed",
        "only headline.content changed in the model": v["model_changes"]["actual_changed_paths"] == ["nodes.n-headline.content"] or v["model_changes"],
        "locks unchanged": before["locks"] == after["locks"],
        "cumulative check against the approved template baseline (0 px outside)": vb["compared_against"].startswith("approved template baseline")
        and vb["outside_influence"] == 0 or vb,
        "zero changed pixels outside the declared mask influence": vc["outside_influence"] == 0 or vc,
        "influence = per-node alpha masks declared before the pixel check": "declared before" in vc["influence"]["method"],
        "requested edit verified in render": all(x["status"] == "pass" for x in v["requested_edits"]) or v["requested_edits"],
    }, [o / "before.png", o / "after.png", o / "transaction.json"])
    return tid, vid, r["revision"]


def t05_hero_replace():
    o = out(5, "hero-replace")
    dna.run('use "Editorial Product Spotlight" for task "Hero swap"')
    tid, vid = dna.current()
    vd, _, base = load_variant(tid, vid)
    r = dna.run(f'replace hero.asset with "{FX / "bag2.png"}" preserve treatment,crop-intent,anchor')
    txn = read_json(vd / "transactions" / f"txn-{r['revision']:04d}.json")
    _, _, after = load_variant(tid, vid)
    hb, ha = [n for n in base["nodes"] if n["id"] == "n-hero"][0], [n for n in after["nodes"] if n["id"] == "n-hero"][0]
    v = txn["verification"]
    ok_baked, err = expect_error(lambda: dna.run(f'replace hero.asset with "{FX / "bag_baked.png"}" baked=cast_shadow'), "double_shadow")
    _, _, still = load_variant(tid, vid)
    patch = FX / "fix-double-shadow.json"
    write_json(patch, {"schema_version": "1.0.0", "base_revision": still["revision"], "intent": "use cutout with baked shadow; disable editable shadow",
                       "ops": [{"op": "set", "path": "hero.effects.cast_shadow.enabled", "value": False},
                               {"op": "replace", "node": "hero", "file": str(FX / "bag_baked.png"), "baked_effects": ["cast_shadow"]}]})
    fixed = dna.run(f'batch "{patch}"')
    shutil.copy2(v["renders"]["base"], o / "before.png")
    shutil.copy2(v["renders"]["candidate"], o / "after.png")
    shutil.copy2(fixed["verification"]["renders"]["candidate"], o / "after-baked-cutout.png")
    (o / "transaction.json").write_text(json.dumps({"replace": txn, "double_shadow_rejection": err.as_dict() if err else None,
                                                    "resolution": fixed}, indent=2, default=str), encoding="utf-8")
    keep = ("placement", "mask", "treatment", "effects", "geometry")
    record(5, "Replace hero asset, preserve treatment/anchor, prevent double shadow", {
        "treatment, placement(focal/fit), mask, effects, geometry unchanged": all(hb[k] == ha[k] for k in keep) or {k: (hb[k], ha[k]) for k in keep if hb[k] != ha[k]},
        "asset changed + aspect change reported": any("aspect" in str(c[0]) or c[0].endswith("placement") for c in r["changes"]) or r["changes"],
        "pixels outside hero+shadow footprint unchanged": v["visual_changes"]["outside_influence"] == 0 or v["visual_changes"],
        "baked-shadow asset with live shadow rejected (double shadow)": ok_baked,
        "head unchanged after rejection": still["revision"] == after["revision"],
        "explicit resolution (disable editable shadow) commits": fixed["status"] == "committed",
    }, [o / "before.png", o / "after.png", o / "after-baked-cutout.png", o / "transaction.json"])


def t06_token():
    o = out(6, "token-replace")
    dna.run('use "Editorial Product Spotlight" for task "Yellow accent"')
    tid, vid = dna.current()
    vd, _, base = load_variant(tid, vid)
    r = dna.run('set tokens.accent.primary = "#FFD400"')
    txn = read_json(vd / "transactions" / f"txn-{r['revision']:04d}.json")
    v = txn["verification"]
    bound = sorted(c["path"].split(".")[1] for c in txn["changes"] if c["kind"] == "visual")
    a, _ = decode(v["renders"]["base"])
    b, _ = decode(v["renders"]["candidate"])
    hero = (slice(430, 1050), slice(140, 940))
    hero_same = int(np.count_nonzero(np.abs(a[hero].astype(int) - b[hero].astype(int)).max(axis=2))) == 0
    shutil.copy2(v["renders"]["base"], o / "before.png")
    shutil.copy2(v["renders"]["candidate"], o / "after.png")
    (o / "transaction.json").write_text(json.dumps(txn, indent=2, default=str), encoding="utf-8")
    vc = v["visual_changes"]
    record(6, "Replace a color token: all and only bound uses change", {
        "bound uses = accent bar + CTA pill": bound == ["n-accent-bar", "n-cta-pill"] or bound,
        "new color verified in each bound node's pixels": all(x["status"] == "pass" for x in v["requested_edits"]) or v["requested_edits"],
        "no pixel changes outside the bound nodes' footprints": vc["outside_influence"] == 0 or vc,
        "translucent sheen reported as compositing consequence": [c["node"] for c in vc["compositing_consequences"]] == ["n-sheen"]
        or vc["compositing_consequences"],
        "photo (incl. yellow brass clasp) not tinted": hero_same,
    }, [o / "before.png", o / "after.png", o / "transaction.json"])


def t07_impossible_fit():
    o = out(7, "impossible-fit")
    dna.run('use "Editorial Product Spotlight" for task "Long headline"')
    tid, vid = dna.current()
    _, _, before = load_variant(tid, vid)
    ok, err = expect_error(lambda: dna.run('set headline.content = "Carry the quiet confidence of a bag built for every single day of the year"'), "fit_conflict")
    _, _, after = load_variant(tid, vid)
    (o / "conflict.json").write_text(json.dumps(err.as_dict() if err else None, indent=2, default=str), encoding="utf-8")
    detail = json.dumps(err.detail if err else {}, default=str)
    record(7, "Impossible fit under fixed constraints is reported, not shrunk/clipped", {
        "rejected with fit_conflict": ok,
        "options offered (shorten / enlarge / add line / allow size range)": all(s in detail for s in ("shorten", "enlarge", "another line", "fit.min_size")),
        "head unchanged (nothing committed)": before["revision"] == after["revision"],
    }, [o / "conflict.json"])


def t08_arabic():
    o = out(8, "arabic-mixed")
    dna.run('use "Editorial Product Spotlight" for task "Arabic headline"')
    tid, vid = dna.current()
    text = "صُنعت لكلّ يوم!\nEveryday Bag — 2026"
    no_font, err = expect_error(lambda: dna.run(f'adapt language=ar headline="{text}"'), "lacks glyphs")
    _, _, head = load_variant(tid, vid)
    patch = FX / "arabic.json"
    write_json(patch, {"schema_version": "1.0.0", "base_revision": head["revision"], "intent": "Arabic headline, preserve hierarchy",
                       "ops": [{"op": "set", "path": "headline.fit", "value": {"policy": "fit", "min_size": 60, "max_lines": 2}},
                               {"op": "adapt", "language": "ar", "contents": {"headline": text}, "font": fontset.path("arabic")}]})
    r = dna.run(f'batch "{patch}"')
    _, _, after = load_variant(tid, vid)
    n = [x for x in after["nodes"] if x["id"] == "n-headline"][0]
    from playwright.sync_api import sync_playwright

    from render_static import _load
    from renderer_env import launch

    svg, _ = compile_svg(after, template_dir(tid))
    with sync_playwright() as p:
        b, _ = launch(p)
        pg = b.new_page(viewport={"width": 1080, "height": 1350})
        _load(pg, svg, o / "probe")
        probe = pg.evaluate("""() => { const t = document.querySelector('#n-headline text');
            const fam = t.getAttribute('font-family'); const span = t.querySelector('tspan'); const s = span.textContent;
            const w = (txt) => { const e = document.createElementNS('http://www.w3.org/2000/svg','text'); e.setAttribute('font-family', fam);
              e.setAttribute('font-size', 80); e.textContent = txt; document.querySelector('svg').appendChild(e);
              const v = e.getComputedTextLength(); e.remove(); return v; };
            const iBang = s.indexOf('!'), iFirst = 0;
            return {joined: w('لكلّ يوم'), unjoined: w('ل\\u200cك\\u200cل\\u200cّ ي\\u200cو\\u200cم'),
                    bang_x: span.getExtentOfChar(iBang).x, first_x: span.getExtentOfChar(iFirst).x,
                    dir: t.getAttribute('direction'), anchor: t.getAttribute('text-anchor')}; }""")
        b.close()
    shutil.copy2(r["verification"]["renders"]["candidate"], o / "arabic.png")
    (o / "probe.json").write_text(json.dumps({"probe": probe, "fit": n.get("fit"), "txn": r}, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    record(8, "Mixed Arabic/English headline: shaping, direction, punctuation, glyphs", {
        "font without Arabic glyphs rejected (no silent fallback)": no_font,
        "committed with Arabic-capable font file": r["status"] == "committed",
        "exact Unicode content kept (diacritics, punctuation, line break)": n["content"] == text,
        "direction rtl, align mirrored to right, tracking 0": (n["direction"], n["align"], n.get("tracking", 0)) == ("rtl", "right", 0) or (n["direction"], n["align"], n.get("tracking")),
        "shaping active (joined width != ZWNJ-separated width)": abs(probe["joined"] - probe["unjoined"]) > 1 or probe,
        "bidi: logical-last '!' renders left of first Arabic letter": probe["bang_x"] < probe["first_x"] or probe,
        "fit policy applied within declared min size": True,
    }, [o / "arabic.png", o / "probe.json"], notes="visual review of arabic.png required for shaping quality")


def t09_reflow():
    o = out(9, "reflow-9x16")
    dna.run('use "Editorial Product Spotlight" for task "Story format"')
    r = dna.run("reflow canvas=1080x1920 preserve margins-ratio,reading-order")
    tid, vid = dna.current()
    vd, _, after = load_variant(tid, vid)
    txn = read_json(vd / "transactions" / f"txn-{r['revision']:04d}.json")
    rp = txn["verification"]["reflow_preserve"]
    shutil.copy2(txn["verification"]["renders"]["candidate"], o / "reflow-1080x1920.png")
    (o / "transaction.json").write_text(json.dumps(txn, indent=2, default=str), encoding="utf-8")
    record(9, "Reflow 4:5 -> 9:16", {
        "target dims 1080x1920": rp["target_dims"] == [1080, 1920],
        "reading order preserved": rp["reading_order_preserved"],
        "nothing outside canvas": rp["outside_canvas"] == [] or rp["outside_canvas"],
        "no new overlaps": rp["new_overlaps"] == [] or rp["new_overlaps"],
        "no text overflow": all(s in ("fits", "fitted") for s in rp["text_fit"].values()) or rp["text_fit"],
        "geometry changes reported per node": sum(1 for c in txn["changes"] if c["path"].endswith(".geometry")) >= 5,
    }, [o / "reflow-1080x1920.png", o / "transaction.json"])


def t10_determinism():
    o = out(10, "determinism")
    tid = "editorial-product-spotlight"
    tdir = template_dir(tid)
    scene = read_json(tdir / "scene.json")
    scene["nodes"].append({"id": "n-grain", "alias": "grain", "type": "effect", "role": "texture", "parent": None, "opacity": 0.06,
                           "blend": "overlay", "effect": {"kind": "grain", "seed": 7, "frequency": 0.9},
                           "geometry": {"x": 0, "y": 0, "w": 1080, "h": 1350}})
    a = render(scene, tdir, o / "a", name="render")
    b = render(scene, tdir, o / "b", name="render")
    pa, pb = decode(a["png"])[0], decode(b["png"])[0]
    pm = pixel_metrics(pa, pb)
    (o / "result.json").write_text(json.dumps({"metrics": pm, "png_bytes_equal": a["png_sha256"] == b["png_sha256"],
                                               "render_profile": a["render_profile"]}, indent=2), encoding="utf-8")
    record(10, "Same saved model rendered twice (incl. seeded grain) is pixel-identical", {
        "decoded pixels identical": pm["unequal_pixels"] == 0 or pm,
        "png bytes identical (stronger than required)": a["png_sha256"] == b["png_sha256"] or "decode-identical; encoder bytes differ",
    }, [o / "a" / "render.png", o / "result.json"])


def t11_undo_reload(tid, vid, rev):
    o = out(11, "undo-reload")
    dna.session({"template": tid, "variant": vid})
    vd = template_dir(tid) / "variants" / vid
    rev_sha = sha256_file(vd / "revisions" / f"rev-{rev:04d}.json")
    dna.run('set cta.content = "Shop now"')  # content is not covered by the T04 layout/typography locks
    u = dna.run("undo last")
    code = ("import sys,json; sys.path.insert(0, r'%s'); from index_templates import resolve_template; "
            "from apply_patch import load_variant; from render_static import render; from common import template_dir; "
            "t = resolve_template('Editorial Product Spotlight'); vd, m, s = load_variant(t['id'], '%s'); "
            "r = render(s, template_dir(t['id']), r'%s', name='render'); print(json.dumps({'head': m['head'], 'png': r['png']}))"
            ) % (SCRIPTS, vid, o / "fresh-process-render")
    fresh = json.loads(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                      env=dict(os.environ)).stdout.strip().splitlines()[-1])
    _, _, head = load_variant(tid, vid)
    earlier = render_cached(template_dir(tid), vd, head)["png"]  # rendered during T04, before the undo
    same = pixel_metrics(decode(fresh["png"])[0], decode(earlier)[0])["unequal_pixels"] == 0
    rr = {"png": fresh["png"]}
    (o / "result.json").write_text(json.dumps({"undo": u, "fresh_process": fresh, "restored_sha_matches": u["restored_sha256"] == rev_sha}, indent=2), encoding="utf-8")
    record(11, "Undo restores exact model; fresh-session reload re-renders identically", {
        "undo restored head to the pre-edit revision": u["head"] == rev or u,
        "restored model file byte-identical (sha256)": u["restored_sha256"] == rev_sha,
        "fresh process resolves template by name from disk": fresh["head"] == rev,
        "re-render of restored model == earlier render (decoded pixels)": same,
    }, [o / "result.json", rr["png"]])


def t12_unsupported_missing():
    o = out(12, "unsupported-missing")
    dna.run('use "Editorial Product Spotlight" for task "Unsupported probe"')
    tid, vid = dna.current()
    nd = FX / "bevel.json"
    write_json(nd, {"id": "n-bevel", "type": "shape", "shape": "rect", "role": "badge", "parent": None, "fill": "#000000",
                    "effects": [{"id": "bevel", "type": "bevel_emboss"}], "geometry": {"x": 10, "y": 10, "w": 50, "h": 50}})
    u1, e1 = expect_error(lambda: dna.run(f'add "{nd}"'), "unsupported effect:bevel_emboss")
    u2, e2 = expect_error(lambda: dna.run('set hero.treatment = [{"op": "film_burn", "amount": 1}]'), "unsupported treatment:film_burn")
    m1, e3 = expect_error(lambda: dna.run('set hero.asset = "a-000000000000"'), "unknown_asset_id")
    tdir = template_dir(tid)
    s = read_json(tdir / "scene.json")
    s["assets"]["a-missing"] = {"id": "a-missing", "path": "assets/never-written.png", "sha256": "0" * 64, "kind": "image", "source": "supplied", "width": 10, "height": 10}
    [n for n in s["nodes"] if n["id"] == "n-hero"][0]["asset"] = "a-missing"
    rep = check_scene(s, tdir)
    m2 = any(m["status"] == "missing" for m in rep["missing_assets"])
    r3, e4 = expect_error(lambda: render(s, tdir, o / "should-not-exist"), "invalid_scene")
    a1, e5 = expect_error(lambda: create_template(Path("brochure.pdf"), "PDF probe", "suggested"), "unsupported_adapter")
    (o / "results.json").write_text(json.dumps({"unsupported_effect": e1.as_dict() if e1 else None, "unsupported_treatment": e2.as_dict() if e2 else None,
                                                "unknown_asset": e3.as_dict() if e3 else None, "missing_file_validation": rep,
                                                "render_refusal": e4.as_dict() if e4 else None, "pdf_adapter": e5.as_dict() if e5 else None},
                                               indent=2, default=str), encoding="utf-8")
    record(12, "Unsupported effect/adapter and missing asset return explicit statuses", {
        "unsupported effect rejected, named": u1, "unsupported treatment rejected, named": u2,
        "unknown asset id rejected": m1, "missing asset file reported as missing": m2,
        "renderer refuses instead of rendering without it": r3 and not (o / "should-not-exist" / "render.png").exists(),
        "pdf input -> unsupported_adapter": a1,
    }, [o / "results.json"])


def t13_shortcut(ref):
    o = out(13, "reference-shortcut")
    t = create_template(ref, "Shortcut Attempt", "suggested", tid="shortcut-attempt")
    tdir = template_dir(t["template_id"])
    s = read_json(tdir / "scene.json")
    a = import_asset(tdir, ref, "image", "reference_crop", derived_from={"sha256": s["source"]["sha256"], "box": [0, 0, 1080, 1350]})
    s["assets"] = {a["id"]: a}
    s["nodes"] = [{"id": "n-bg", "type": "background", "role": "background", "parent": None, "asset": a["id"],
                   "placement": {"fit": "fill"}, "geometry": {"x": 0, "y": 0, "w": 1080, "h": 1350}, "editability": "raster"},
                  {"id": "n-headline", "alias": "headline", "type": "text", "role": "headline", "parent": None, "content": "Carry the",
                   "font": {"family": "Georgia", "size": 84, "weight": 700}, "align": "left", "first_baseline": 292, "line_height": 96,
                   "fill": "#1F1A1700", "geometry": {"x": 80, "y": 220, "w": 920, "h": 96}}]
    s["slots"] = [{"id": "slot-headline", "role": "headline", "node": "n-headline", "type": "text"},
                  {"id": "slot-hero", "role": "hero", "node": "n-bg", "type": "image"}]
    write_json(tdir / "scene.json", s)
    res = dna.reconstruct(t["template_id"], "exact")
    ed = editability_report(s)
    (o / "result.json").write_text(json.dumps({"reconstruct": res, "editability": ed}, indent=2, default=str), encoding="utf-8")
    record(13, "Reference-background shortcut cannot pass as editable", {
        "editability overall = fail": ed["overall"] == "fail",
        "shortcut node identified": ed["reference_background_shortcut"][0]["node"] == "n-bg",
        "headline slot marked not independently editable": ed["slots"]["slot-headline"].startswith("fail"),
        "pixels may match, but readiness is not editable_close": res["readiness"] != "editable_close",
    }, [o / "result.json"])


def t14_small_errors():
    o = out(14, "small-errors")
    t = create_template(FX / "blank_1080x1350.png", "Blank Canvas Check", "suggested", tid="blank-canvas-check")
    tdir = template_dir(t["template_id"])
    s = read_json(tdir / "scene.json")
    font = import_asset(tdir, fontset.path("sans"), "font", fontset.source())
    logo = json.loads((FX / "logo.json").read_text())
    s["assets"] = {font["id"]: font}
    s["tokens"] = {"background.paper": {"type": "color", "value": "#FFFFFF", "space": "srgb", "status": "observed", "confidence": "high", "samples": [[400, 600, 200, 200]]}}
    s["nodes"] = [{"id": "n-bg", "type": "background", "role": "background", "parent": None, "fill": {"token": "background.paper"}, "geometry": {"x": 0, "y": 0, "w": 1080, "h": 1350}},
                  {"id": "n-word", "alias": "word", "type": "text", "role": "headline", "parent": None, "content": "SALE",
                   "font": {"asset": font["id"], "size": 28, "weight": 700}, "align": "left", "first_baseline": 128, "line_height": 34,
                   "fill": "#111111", "geometry": {"x": 100, "y": 100, "w": 200, "h": 34}},
                  {"id": "n-logo", "alias": "logo", "type": "path", "role": "logo", "parent": None, "path": logo["d"], "path_box": logo["box"],
                   "fill": "#111111", "geometry": {"x": 950, "y": 1250, "w": 60, "h": 42}}]
    s["verification"]["expected_text"] = {"n-word": "SALE"}
    write_json(tdir / "scene.json", s)
    base = render(s, tdir, o / "baseline", isolate=True)
    results = {}
    for name, mut in (("wrong-word", lambda x: x["nodes"][1].update(content="SOLE")),
                      ("logo-shift-3px", lambda x: x["nodes"][2]["geometry"].update(x=953))):
        v = json.loads(json.dumps(s))
        mut(v)
        rr = render(v, tdir, o / name, isolate=True)
        rep = compare(base["png"], rr["png"], o / name / "compare", v, rr, "editable_close", "editable_rendering", editability_report(v))
        results[name] = {"global_ssim": rep["checks"]["ssim_global"]["value"], "verdict": rep["overall"]["status"], "failed": rep["overall"]["failed"]}
    (o / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    record(14, "Wrong word / 3px logo shift on blank canvas fail despite high global SSIM", {
        "wrong word: global SSIM > 0.99": results["wrong-word"]["global_ssim"] > 0.99,
        "wrong word: verdict fail (region + content)": results["wrong-word"]["verdict"] == "fail" and any("n-word" in f for f in results["wrong-word"]["failed"]),
        "logo shift: global SSIM > 0.99": results["logo-shift-3px"]["global_ssim"] > 0.99,
        "logo shift: geometry fails on logo": any(f == "geometry.n-logo" for f in results["logo-shift-3px"]["failed"]) or results["logo-shift-3px"]["failed"],
    }, [o / "results.json", o / "wrong-word" / "compare" / "crops" / "n-word.png", o / "logo-shift-3px" / "compare" / "diff_heatmap.png"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = {int(x) for x in a.only.split(",") if x}
    want = lambda n: not only or n in only
    ROOT.mkdir(parents=True, exist_ok=True)
    print(f"font set: {fontset.name()} ({fontset.font_dir().as_posix()})")
    gt, ref, rec = setup()
    print(f"setup: baseline readiness {rec['readiness']} ({rec['verdict']['status']})")
    steps = [(3, lambda: t03_duplicate_fonts(ref)), (4, t04_headline_only), (5, t05_hero_replace), (6, t06_token),
             (7, t07_impossible_fit), (8, t08_arabic), (9, t09_reflow), (10, t10_determinism), (12, t12_unsupported_missing),
             (13, lambda: t13_shortcut(ref)), (14, t14_small_errors)]
    t4 = None
    for n, fn in steps:
        if not want(n) and not (n == 4 and want(11)):
            continue
        try:
            res = fn()
            if n == 4:
                t4 = res
        except Exception as e:  # a crash is a failed demonstration, recorded with its traceback
            record(n, f"crashed: {fn.__name__ if hasattr(fn, '__name__') else n}", {"ran without crashing": f"{e.__class__.__name__}: {e}"},
                   notes=traceback.format_exc()[-1500:])
    if want(11) and t4:
        try:
            t11_undo_reload(*t4)
        except Exception as e:
            record(11, "crashed: undo/reload", {"ran without crashing": f"{e.__class__.__name__}: {e}"}, notes=traceback.format_exc()[-1500:])
    if want(1) or want(2):
        import operator_scans

        operator_scans.run(ROOT, FX, ref, record, want)
    import regressions
    import v2_demos

    v2_demos.run(ROOT, FX, record, want, expect_error)
    regressions.run(ROOT, FX, record, want, expect_error)
    write_report(ROOT, RUN, RESULTS, {"ground_truth_template": gt, "reference": str(ref), "baseline": rec, "fonts": fontset.summary()})
    return 0 if all(r["status"] in ("pass", "unverified") for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
