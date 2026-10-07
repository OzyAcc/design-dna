"""Coverage (16 categories + required facets), communication claims and measured alignment relationships for a scan.

Statuses follow references/scan-contract.md: measured needs a measurement evidence id, observed a recorded observation
(user-confirmed inventory, transcription or brief), inferred carries a confidence, and anything not established is
unknown with what would resolve it. Communication categories are never measured.
"""
from __future__ import annotations


def _m(note, ids, conf="high"):
    return {"status": "measured", "note": note, "evidence_ids": sorted(set(ids)), "confidence": conf} if ids else \
        _u(note + " (no measurement recorded)", "re-run measurement for this category")


def _o(note, ids, conf="high"):
    return {"status": "observed", "note": note, "evidence_ids": sorted(set(ids)), "confidence": conf}


def _i(note, conf="low", ids=None, amb=None):
    d = {"status": "inferred", "note": note, "confidence": conf}
    if ids:
        d["evidence_ids"] = [i for i in ids if i]
    if amb:
        d["ambiguity"] = amb
    return d


def _u(note, probe):
    return {"status": "unknown", "note": note, "ambiguity": [probe]}


def _na(note):
    return {"status": "not_applicable", "note": note}


def _ai(b, key, default=""):
    v = (b.analysis or {}).get(key, default)
    return v if isinstance(v, str) else default


