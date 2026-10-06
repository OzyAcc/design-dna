"""Ground-truth layered scene for the acceptance suite ("known synthetic layered reference").

build_gt(fixtures_dir) creates template `fixture-layered-source` with known geometry, live text, a masked hero
with treatment + editable shadow, token-bound accent uses and a translucent sheen, then renders reference.png.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from common import import_asset, read_json, template_dir, write_json  # noqa: E402
from inspect_source import create_template  # noqa: E402

FONTS = Path("C:/Windows/Fonts")


def claim(v, status="observed", conf="high"):
    return {"value": v, "status": status, "confidence": conf, "evidence_ids": [], "supplied_by_user": status == "observed"}


def gt_scene(scene, tdir, fx: Path) -> dict:
    bag = import_asset(tdir, fx / "bag.png", "image", "synthetic_fixture")
    serif = import_asset(tdir, FONTS / "georgiab.ttf", "font", "system_font")
    sans = import_asset(tdir, FONTS / "arialbd.ttf", "font", "system_font")
    logo = json.loads((fx / "logo.json").read_text())
    known = {"*": {"status": "observed", "confidence": "high", "note": "known by construction (layered fixture)"}}
    ident = lambda a: {"status": "verified", "candidates": [a["font_names"]["full"]], "evidence_ids": []}
    T = lambda nid, alias, content, font, size, x, y, w, h, base, lh, fill, align="left", tracking=0: {
        "id": nid, "alias": alias, "type": "text", "role": alias, "parent": None, "content": content,
        "font": {"asset": font["id"], "weight": 700, "size": size, "identity": ident(font)}, "align": align,
        "direction": "ltr", "lang": "en", "first_baseline": base, "line_height": lh, "tracking": tracking,
        "fill": {"token": fill}, "fit": {"policy": "strict", "max_lines": content.count("\n") + 1},
        "geometry": {"x": x, "y": y, "w": w, "h": h, "space": "canvas", "bounds": "layout"},
        "editability": "live", "provenance": known}
    scene["assets"] = {a["id"]: a for a in (bag, serif, sans)}
    scene["tokens"] = {k: {"type": "color", "value": v, "space": "srgb", "status": "observed", "confidence": "high"}
                       for k, v in {"background.paper": "#F4EFE6", "accent.primary": "#C8102E", "text.primary": "#1F1A17",
                                    "text.secondary": "#6B5E55", "cta.text": "#FFFFFF"}.items()}
    scene["nodes"] = [
        {"id": "n-bg", "alias": "background", "type": "background", "role": "background", "parent": None,
         "fill": {"token": "background.paper"}, "geometry": {"x": 0, "y": 0, "w": 1080, "h": 1350}, "provenance": known},
        {"id": "n-accent-bar", "alias": "accent-bar", "type": "shape", "shape": "rect", "role": "accent", "parent": None,
         "fill": {"token": "accent.primary"}, "geometry": {"x": 80, "y": 100, "w": 120, "h": 12}, "provenance": known},
        T("n-label", "label", "NEW SEASON", sans, 28, 80, 144, 600, 34, 172, 34, "text.secondary", tracking=4),
        T("n-headline", "headline", "Carry the\nquiet confidence.", serif, 84, 80, 220, 920, 192, 292, 96, "text.primary"),
        {"id": "n-hero", "alias": "hero", "type": "image", "role": "hero", "parent": None, "asset": bag["id"],
         "placement": {"fit": "cover", "focal": [0.5, 0.55], "scale": 1},
         "mask": {"type": "rect", "radius": 32},
         "treatment": [{"op": "saturate", "amount": 0.85}, {"op": "contrast", "amount": 1.08}],
         "effects": [{"id": "cast_shadow", "type": "drop_shadow", "kind": "cast", "enabled": True, "dx": 0, "dy": 18,
                      "blur": 22, "spread": 0, "color": "#2B1D12", "opacity": 0.22, "blend": "multiply", "receiver": "n-bg"}],
         "geometry": {"x": 140, "y": 430, "w": 800, "h": 620}, "editability": "raster", "provenance": known},
        {"id": "n-cta-pill", "alias": "cta-pill", "type": "shape", "shape": "rect", "role": "cta", "parent": None, "radius": 48,
         "fill": {"token": "accent.primary"}, "geometry": {"x": 80, "y": 1150, "w": 360, "h": 96}, "provenance": known},
        T("n-cta-text", "cta", "Shop the edit", sans, 34, 80, 1178, 360, 44, 1210, 44, "cta.text", align="center"),
        {"id": "n-sheen", "alias": "sheen", "type": "shape", "shape": "ellipse", "role": "decoration", "parent": None,
         "fill": "#FFFFFF", "opacity": 0.35, "geometry": {"x": 380, "y": 1112, "w": 150, "h": 150}, "provenance": known},
        {"id": "n-logo", "alias": "logo", "type": "path", "role": "logo", "parent": None, "path": logo["d"], "path_box": logo["box"],
         "fill": {"token": "text.primary"}, "geometry": {"x": 880, "y": 1166, "w": 120, "h": 84}, "provenance": known},
    ]
    scene["slots"] = [
        {"id": "slot-headline", "role": "headline", "node": "n-headline", "type": "text", "fit": "strict", "limits": {"max_lines": 2}},
        {"id": "slot-label", "role": "label", "node": "n-label", "type": "text", "fit": "strict"},
        {"id": "slot-hero", "role": "hero", "node": "n-hero", "type": "image", "treatments_allowed": ["saturate", "contrast"]},
        {"id": "slot-cta", "role": "cta", "node": "n-cta-text", "type": "text", "fit": "strict"},
        {"id": "slot-accent", "role": "accent", "node": "n-accent-bar", "type": "color"},
        {"id": "slot-logo", "role": "logo", "node": "n-logo", "type": "logo"}]
    scene["constraints"] = [
        {"id": "c-margin-left", "type": "anchor", "a": "n-headline.left", "b": "canvas.left", "value": 80, "tolerance": 0.5, "priority": "required"},
        {"id": "c-label-gap", "type": "gap", "a": "n-headline.top", "b": "n-label.bottom", "value": 42, "tolerance": 0.5, "relaxable": True},
        {"id": "c-cta-align", "type": "equal", "a": "n-cta-pill.left", "b": "n-headline.left", "tolerance": 0.5, "modes": ["adapt"]},
        {"id": "c-hero-center", "type": "equal", "a": "n-hero.center_x", "b": "canvas.center_x", "tolerance": 0.5}]
    scene["communication"] = {
        "goal": claim("launch a premium everyday handbag"), "literal_message": claim("Carry the quiet confidence."),
        "takeaway": claim("premium without shouting", "inferred", "medium"), "cta": claim("Shop the edit"),
        "word_image_relationship": claim("demonstration: the product is the evidence for the promise", "inferred", "medium"),
        "mechanisms": [{"chain": ["large two-line serif headline, top-left, generous paper margin", "likely first fixation",
                                  "quiet confidence = premium", "inspect the bag, then the red CTA"],
                        "status": "inferred", "confidence": "medium", "evidence_ids": [],
                        "competing": ["the red CTA could pull first attention on a small phone screen"]}],
        "hierarchy": {"order": ["n-headline", "n-hero", "n-cta-pill", "n-label", "n-logo"], "status": "inferred"}}
    scene["verification"]["expected_text"] = {n["id"]: n["content"] for n in scene["nodes"] if n["type"] == "text"}
    scene["scan"] = {"state": "complete", "coverage": {c: {"status": "observed", "note": "known by construction"} for c in (
        "input_canvas", "composition", "element_inventory", "geometry", "color", "typography", "image_treatment",
        "depth_compositing", "hierarchy_attention", "message_mechanism", "character_theme", "usage_context", "output_requirements")}}
    scene["scan"]["coverage"].update({"surface_texture": {"status": "not_applicable", "note": "flat paper, no texture"},
                                      "lighting": {"status": "observed", "note": "single top light implied by shadow dy=18"},
                                      "responsive_system": {"status": "not_applicable", "note": "single static format"}})
    return scene


def build_gt(fx: Path) -> str:
    r = create_template(fx / "blank_1080x1350.png", "Synthetic Layered Source", "user_supplied", tid="fixture-layered-source")
    tid = r["template_id"]
    tdir = template_dir(tid)
    scene = gt_scene(read_json(tdir / "scene.json"), tdir, fx)
    write_json(tdir / "scene.json", scene)
    p = read_json(tdir / "passport.json")
    p.update(fixture=True, readiness="scanned", unresolved=[])
    write_json(tdir / "passport.json", p)
    return tid
