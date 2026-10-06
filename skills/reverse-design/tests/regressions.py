"""Audit regression demonstrations (24-33): one per finding of the 2026-10-06 repository audit.

24 F1 empty scan / missing evidence never passes · 25 F1 page assembled from reference fragments, baked content ·
26 F2 ancestor replacement + node removal under locks · 27 F3 hostile model data + normal OpenType settings ·
28 F4 alpha counts in identity and preservation · 29 F5/F7 relocated + corrupted render caches ·
30 F6 EXIF orientations 5-8 · 31 text stroke rendered, unsupported stroke rejected ·
32 immutable baselines and exports · 33 capability report does not claim OCR.
"""
from __future__ import annotations

import json
import os
import shutil
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

import dna
import fontset
from apply_patch import load_variant
from common import DnaError, deep, import_asset, read_json, sha256_file, template_dir, write_json
from compare_render import compare, outside_influence
from inspect_source import create_template
from render_static import check_svg, compile_svg, render
from validate_model import check_scene, editability_report
from verify_change import render_cached

T = "Editorial Product Spotlight"
TID = "editorial-product-spotlight"


def folder(root, n, name):
    p = Path(root) / f"t{n:02d}-{name}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def r24(root, fx, record, expect_error):
    o = folder(root, 24, "empty-scan-never-passes")
    tid = create_template(fx / "grid_flattened.jpg", "Empty Scan Probe", "suggested", tid="empty-scan-probe")["template_id"]
    tdir = template_dir(tid)
    scene = read_json(tdir / "scene.json")
    ed = editability_report(scene)
    rep = compare(tdir / "source/canonical.png", tdir / "source/canonical.png", o / "self-compare", scene, None, "editable_close",
                  "copying", ed)
    rec = dna.reconstruct(tid, "editable")
    write_json(o / "results.json", {"editability": ed, "self_compare": rep["overall"], "reconstruct": rec})
    record(24, "Audit F1: an empty scan with missing evidence never passes", {
        "editability of an empty inventory = incomplete (not pass)": ed["overall"] == "incomplete",
        "identical pixels + empty scene: verdict incomplete, not editable_close pass": rep["overall"]["status"] == "incomplete"
        and rep["checks"]["exact_pixels"]["status"] == "pass",
        "missing colour samples listed as blocking": any(u.startswith("color") for u in rep["overall"]["blocking_unknowns"]),
        "reconstruct does not promote readiness": rec["readiness"] == "partial_baseline",
    }, [o / "results.json"])


def r25(root, fx, record, expect_error):
    o = folder(root, 25, "fragment-assembly")
    tid = create_template(fx / "grid_flattened.jpg", "Fragment Probe", "suggested", tid="fragment-probe")["template_id"]
    tdir = template_dir(tid)
    s = read_json(tdir / "scene.json")
    canon = Image.open(tdir / "source/canonical.png").convert("RGB")
    s["nodes"], s["assets"] = [{"id": "n-bg", "type": "background", "role": "background", "parent": None, "fill": "#FFFFFF",
                                "geometry": {"x": 0, "y": 0, "w": 1080, "h": 1080}}], {}
    for i, (x, y) in enumerate(((0, 0), (540, 0), (0, 540), (540, 540))):
        f = o / f"q{i}.png"
        canon.crop((x, y, x + 540, y + 540)).save(f)
        a = import_asset(tdir, f, "image", "reference_crop", derived_from={"sha256": s["source"]["sha256"], "box": [x, y, 540, 540]})
        s["assets"][a["id"]] = a
        s["nodes"].append({"id": f"n-q{i}", "type": "image", "role": "photo", "parent": None, "asset": a["id"], "placement": {"fit": "fill"},
                           "geometry": {"x": x, "y": y, "w": 540, "h": 540}})
    s["nodes"].append({"id": "n-cap", "type": "text", "role": "caption", "parent": None, "content": "ALBA", "font": {"family": "Arial", "size": 30},
                       "align": "center", "first_baseline": 485, "line_height": 36, "geometry": {"x": 40, "y": 455, "w": 318, "h": 36}})
    s["slots"] = [{"id": "slot-cap", "role": "caption", "node": "n-cap", "type": "text"}] + \
                 [{"id": f"slot-q{i}", "role": "photo", "node": f"n-q{i}", "type": "image"} for i in range(4)]
    ed = editability_report(s)
    one = deep(s)
    one["nodes"] = [n for n in one["nodes"] if n["id"] not in ("n-q1", "n-q2", "n-q3")]  # single crop over the caption only
    one["slots"] = [sl for sl in one["slots"] if sl["node"] in {n["id"] for n in one["nodes"]}]
    ed1 = editability_report(one)
    write_json(o / "results.json", {"quarters": ed, "one_crop_over_text": ed1})
    record(25, "Audit F1: a page assembled from reference crops, or a crop with text baked in, is not editable", {
        "four quarter-page crops (each < 50%) detected as an assembly": ed["overall"] == "fail"
        and any("assembled" in x["why"] for x in ed["reference_background_shortcut"]),
        "caption slot fails: its pixels are baked into a crop": ed["slots"]["slot-cap"].startswith("fail"),
        "a single crop containing the caption fails as baked content": ed1["overall"] == "fail" and ed1["baked_content"][0]["contains"] == "n-cap",
    }, [o / "results.json"])