def coverage(b, nodes, failures, ai_ev, brief_ev) -> dict:
    texts = [n for n in nodes if n["type"] == "text"]
    images = [n for n in nodes if n["type"] == "image" or (n["type"] == "background" and n.get("asset"))]
    comp = (b.analysis or {}).get("composition") or {}
    unc = [u for u in (b.analysis or {}).get("uncertainties", []) if isinstance(u, str)][:8]
    failed = [f"{k}: {v[:120]}" for k, v in failures.items()]
    pf = b.pf
    supplied = lambda k: (pf.get(k) or {}).get("status") in ("user_supplied", "user_confirmed") and (pf.get(k) or {}).get("value")
    cov = {"input_canvas": b.scene["scan"]["coverage"].get("input_canvas") or _u("intake evidence missing", "re-run intake"),
           "responsive_system": {"status": "unknown", "note": "a single still shows one state; breakpoints and interactions are unknowable"}}
    geo_ids = b.ev["geometry"] + b.ev["fit"]
    align = [c for c in b.scene.get("constraints", [])]
    cov["composition"] = dict(_m(f"ink bands along both axes; {len(nodes)} elements placed", b.ev["composition"] + geo_ids), facets={
        "grid": _i(comp.get("grid") or "no grid declared; column structure inferred from element edges", "low", [ai_ev]),
        "spacing": _m("band gaps and margins from the composition profiles", b.ev["composition"]),
        "alignment": _m(f"{len(align)} shared edge relationship(s) measured", ["ev-app-alignment"]) if align else
        _i(comp.get("alignment") or "no shared edges within 1 px were found", "low", [ai_ev]),
        "whitespace": _m("leading/trailing margins from the composition profiles", b.ev["composition"])})
    cov["element_inventory"] = _o(f"{len(nodes)} elements reviewed: " + ", ".join(sorted({n['role'] for n in nodes}))[:300],
                                  ["ev-app-inventory"], "medium")
    if failed:
        cov["element_inventory"]["ambiguity"] = failed
    cov["geometry"] = dict(_m("text by render fit, shapes by ink bounds, images by the reviewed boxes", geo_ids, "medium"), facets={
        "position_size": _m("every measured node", geo_ids + ["ev-app-inventory"], "medium"),
        "radii_strokes": _m("corner radii by circle fit", b.ev["radius"], "medium") if b.ev["radius"] else
        _i("square corners and no strokes assumed where no radius was measured", "low"),
        "transforms": _i("no rotation or skew recorded", "medium")})
    cov["color"] = dict(_m(f"{len(b.tokens)} role token(s) from clean patches and ink cores", b.ev["color"]), facets={
        "role_tokens": _m(", ".join(sorted(b.tokens))[:300] or "none", b.ev["color"]),
        "gradients": _u("gradients were not sampled", "sample_colors --gradient along the gradient axis"),
        "opacity_blending": _u("underlying colour and opacity of blended areas are not recoverable from one image",
                               "a layered source or a second background")})
    if texts:
        cov["typography"] = dict(_m(f"{len(texts)} text block(s) render-fitted with the best supplied candidates", b.ev["fit"], "medium"), facets={
            "text": _o("transcriptions confirmed in review (no OCR)", ["ev-app-transcription"]),
            "font_candidates": _m("ranked by ink-mask IoU against the font library", b.ev["font"], "medium"),
            "font_identity": _u("a matching candidate is not the font's identity", "the original font file or source document"),
            "size_line_height": _m("render fits; single-line line heights are not observable", b.ev["fit"], "medium"),
            "tracking": _i("tracking 0 assumed (not fitted)", "low"),
            "baselines_alignment": _m("fitted baselines and alignment anchors", b.ev["fit"], "medium"),
            "direction": _o("script direction from the transcribed characters", ["ev-app-transcription"])})
    else:
        cov["typography"] = _na("no text elements in the reviewed inventory")
    if images:
        cov["image_treatment"] = dict(_o(f"{len(images)} image region(s) kept as bounded reference crops", ["ev-app-inventory"], "medium"), facets={
            "images": _o("reference crops; the original photos are not available", ["ev-app-inventory"]),
            "crop_intent": _u("original framing and focal point are unknown", "the original photo"),
            "masks": _i("rectangular frames assumed", "low"),
            "treatment": _u(_ai(b, "image_treatment") or "grading cannot be separated from content in a crop", "the original photo")})
    else:
        cov["image_treatment"] = _na("no image regions in the reviewed inventory")
    cov["depth_compositing"] = dict(_i("paint order: background, images, shapes, logos, text", "medium", [ai_ev]), facets={
        "layering": _i("paint order follows element type; overlaps not measured", "medium"),
        "shadows": _u(_ai(b, "depth") or "no shadow probe was run", "measure.py shadow on a caster edge"),
        "blend_modes": _u("normal assumed; blend modes are not separable on a flat image", "a layered source")})
    surf = _ai(b, "surface")
    cov["surface_texture"] = dict(_i(surf, "low", [ai_ev]) if surf else _u("surface not assessed", "inspect enlarged crops"), facets={
        "textures": _i(surf, "low", [ai_ev]) if surf else _u("texture not assessed", "inspect enlarged crops")})
    light = _ai(b, "lighting")
    cov["lighting"] = _i(light, "low", [ai_ev]) if light else _u("lighting not assessed", "shadow offsets and highlights")
    hier = (b.analysis or {}).get("hierarchy") or []
    cov["hierarchy_attention"] = _i("likely reading order: " + " -> ".join(hier)[:300], "low", [ai_ev]) if hier else \
        _u("reading order not assessed", "interpretation pass or user brief")
    msg_user = supplied("literal_message") or supplied("goal")
    com = (b.analysis or {}).get("communication") or {}
    if msg_user:
        cov["message_mechanism"] = dict(_o("message and goal supplied by the user", [brief_ev]), facets={
            "message_delivery": _i(com.get("takeaway") or "delivery mechanism not interpreted", "low", [ai_ev]) if com else
            _u("how the design delivers the message was not interpreted", "interpretation pass")})
    elif com:
        cov["message_mechanism"] = dict(_i(com.get("literal_message") or "message interpreted from visible copy", "low", [ai_ev]), facets={
            "message_delivery": _i(com.get("takeaway") or "takeaway hypothesis", "low", [ai_ev])})
    else:
        cov["message_mechanism"] = dict(_u("message not interpreted", "user brief or interpretation pass"), facets={
            "message_delivery": _u("delivery mechanism not interpreted", "interpretation pass")})
    if supplied("character") or supplied("theme"):
        cov["character_theme"] = _o("character/theme supplied by the user", [brief_ev])
    elif _ai(b, "character_theme"):
        cov["character_theme"] = _i(_ai(b, "character_theme"), "low", [ai_ev])
    else:
        cov["character_theme"] = _u("character not assessed", "user brief or interpretation pass")
    if supplied("usage") or supplied("channels"):
        cov["usage_context"] = _o("usage supplied by the user", [brief_ev])
    elif _ai(b, "usage_context"):
        cov["usage_context"] = _i(_ai(b, "usage_context"), "low", [ai_ev])
    else:
        cov["usage_context"] = _u("usage not stated", "user brief")
    cov["output_requirements"] = _o("channel supplied by the user", [brief_ev]) if supplied("channels") else \
        _u("no output brief (size, colour policy, format)", "user brief")
    if unc:
        cov["element_inventory"].setdefault("ambiguity", []).extend(unc[:4])
    return cov


