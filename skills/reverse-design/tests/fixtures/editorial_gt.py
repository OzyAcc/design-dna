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
from common import add_evidence, import_asset, read_json, template_dir, write_json  # noqa: E402
from inspect_source import create_template  # noqa: E402

import fontset  # noqa: E402


def claim(v, status="observed", conf="high"):
    return {"value": v, "status": status, "confidence": conf, "evidence_ids": [], "supplied_by_user": status == "observed"}


def gt_scene(scene, tdir, fx: Path) -> dict:
    bag = import_asset(tdir, fx / "bag.png", "image", "synthetic_fixture")
    serif = import_asset(tdir, fontset.path("serif"), "font", fontset.source())
    sans = import_asset(tdir, fontset.path("sans"), "font", fontset.source())
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
    scene["scan"] = {"state": "complete", "coverage": layered_coverage("ev-layered-source")}
    return scene


def layered_coverage(ev):
    """Complete 16-category coverage with facets for a source whose layers are known (construction manifest)."""
    o = lambda note: {"status": "observed", "note": note, "evidence_ids": [ev], "confidence": "high"}
    i = lambda note, conf="medium": {"status": "inferred", "note": note, "confidence": conf}
    f = lambda **kw: {k: (v if isinstance(v, dict) else o(v)) for k, v in kw.items()}
    return {
        "input_canvas": o("1080x1350 sRGB PNG rendered from the layered source"),
        "composition": dict(o("single column on paper, 80px side margin, centred hero"), facets=f(
            grid="single column", spacing="label->headline gap 42px; hero 18px below headline box", alignment="left edge x=80; hero centred",
            whitespace="generous paper margins top and bottom")),
        "element_inventory": o("background, accent bar, label, headline, hero image, CTA pill + text, translucent sheen, logo"),
        "geometry": dict(o("all node boxes known"), facets=f(position_size="every node", radii_strokes="hero radius 32, pill radius 48, no strokes",
                                                             transforms="none")),
        "color": dict(o("five role tokens"), facets=f(role_tokens="paper, accent, text primary/secondary, cta text",
                                                       gradients="only inside the photo asset", opacity_blending="sheen = white at 0.35")),
        "typography": dict(o("two pinned font files"), facets=f(
            text="3 live strings", font_candidates="the source names its files", font_identity="verified: source manifest names the file hashes",
            size_line_height="headline 84/96, label 28/34, CTA 34/44", tracking="label 4px, others 0", baselines_alignment="left; CTA centred",
            direction="ltr")),
        "image_treatment": dict(o("supplied product photo"), facets=f(images="bag.png (supplied original)", crop_intent="cover, focal 0.5/0.55",
                                                                       masks="rounded rect r=32", treatment="saturate 0.85 then contrast 1.08")),
        "depth_compositing": dict(o("8 layers in document order"), facets=f(layering="document order", shadows="hero cast shadow dy 18, blur 22, multiply",
                                                                            blend_modes="multiply shadow; normal elsewhere")),
        "surface_texture": dict(o("flat paper colour"), facets=f(textures="none in the layout; photo texture is inside the asset")),
        "lighting": i("single soft top light implied by the shadow offset"),
        "hierarchy_attention": i("headline -> hero -> CTA (hypothesis, not eye tracking)"),
        "message_mechanism": dict(o("brief supplied with the source: launch a premium everyday bag"),
                                  facets={"message_delivery": i("promise headline + product as evidence + red CTA")}),
        "character_theme": i("quiet editorial premium"),
        "usage_context": o("brief: social feed product launch, 4:5"),
        "responsive_system": {"status": "not_applicable", "note": "single static format by construction"},
        "output_requirements": o("1080x1350 PNG, sRGB"),
    }


def passport_fields():
    s = lambda v, st="suggested": {"value": v, "status": st}
    return dict(character=s("quiet editorial premium"), theme=s("everyday luxury accessories"), goal=s("launch a premium everyday handbag", "user_supplied"),
                literal_message=s("Carry the quiet confidence. Shop the edit.", "observed"),
                takeaway=s("premium without shouting", "inferred"),
                mechanism=s("large serif promise -> product shown as evidence -> single red call to action", "inferred"),
                channels=s(["instagram feed 4:5", "facebook feed"]), usage=s("single-product launches, seasonal edits"),
                unsuitable_for=s("multi-product range overviews, price-led promotions"), medium=s("social feed post", "user_supplied"),
                visual_signature=["paper ground", "serif two-line headline", "rounded photo with soft shadow", "red pill CTA"])


def build_gt(fx: Path) -> str:
    r = create_template(fx / "blank_1080x1350.png", "Synthetic Layered Source", "user_supplied", tid="fixture-layered-source")
    tid = r["template_id"]
    tdir = template_dir(tid)
    add_evidence(tdir, [{"evidence_id": "ev-layered-source", "source_sha256": read_json(tdir / "scene.json")["source"]["sha256"],
                         "region": None, "object": "all", "method": "source_extraction", "tool": "editorial_gt.py construction manifest",
                         "value": "every layer, font file, asset and parameter is defined by the fixture code", "status": "observed",
                         "confidence": "high", "justification": "layered source: values are known by construction, not measured"}])
    scene = gt_scene(read_json(tdir / "scene.json"), tdir, fx)
    write_json(tdir / "scene.json", scene)
    p = read_json(tdir / "passport.json")
    p.update(fixture=True, readiness="scanned", unresolved=[], **passport_fields())
    write_json(tdir / "passport.json", p)
    return tid