def r26(root, fx, record, expect_error):
    o = folder(root, 26, "lock-ancestors-removal")
    dna.run(f'use "{TID}" for task "Lock bypass probe"')
    tid, vid = dna.current()
    dna.run("lock headline.geometry.x")
    _, _, h = load_variant(tid, vid)
    g = dict(next(n for n in h["nodes"] if n["id"] == "n-headline")["geometry"], x=83)
    ok1, e1 = expect_error(lambda: dna.run(f"set headline.geometry = {json.dumps(g)}"), "lock-1-headline-geometry-x")
    dna.run("lock typography")
    ok2, e2 = expect_error(lambda: dna.run("remove label force"), "lock-2-typography")
    _, _, h2 = load_variant(tid, vid)
    write_json(o / "results.json", {"ancestor_replacement": e1.as_dict() if e1 else None, "removal": e2.as_dict() if e2 else None})
    record(26, "Audit F2: replacing a parent object or removing a node cannot bypass a lock", {
        "replacing headline.geometry under a lock on headline.geometry.x -> conflict": ok1,
        "removing a text node under a hard typography lock -> conflict": ok2,
        "neither change was committed": any(n["id"] == "n-label" for n in h2["nodes"])
        and next(n for n in h2["nodes"] if n["id"] == "n-headline")["geometry"]["x"] == 80,
    }, [o / "results.json"])


def r27(root, fx, record, expect_error):
    o = folder(root, 27, "hostile-model-opentype")
    tdir = template_dir(TID)
    base = read_json(tdir / "scene.json")
    bad = deep(base)
    aid = next(a for a, r in bad["assets"].items() if r["kind"] == "font")
    evil = 'x</style><script>globalThis.__dna=1</script><style>'
    bad["assets"][evil] = dict(bad["assets"].pop(aid), id=evil)
    for n in bad["nodes"]:
        if n["type"] == "text" and n["font"].get("asset") == aid:
            n["font"]["asset"] = evil
    v = check_scene(bad, tdir)
    named = deep(base)
    fa = next(a for a, r in named["assets"].items() if r["kind"] == "font")
    named["assets"][fa]["font_names"] = {"full": '</style><script>globalThis.__dna=2</script>', "postscript": 'a"b'}
    svg, _ = compile_svg(named, tdir, href_mode="data-nofonts")
    tree = ET.fromstring(svg)
    scripts = [e for e in tree.iter() if e.tag.split("}")[-1] == "script"]
    blocked, _ = expect_error(lambda: check_svg('<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'), "unsafe_or_invalid_svg")
    ext, _ = expect_error(lambda: check_svg('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x.png"/></svg>'),
                          "unsafe_or_invalid_svg")
    ot = deep(base)
    var = import_asset(tdir, fontset.path("variable"), "font", fontset.source())
    ot["assets"][var["id"]] = var
    h = next(n for n in ot["nodes"] if n["id"] == "n-headline")
    h["font"] = dict(h["font"], asset=var["id"], features={"kern": 0}, variation={"wdth": 90}, identity={"status": "unknown"})
    plain = deep(ot)
    next(n for n in plain["nodes"] if n["id"] == "n-headline")["font"].pop("variation")
    r1 = render(ot, tdir, o / "opentype", name="with-settings", formats=("png", "svg"))
    r0 = render(plain, tdir, o / "opentype-plain", name="without-wdth")
    differs = (np.asarray(Image.open(r1["png"])) != np.asarray(Image.open(r0["png"]))).any()
    write_json(o / "results.json", {"hostile_id_validation": v["errors"][:5], "scripts_in_svg": len(scripts)})
    record(27, "Audit F3: hostile model data stays data; normal OpenType settings produce valid SVG", {
        "asset id that would close <style> is rejected by validation": not v["valid"] and any("assetid" in e or "does not match" in e for e in v["errors"]),
        "hostile font names are escaped: compiled SVG has no <script>": not scripts,
        "sanitizer rejects <script> and external resources": blocked and ext,
        "features {kern:0} + variation {wdth:90}: valid XML, rendered, SVG round-trips": r1["svg_verification"]["roundtrip_status"] == "pass",
        "the wdth axis is actually applied (pixels differ without it)": bool(differs),
    }, [o / "results.json", o / "opentype" / "with-settings.png"])


