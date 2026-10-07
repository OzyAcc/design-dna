"""Assisted scan: reviewed element proposals -> engine measurements -> scene nodes, tokens, slots, coverage, evidence.

Proposals (from the analysis adapter or drawn by the user) only say WHERE to look and WHAT an element is. Geometry,
colours, font candidates, sizes and baselines come from the engine's own tools (measure.py, sample_colors.py,
font_candidates.py, fit_text.py), each writing its evidence record. Transcriptions and the inventory are recorded as
user-confirmed manual observations (there is no OCR integration). Communication findings stay hypotheses. Anything the
tools could not establish is written as unknown with the reason; nothing is upgraded to a measurement.
"""
from __future__ import annotations

import re
import statistics
from pathlib import Path

from PIL import Image

from . import enginelib as el
from .engine import EngineCrash, EngineError, tool

ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
TYPES = ("text", "image", "shape", "logo", "background")
TEXT_SLOT_ROLES = {"headline", "subheadline", "body", "kicker", "label", "cta", "caption", "price", "tagline", "title"}


def slug(s: str, n=40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n] or "x"


def _clip(b, W, H):
    x, y, w, h = [float(v) for v in b]
    x0, y0 = max(0, int(round(x))), max(0, int(round(y)))
    x1, y1 = min(W, int(round(x + w))), min(H, int(round(y + h)))
    return [x0, y0, max(1, x1 - x0), max(1, y1 - y0)]


def _pad(b, p, W, H):
    return _clip([b[0] - p, b[1] - p, b[2] + 2 * p, b[3] + 2 * p], W, H)


def _box(b) -> str:
    return ",".join(str(int(round(v))) for v in b)