def _claim(user, ai, ai_ev, brief_ev, conf="low"):
    if user:
        return {"value": user, "status": "observed", "confidence": "high", "evidence_ids": [brief_ev] if brief_ev else [],
                "supplied_by_user": True}
    if ai:
        return {"value": ai, "status": "inferred", "confidence": conf, "evidence_ids": [ai_ev] if ai_ev else [], "supplied_by_user": False}
    return {"value": None, "status": "unknown", "confidence": "unassessed", "evidence_ids": [], "resolving_probe": "user brief"}


def communication(analysis, pf, ai_ev, brief_ev, key_to_node) -> dict:
    com = (analysis or {}).get("communication") or {}
    user = lambda k: (pf.get(k) or {}).get("value") if (pf.get(k) or {}).get("status") in ("user_supplied", "user_confirmed") else None
    out = {"goal": _claim(user("goal"), com.get("goal"), ai_ev, brief_ev),
           "literal_message": _claim(user("literal_message"), com.get("literal_message"), ai_ev, brief_ev),
           "takeaway": _claim(user("takeaway"), com.get("takeaway"), ai_ev, brief_ev),
           "mechanisms": []}
    if com.get("cta"):
        out["cta"] = _claim(None, com["cta"], ai_ev, brief_ev)
    if com.get("word_image_relationship") and com["word_image_relationship"] != "none":
        out["word_image_relationship"] = _claim(None, com["word_image_relationship"], ai_ev, brief_ev)
    for m in com.get("mechanisms") or []:
        chain = [c for c in (m.get("chain") or []) if isinstance(c, str)]
        if len(chain) == 4:
            out["mechanisms"].append({"chain": chain, "status": "inferred", "confidence": m.get("confidence", "low") if m.get("confidence") in
                                      ("high", "medium", "low") else "low", "evidence_ids": [ai_ev] if ai_ev else [],
                                      "competing": [c for c in m.get("competing", []) if isinstance(c, str)]})
    return out


def hierarchy(analysis, key_to_node, ai_ev) -> dict:
    order = [key_to_node[k] for k in (analysis or {}).get("hierarchy", []) if k in key_to_node]
    if not order:
        return {"order": [], "status": "unknown", "note": "reading order not interpreted"}
    return {"order": order, "status": "inferred", "note": "likely reading order (hypothesis, not eye-tracking)"}


def alignment_constraints(nodes) -> tuple[list, dict | None]:
    """Shared left edges (left-aligned text and shapes, within 1 px) and canvas-centred text, as relaxable constraints."""
    lefts = [n for n in nodes if (n["type"] == "text" and n.get("align") == "left") or n["type"] == "shape"]
    out, groups = [], []
    for n in sorted(lefts, key=lambda n: n["geometry"]["x"]):
        if groups and abs(groups[-1][0]["geometry"]["x"] - n["geometry"]["x"]) <= 1:
            groups[-1].append(n)
        else:
            groups.append([n])
    for g in groups:
        for a, b in zip(g, g[1:]):
            out.append({"id": f"c-left-{a['id'][2:]}-{b['id'][2:]}"[:60], "type": "equal", "a": f"{a['id']}.left", "b": f"{b['id']}.left",
                        "tolerance": 1, "priority": "strong", "modes": ["adapt"], "relaxable": True, "status": "measured",
                        "note": "shared left edge measured within 1 px"})
    if not out:
        return [], None
    return out, {"evidence_id": "ev-app-alignment", "region": None, "object": "composition", "method": "computed_measurement",
                 "tool": "design-dna dashboard (edges from measured node geometry)",
                 "value": [{"a": c["a"], "b": c["b"]} for c in out], "status": "measured", "confidence": "medium",
                 "justification": "left edges of measured nodes equal within 1 px"}