def r28(root, fx, record, expect_error):
    o = folder(root, 28, "alpha-identity")
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(o / "white.png")
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(o / "clear.png")
    rep = compare(o / "white.png", o / "clear.png", o / "cmp", None, None, "exact_pixels", "editable_rendering")
    pres = outside_influence(o / "white.png", o / "clear.png", [], 16, 16)
    write_json(o / "results.json", {"exact": rep["checks"]["exact_pixels"], "appearance": rep["checks"]["appearance"], "preservation": pres})
    record(28, "Audit F4: transparent black is not identical to opaque white", {
        "decoded RGBA identity fails (256 px differ)": rep["checks"]["exact_pixels"]["unequal_pixels"] == 256 and rep["overall"]["status"] == "fail",
        "appearance over white is reported separately (identical there)": rep["checks"]["appearance"]["unequal_pixels"] == 0,
        "preservation with an empty influence fails on alpha": pres["status"] == "fail" and pres["changed_outside_influence"] == 256,
    }, [o / "results.json"])


def r29(root, fx, record, expect_error):
    o = folder(root, 29, "cache-relocation-integrity")
    tdir = template_dir(TID)
    vid = next(p.name for p in sorted((tdir / "variants").iterdir()))
    vd = tdir / "variants" / vid
    _, meta, scene = load_variant(TID, vid)
    first = render_cached(tdir, vd, scene)
    store = Path(os.environ["DESIGN_DNA_HOME"])
    moved_root = Path(root) / "relocated-store"
    shutil.copytree(store, moved_root)
    os.replace(store, store.with_name(store.name + "-parked"))  # original location unreachable (moved, not deleted)
    os.environ["DESIGN_DNA_HOME"] = str(moved_root)
    try:
        t2 = template_dir(TID)
        hit = render_cached(t2, t2 / "variants" / vid, scene)
        relocated = Path(hit["png"]).is_relative_to(moved_root) and Path(hit["png"]).exists()
        with open(hit["png"], "ab") as f:
            f.write(b"\0")  # corrupt the relocated copy's cached image
        again = render_cached(t2, t2 / "variants" / vid, scene)
        fresh_dir = Path(again["png"]).parent != Path(hit["png"]).parent
    finally:
        os.environ["DESIGN_DNA_HOME"] = str(store)
        os.replace(store.with_name(store.name + "-parked"), store)
    write_json(o / "results.json", {"first": first["png"], "relocated_hit": hit["png"], "after_corruption": again["png"]})
    record(29, "Audit F5/F7: caches survive relocation and are never trusted blindly", {
        "relocated template: cache hit resolves inside the new location": relocated,
        "corrupted cached image is not trusted; a fresh render goes to a new folder": fresh_dir,
        "cached entry records the renderer that produced it (part of the cache key)": bool(first["render_profile"].get("browser_version")),
    }, [o / "results.json"])


def r30(root, fx, record, expect_error):
    o = folder(root, 30, "exif-orientation")
    res = {}
    for ori in (5, 6, 7, 8):
        im = Image.new("RGB", (80, 48), (200, 30, 30))
        exif = im.getexif()
        exif[0x0112] = ori
        f = o / f"ori{ori}.jpg"
        im.save(f, exif=exif.tobytes())
        t = create_template(f, f"Orientation {ori}", "suggested", tid=f"orientation-{ori}")
        s = read_json(template_dir(t["template_id"]) / "scene.json")
        canon = Image.open(template_dir(t["template_id"]) / "source/canonical.png").size
        res[ori] = {"canvas": [s["canvas"]["width"], s["canvas"]["height"]], "canonical": list(canon),
                    "aspect": read_json(template_dir(t["template_id"]) / "passport.json")["aspect_ratio"]}
    write_json(o / "results.json", res)
    record(30, "Audit F6: EXIF orientations 5-8 give one consistent canvas", {
        f"orientation {k}: canvas = canonical = 48x80, aspect 3:5": v["canvas"] == v["canonical"] == [48, 80] and v["aspect"] == "3:5" or v
        for k, v in res.items()}, [o / "results.json"])