class Builder:
    def __init__(self, ctx, home: Path, engine_id: str, draft: dict, passport_fields: dict):
        self.ctx, self.home, self.eid = ctx, Path(home), engine_id
        self.tdir = self.home / "templates" / engine_id
        self.draft, self.pf = draft, passport_fields or {}
        self.scene = el.read_json(self.tdir / "scene.json")
        self.W, self.H = int(self.scene["canvas"]["width"]), int(self.scene["canvas"]["height"])
        self.src = self.scene["source"]["sha256"]
        self.canon = Image.open(self.tdir / "source" / "canonical.png").convert("RGB")
        self.records, self.nodes, self.tokens, self.slots, self.expected = [], [], {}, [], {}
        self.assets, self.warnings, self.report = {}, [], {}
        self.ev = {k: [] for k in ("geometry", "color", "typography", "fit", "font", "image", "radius", "composition")}
        self.ids, self.key_node, self.analysis = set(), {}, draft.get("analysis") or {}
        self.ameta = draft.get("analysis_meta") or {}

    # ------------------------------------------------------------------ helpers
    def tool(self, script, *args):
        return tool(script, [self.eid, *args], self.home, cancel=self.ctx.cancelled)

    def node_id(self, key):
        base = "n-" + slug(key, 50)
        nid, i = base, 2
        while nid in self.ids:
            nid, i = f"{base}-{i}", i + 1
        self.ids.add(nid)
        self.key_node[key] = nid
        return nid

    def token_key(self, prefix, role):
        k, i = f"{prefix}.{slug(role, 30)}", 2
        while k in self.tokens:
            k, i = f"{prefix}.{slug(role, 30)}-{i}", i + 1
        return k

    def sample(self, role, boxes, ink_core=False, inset=2):
        flag = "--ink-core" if ink_core else "--sample"
        args = ["--inset", str(inset)]
        for b in boxes:
            args += [flag, f"{role}={_box(b)}"]
        res = self.tool("sample_colors.py", *args)
        r = (res or {}).get(role)
        if r:
            self.ev["color"].append(f"ev-color-{slug(role, 80)}")
        return r

    def add_token(self, key, r, sample_boxes, method):
        self.tokens[key] = {"type": "color", "value": r["value"], "space": "srgb", "status": "measured" if r["solid"] else "inferred",
                            "confidence": r["confidence"], "evidence_ids": [f"ev-color-{slug(key, 80)}"], "samples": sample_boxes,
                            "sample_method": method}
        if not r["solid"]:
            self.tokens[key]["note"] = "non-uniform samples: stored as the median, not a confirmed solid colour"

    # ------------------------------------------------------------------ elements
    def background(self, e):
        boxes = [b for b in (p.get("sample_box") for p in self.analysis.get("palette", []) if str(p.get("role", "")).startswith("background")) if b]
        inset = 8
        corners = [[inset, inset, 24, 24], [self.W - inset - 24, inset, 24, 24], [inset, self.H - inset - 24, 24, 24],
                   [self.W - inset - 24, self.H - inset - 24, 24, 24]]
        boxes = [_clip(b, self.W, self.H) for b in boxes][:4] + corners
        r = self.sample("background.base", boxes)
        nid = self.node_id(e.get("key", "background"))
        if r and r["solid"]:
            self.add_token("background.base", r, boxes, "patch_median")
            node = {"id": nid, "alias": "background", "type": "background", "role": "background", "parent": None,
                    "fill": {"token": "background.base"}, "geometry": {"x": 0, "y": 0, "w": self.W, "h": self.H},
                    "provenance": {"fill": {"status": "measured", "confidence": r["confidence"], "evidence_ids": ["ev-color-background-base"]}}}
            self.report[e["key"]] = {"status": "measured", "detail": f"solid background {r['value']}"}
        else:
            rec = self.crop_asset(e["key"], [0, 0, self.W, self.H])
            node = {"id": nid, "alias": "background", "type": "background", "role": "background", "parent": None, "asset": rec["id"],
                    "placement": {"fit": "cover"}, "geometry": {"x": 0, "y": 0, "w": self.W, "h": self.H}, "editability": "raster",
                    "provenance": {"*": {"status": "observed", "confidence": "high", "evidence_ids": ["ev-app-inventory"],
                                         "note": "non-uniform background kept as a bounded reference crop; it is not an editable reconstruction"}}}
            self.warnings.append("the background is not a solid colour; it is kept as a reference crop, so editability cannot pass")
            self.report[e["key"]] = {"status": "raster", "detail": "non-uniform background kept as reference crop"}
        return node

    def crop_asset(self, key, box):
        crops = self.ctx.dir / "crops"
        crops.mkdir(parents=True, exist_ok=True)
        f = crops / f"{slug(key)}-{_box(box).replace(',', '-')}.png"
        x, y, w, h = box
        self.canon.crop((x, y, x + w, y + h)).save(f)
        rec = el.import_asset(self.tdir, f, "image", "reference_crop", derived_from={"sha256": self.src, "box": box},
                              note="bounded crop of the reference: the original photo/artwork is not available")
        self.assets[rec["id"]] = rec
        self.ev["image"].append("ev-app-inventory")
        return rec

    def image(self, e, kind):
        box = _clip(e["bbox"], self.W, self.H)
        rec = self.crop_asset(e["key"], box)
        nid = self.node_id(e["key"])
        node = {"id": nid, "alias": slug(e.get("role") or kind, 30), "type": "image", "role": e.get("role") or kind, "parent": None,
                "asset": rec["id"], "placement": {"fit": "cover", "focal": [0.5, 0.5]}, "mask": {"type": "rect", "radius": 0},
                "geometry": {"x": box[0], "y": box[1], "w": box[2], "h": box[3]}, "editability": "raster",
                "provenance": {"geometry": {"status": "observed", "confidence": "medium", "evidence_ids": ["ev-app-inventory"],
                                            "note": "region confirmed in review; crop bounds are the reviewed box"},
                               "asset": {"status": "observed", "confidence": "high", "evidence_ids": ["ev-app-inventory"],
                                         "note": "reference crop; hidden pixels behind other elements are unknown"},
                               "treatment": {"status": "unknown", "confidence": "unassessed", "resolving_probe": "the original photo"}}}
        if e.get("slot", True):
            self.slots.append({"id": f"slot-{slug(e.get('role') or kind, 30)}-{nid[2:]}"[:60], "role": e.get("role") or kind, "node": nid,
                               "type": "logo" if kind == "logo" else "image", "fit": "strict",
                               "treatments_allowed": ["grayscale", "saturate", "contrast", "brightness", "hue_rotate", "tint", "blur"]})
        self.report[e["key"]] = {"status": "observed", "detail": f"reference crop {box[2]}x{box[3]}"}
        return node

    def shape(self, e):
        box = _clip(e["bbox"], self.W, self.H)
        nid = self.node_id(e["key"])
        ink = self.tool("measure.py", "ink", "--region", _box(box), "--object", nid, "--id", f"ev-ink-{nid}")
        g, gstat = box, "observed"
        if ink.get("ink_box"):
            g, gstat = ink["ink_box"], "measured"
            self.ev["geometry"].append(f"ev-ink-{nid}")
        key = self.token_key("fill", e.get("role") or "shape")
        if min(g[2], g[3]) >= 16:  # interior patch, clear of antialiased edges and rounded corners
            inner = _clip([g[0] + g[2] * 0.25, g[1] + g[3] * 0.25, g[2] * 0.5, g[3] * 0.5], self.W, self.H)
            r = self.sample(key, [inner])
        else:  # thin bars and rules: the whole ink box with a 1 px inset
            inner = list(g)
            r = self.sample(key, [inner], inset=1)
        fill = "#000000"
        if r:
            self.add_token(key, r, [inner], "patch_median")
            fill = {"token": key}
        rad = self.tool("measure.py", "radius", "--region", _box(_pad(g, 2, self.W, self.H)), "--object", nid, "--id", f"ev-radius-{nid}")
        radius = rad.get("radius_estimate") if isinstance(rad, dict) else None
        node = {"id": nid, "alias": slug(e.get("role") or "shape", 30), "type": "shape", "shape": "rect", "role": e.get("role") or "shape",
                "parent": None, "fill": fill, "geometry": {"x": g[0], "y": g[1], "w": g[2], "h": g[3]},
                "provenance": {"geometry": {"status": gstat, "confidence": "high" if gstat == "measured" else "medium",
                                            "evidence_ids": [f"ev-ink-{nid}"] if gstat == "measured" else ["ev-app-inventory"]}}}
        if radius and 1.5 < radius < min(g[2], g[3]) / 2 + 1:
            node["radius"] = round(min(radius, min(g[2], g[3]) / 2), 2)
            node["provenance"]["radius"] = {"status": "measured", "confidence": "medium", "evidence_ids": [f"ev-radius-{nid}"]}
            self.ev["radius"].append(f"ev-radius-{nid}")
        self.report[e["key"]] = {"status": gstat, "detail": f"shape {g}, fill {r['value'] if r else 'unknown'}"}
        return node

    def text(self, e, fonts):
        text = (e.get("text") or "").replace("\r", "")
        if not text.strip():
            raise ValueError(f"text element {e['key']} has no transcription; type the exact visible text in the review step")
        lines = text.split("\n")
        box = _clip(e["bbox"], self.W, self.H)
        nid = self.node_id(e["key"])
        align = e.get("align") if e.get("align") in ("left", "center", "right") else "left"
        prof = self.tool("measure.py", "profile", "--region", _box(box), "--axis", "y", "--object", nid, "--id", f"ev-profile-{nid}")
        bands = prof.get("bands") or []
        line_boxes = []
        if len(bands) == len(lines):
            line_boxes = [[box[0], b0, box[2], b1 - b0] for b0, b1 in bands]
        else:
            self.warnings.append(f"{e['key']}: {len(lines)} transcribed line(s) but {len(bands)} ink band(s); line positions are estimated")
            hh = box[3] / len(lines)
            line_boxes = [[box[0], box[1] + i * hh, box[2], hh] for i in range(len(lines))]
        inks = []
        for i, lb in enumerate(line_boxes):
            r = self.tool("measure.py", "ink", "--region", _box(_pad(lb, 1, self.W, self.H)), "--object", nid, "--id", f"ev-ink-{nid}-l{i + 1}")
            inks.append(r)
            if r.get("ink_box"):
                self.ev["geometry"].append(f"ev-ink-{nid}-l{i + 1}")
        first = inks[0]
        if not first.get("ink_box"):
            raise ValueError(f"no ink found for text element {e['key']} inside its box")
        ib = first["ink_box"]
        role = e.get("role") or "text"
        tkey = self.token_key("text", role)
        colour = self.sample(tkey, [ib], ink_core=True)
        if colour:
            self.add_token(tkey, colour, [ib], "ink_core")
        usable = [f for f in fonts if el.covers(f["path"], text)][:12]
        if not usable:
            raise ValueError(f"no font in the library covers every character of {e['key']!r}; upload a font that does")
        args = ["--region", _box(_pad(ib, 3, self.W, self.H)), "--text", lines[0].strip() or lines[0], "--object", nid]
        for f in usable:
            args += ["--font", f["path"]]
        cand = self.tool("font_candidates.py", *args)
        self.ev["font"].append(cand["evidence_id"])
        best = cand["ranked"][0]
        best_lib = next(f for f in usable if Path(f["path"]).resolve() == Path(best["file"]).resolve())
        size = float(best["size_px_by_height"])
        anchor = {"left": ib[0], "center": ib[0] + ib[2] / 2, "right": ib[0] + ib[2]}[align]
        base0 = first["baseline_y"]
        fit_box = _clip([ib[0] - 12, ib[1] - size * 0.35, ib[2] + 24, ib[3] + size * 0.7], self.W, self.H)
        fit = self.tool("fit_text.py", "--region", _box(fit_box), "--text", lines[0], "--font", best["file"], "--size", f"{size:.2f}",
                        "--x", f"{anchor:.2f}", "--baseline", f"{base0:.2f}", "--fit", "size,x,baseline", "--align", align,
                        "--weight", str(best_lib["weight"]), "--object", nid)
        self.ev["fit"].append(fit["evidence_id"])
        p = fit["params"]
        size, x_anchor, baseline = float(p["size"]), float(p["x"]), float(p["baseline"])
        baselines = [baseline] + [r["baseline_y"] for r in inks[1:] if r.get("baseline_y")]
        lh_status = "measured"
        if len(lines) > 1 and len(baselines) == len(lines):
            line_height = round(statistics.median([b - a for a, b in zip(baselines, baselines[1:])]), 2)
        else:
            line_height, lh_status = round(size * 1.2, 2), ("inferred" if len(lines) == 1 else "unknown")
        widest = max((r["ink_box"][2] for r in inks if r.get("ink_box")), default=ib[2])
        w = max(box[2], widest * 1.04 + 6)
        x = {"left": x_anchor, "center": x_anchor - w / 2, "right": x_anchor - w}[align]
        y = min(ib[1], baseline - size * 0.8) - 2
        h = max(baseline - y + (len(lines) - 1) * line_height + size * 0.3, len(lines) * line_height + 1)
        font_rec = el.import_asset(self.tdir, Path(best["file"]), "font", "supplied")
        self.assets[font_rec["id"]] = font_rec
        rtl = bool(ARABIC.search(text))
        node = {"id": nid, "alias": slug(role, 30), "type": "text", "role": role, "parent": None, "content": text,
                "font": {"asset": font_rec["id"], "size": round(size, 3), "weight": best_lib["weight"],
                         "identity": {"status": "unknown", "candidates": [{"full": r["font"], "iou": r["iou"]} for r in cand["ranked"][:5]],
                                      "evidence_ids": [cand["evidence_id"]], "resolving_probe": "the original font file or source document"}},
                "align": align, "direction": "rtl" if rtl else "ltr", "first_baseline": round(baseline, 3), "line_height": line_height,
                "tracking": 0, "fill": {"token": tkey} if colour else "#000000",
                "fit": {"policy": "strict", "max_lines": len(lines)},
                "geometry": {"x": round(x, 2), "y": round(y, 2), "w": round(w, 2), "h": round(h, 2)}, "editability": "live",
                "provenance": {"content": {"status": "observed", "confidence": "high", "evidence_ids": ["ev-app-transcription"],
                                           "note": "transcription confirmed in review (no OCR)"},
                               "font.asset": {"status": "inferred", "confidence": "low" if len(cand.get("ties", [])) > 1 else "medium",
                                              "evidence_ids": [cand["evidence_id"]], "note": "best-ranked candidate; identity unknown"},
                               "font.size": {"status": "measured", "confidence": "medium", "evidence_ids": [fit["evidence_id"]],
                                             "note": "render fit, conditional on the candidate font"},
                               "first_baseline": {"status": "measured", "confidence": "medium", "evidence_ids": [fit["evidence_id"]]},
                               "line_height": {"status": lh_status, "confidence": "medium" if lh_status == "measured" else "low",
                                               "evidence_ids": [f"ev-ink-{nid}-l{i + 1}" for i in range(len(inks)) if inks[i].get("ink_box")]
                                               if lh_status == "measured" else [],
                                               "note": "" if lh_status == "measured" else "single line: line height not observable"}}}
        if rtl:
            node["lang"] = "ar"
        self.expected[nid] = text
        if e.get("slot", True):
            self.slots.append({"id": f"slot-{slug(role, 30)}-{nid[2:]}"[:60], "role": role, "node": nid, "type": "text", "fit": "strict",
                               "limits": {"max_lines": len(lines)}})
        self.report[e["key"]] = {"status": "measured", "detail": f"{best['font']} {size:.1f}px, baseline {baseline:.1f}",
                                 "font": best["font"], "ties": cand.get("ties", []), "mae": [fit.get("mae_start"), fit.get("mae_end")]}
        return node

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        els = [e for e in self.draft.get("elements", []) if e.get("status") != "rejected"]
        bad = [e.get("key") for e in els if e.get("type") not in TYPES or not isinstance(e.get("bbox"), list) or len(e["bbox"]) != 4]
        if bad:
            raise ValueError(f"elements without a valid type and box: {bad}")
        if not els:
            raise ValueError("no accepted elements to measure: accept proposals or draw elements first")
        self.ctx.stage("evidence", "recording the reviewed inventory and transcriptions")
        src = self.ameta.get("provider")
        by = f"{src} {self.ameta.get('model', '')} request {self.ameta.get('request_id', '')}".strip() if src else "the user"
        self.records += [
            {"evidence_id": "ev-app-inventory", "source_sha256": self.src, "region": None, "object": "element_inventory",
             "method": "manual_observation", "tool": f"design-dna dashboard review (proposed by {by})",
             "value": [{k: e.get(k) for k in ("key", "type", "role", "bbox", "source")} for e in els], "status": "observed",
             "confidence": "medium", "justification": "elements proposed and then confirmed or corrected by the user in the review step"},
            {"evidence_id": "ev-app-transcription", "source_sha256": self.src, "region": None, "object": "typography",
             "method": "manual_observation", "tool": f"design-dna dashboard review (proposed by {by})",
             "value": {e["key"]: e.get("text") for e in els if e["type"] == "text"}, "status": "observed", "confidence": "high",
             "justification": "transcription confirmed by the user; no OCR integration exists"}]
        el.add_evidence(self.tdir, self.records)
        fonts = el.font_library()
        bg_el = next((e for e in els if e["type"] == "background"), {"key": "background", "type": "background", "bbox": [0, 0, self.W, self.H]})
        self.ctx.stage("background", "sampling the background")
        ordered = [self.background(bg_el)]
        groups = {"image": [], "shape": [], "logo": [], "text": []}
        for e in els:
            if e is not bg_el and e["type"] != "background":
                groups[e["type"]].append(e)
        failures = {}
        for kind in ("image", "shape", "logo", "text"):
            for e in groups[kind]:
                self.ctx.stage(f"measure:{e['key']}", f"measuring {kind} {e.get('role') or e['key']}")
                try:
                    if kind == "text":
                        ordered.append(self.text(e, fonts))
                    elif kind == "shape":
                        ordered.append(self.shape(e))
                    else:
                        ordered.append(self.image(e, kind))
                except (ValueError, EngineError, EngineCrash) as x:
                    msg = getattr(x, "message", None) or str(x)
                    failures[e["key"]] = msg
                    self.report[e["key"]] = {"status": "unknown", "detail": msg}
                    self.warnings.append(f"{e['key']}: not measured ({msg[:200]})")
        self.ctx.stage("composition", "measuring composition bands")
        for axis in ("y", "x"):
            self.tool("measure.py", "profile", "--region", f"0,0,{self.W},{self.H}", "--axis", axis, "--object", "composition",
                      "--id", f"ev-composition-{axis}")
            self.ev["composition"].append(f"ev-composition-{axis}")
        return self.finish(ordered, els, failures)

    def finish(self, nodes, els, failures) -> dict:
        from .scan_coverage import alignment_constraints, communication, coverage, hierarchy

        s = self.scene
        s["nodes"], s["tokens"], s["slots"] = nodes, self.tokens, self.slots
        s["assets"] = {k: v for k, v in self.assets.items()}
        s["constraints"], align_ev = alignment_constraints(nodes)
        if align_ev:
            el.add_evidence(self.tdir, [dict(align_ev, source_sha256=self.src)])
        s["verification"]["expected_text"] = self.expected
        built = {n["id"] for n in nodes}
        key_to_node = {k: v for k, v in self.key_node.items() if v in built}
        ai_ev = None
        if self.analysis:
            ai_ev = "ev-app-analysis"
            el.add_evidence(self.tdir, [{"evidence_id": ai_ev, "source_sha256": self.src, "region": None, "object": "communication",
                                         "method": "inference", "tool": f"{self.ameta.get('provider')} {self.ameta.get('model')} "
                                                                        f"(request {self.ameta.get('request_id')})",
                                         "value": {k: self.analysis.get(k) for k in ("communication", "character_theme", "usage_context",
                                                                                     "composition", "image_treatment", "depth", "surface",
                                                                                     "lighting", "hierarchy", "uncertainties")},
                                         "status": "inferred", "confidence": "low",
                                         "justification": "vision-model interpretation of visible choices; a hypothesis, not a measurement",
                                         "limitations": ["no eye-tracking, audience data or designer intent"]}])
        brief_ev = None
        if any((self.pf.get(k) or {}).get("value") for k in ("goal", "literal_message", "usage", "channels", "character", "theme")):
            brief_ev = "ev-app-brief"
            el.add_evidence(self.tdir, [{"evidence_id": brief_ev, "source_sha256": self.src, "region": None, "object": "usage_context",
                                         "method": "manual_observation", "tool": "design-dna dashboard (user brief)",
                                         "value": {k: v for k, v in self.pf.items() if isinstance(v, dict) and v.get("status") == "user_supplied"},
                                         "status": "observed", "confidence": "high", "justification": "supplied by the user in the purpose step"}])
        s["communication"] = communication(self.analysis, self.pf, ai_ev, brief_ev, key_to_node)
        s["communication"]["hierarchy"] = hierarchy(self.analysis, key_to_node, ai_ev)
        complete = bool(self.draft.get("review_confirmed")) and not failures
        s["scan"] = {"state": "complete" if complete else "partial",
                     "coverage": coverage(self, nodes, failures, ai_ev, brief_ev)}
        el.write_json(self.tdir / "scene.json", s)
        return {"nodes": len(nodes), "tokens": sorted(self.tokens), "slots": [sl["id"] for sl in self.slots], "elements": self.report,
                "failures": failures, "warnings": self.warnings, "scan_state": s["scan"]["state"]}