def r31(root, fx, record, expect_error):
    o = folder(root, 31, "text-stroke")
    tdir = template_dir(TID)
    base = read_json(tdir / "scene.json")
    s = deep(base)
    next(n for n in s["nodes"] if n["id"] == "n-headline")["stroke"] = {"color": "#FF0000", "width": 3, "align": "center"}
    svg, _ = compile_svg(s, tdir)
    r = render(s, tdir, o / "stroked", name="stroked")
    plain = render(base, tdir, o / "plain", name="plain")
    differs = (np.asarray(Image.open(r["png"])) != np.asarray(Image.open(plain["png"]))).any()
    bad = deep(base)
    next(n for n in bad["nodes"] if n["id"] == "n-hero")["stroke"] = {"color": "#FF0000", "width": 3}
    v = check_scene(bad, tdir)
    record(31, "Audit: text stroke is rendered; strokes the renderer cannot draw are rejected", {
        "stroke attributes present on the <text>": 'stroke="#ff0000"' in svg and 'stroke-width="3"' in svg,
        "stroke visibly changes the render": bool(differs),
        "stroke on an image node -> explicit unsupported error": not v["valid"] and any("stroke_on_image" in e for e in v["errors"]),
    }, [o / "stroked" / "stroked.png"])


def r32(root, fx, record, expect_error):
    o = folder(root, 32, "immutable-evidence")
    tdir = template_dir(TID)
    before = read_json(tdir / "passport.json")["baseline_render"]
    sha_before = sha256_file(tdir / before["path"])
    rec = dna.reconstruct(TID, "exact")
    after = read_json(tdir / "passport.json")["baseline_render"]
    clash, _ = expect_error(lambda: render(read_json(tdir / "scene.json"), tdir, Path(rec["render"]).parent, name="baseline"), "immutable_conflict")
    dna.run(f'use "{TID}" for task "Export twice"')
    e1, e2 = dna.run("export formats=png"), dna.run("export formats=png")
    write_json(o / "results.json", {"approved_before": before, "approved_after": after, "rerun": rec.get("reproduces_approved_baseline"),
                                    "exports": [e1["dir"], e2["dir"]]})
    record(32, "Audit: baselines and exports are immutable evidence", {
        "re-running reconstruct keeps the approved baseline (same file, same hash)": after == before
        and sha256_file(tdir / before["path"]) == sha_before,
        "the re-run lands in a new folder and proves reproducibility (0 px)": Path(rec["render"]).parent.name != Path(before["path"]).parent.name
        and rec["reproduces_approved_baseline"]["status"] == "pass",
        "rendering into an existing image path is refused": clash,
        "two exports of the same revision get two folders": e1["dir"] != e2["dir"],
    }, [o / "results.json"])


def r33(root, fx, record, expect_error):
    import subprocess
    import sys

    out = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "capabilities.py")],
                         capture_output=True, text=True, check=True).stdout
    caps = json.loads(out)["capabilities"]
    record(33, "Audit: the capability report does not claim OCR", {
        "OCR reported as unsupported (tooling presence is not an adapter)": caps["OCR"].startswith("unsupported"),
        "host storage integration reported as unverified": caps["host persistent storage adapter (e.g. ChatGPT Work)"].startswith("unverified"),
    })


def run(root, fx, record, want, expect_error):
    for n, fn in ((24, r24), (25, r25), (26, r26), (27, r27), (28, r28), (29, r29), (30, r30), (31, r31), (32, r32), (33, r33)):
        if not want(n):
            continue
        try:
            fn(root, fx, record, expect_error)
        except (Exception, DnaError) as e:
            record(n, f"crashed: T{n:02d}", {"ran without crashing": f"{e.__class__.__name__}: {e}"}, notes=traceback.format_exc()[-1500:])
