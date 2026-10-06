"""Verification of a transaction: model changes and visual changes, reported separately.

Model: every leaf path that differs between base and candidate must be a requested change or a declared dependency
(`keep everything else` freezes every other path). Visual: the candidate render is compared with the APPROVED
template baseline when the base is the baseline revision (and the pinned re-render of that baseline must still
reproduce it), otherwise with the previous revision's render. The expected influence is the union of the edited
nodes' own alpha masks (before + after, incl. shadows), dilated 2 px, declared before any pixel is compared — not a
bounding box and never an ignore mask chosen afterwards. Changed pixels are attributed per node.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from common import diff_paths, model_hash, read_json
from compare_render import decode_rgba, delta_e, pixel_metrics
from ops import reading_order
from render_static import render

IGNORED = ("revision", "base_revision", "variant", "render_profile")
MODEL_ONLY = {"alias", "role", "provenance", "editability", "reflow", "fit", "lang"}
DILATE_PX = 2


def _scene_key(scene) -> str:
    return hashlib.sha256(json.dumps(scene, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


_FINGERPRINTS = {}


def runtime_fingerprint(channel=None) -> str:
    """'<channel> <version>' of the browser that WOULD render now (launched once per process and channel)."""
    if channel not in _FINGERPRINTS:
        from renderer_env import browser

        with browser(channel) as (b, ch):
            _FINGERPRINTS[channel] = f"{ch} {b.version}"
    return _FINGERPRINTS[channel]


def _rebase(rep, out):
    """Reports store absolute paths; a relocated template keeps working by resolving them inside its own cache dir."""
    out = Path(out)
    rep["png"] = str(out / Path(rep["png"]).name)
    for b in rep.get("bounds", {}).values():
        if b.get("mask"):
            b["mask"] = str(out / "masks" / Path(b["mask"]).name)
    for k in ("svg",):
        if rep.get(k):
            rep[k] = str(out / Path(rep[k]).name)
    return rep


def render_cached(tdir, vd, scene, formats=("png",)) -> dict:
    """Cache key = scene content + engine + the browser that would render now; a hit is trusted only after its
    files exist, the PNG hash matches and the scene's assets still verify. Otherwise a fresh directory is used."""
    from common import TOOL_VERSION
    from renderer_env import pin_of, requested_channel
    from validate_model import check_scene

    fp = runtime_fingerprint(requested_channel(pin_of(scene, tdir)))
    key = hashlib.sha256(f"{_scene_key(scene)}|{TOOL_VERSION}|{fp}".encode()).hexdigest()[:16]
    out = Path(vd) / "renders" / key
    rep = out / "render.report.json"
    if rep.exists() and (set(formats) <= {"png"} or (out / "render.svg").exists()):
        r = _rebase(read_json(rep), out)
        from common import sha256_file

        masks_ok = all(Path(b["mask"]).exists() for b in r.get("bounds", {}).values() if b.get("mask"))
        if Path(r["png"]).exists() and sha256_file(r["png"]) == r["png_sha256"] and masks_ok and check_scene(scene, tdir)["valid"] \
                and f"{r['render_profile']['channel']} {r['render_profile']['browser_version']}" == fp:
            return r
        import datetime as _dt

        out = out.with_name(f"{key}-{_dt.datetime.now():%Y%m%d%H%M%S}")  # never overwrite; the stale entry stays as evidence
    return render(scene, tdir, out, isolate=True, formats=formats)


def approved_baseline(tdir, base):
    """The approved baseline applies when the base model IS the approved model (same content hash)."""
    p = read_json(Path(tdir) / "passport.json").get("baseline_render")
    if p and p.get("scene_sha256") == model_hash(base) and (Path(tdir) / p["path"]).exists():
        return p
    return None


def _mask(report, nid, shape):
    m = (report["bounds"].get(nid) or {}).get("mask")
    if m and Path(m).exists():
        return np.asarray(Image.open(m)) > 0
    return np.zeros(shape, bool)


def _intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def model_changes(base, after, changes, scope) -> dict:
    req = sorted({c["path"] for c in changes if c["kind"] == "requested"})
    deps = [{"path": c["path"], "why": c["why"]} for c in changes if c["kind"] == "dependency"]
    vis = [{"path": c["path"], "why": c["why"]} for c in changes if c["kind"] == "visual"]
    notes = [{"path": c["path"], "why": c["why"]} for c in changes if c["kind"] == "note"]
    authorized = set(req) | {d["path"] for d in deps}  # visual-only and note records authorise no model change
    actual = [p for p in diff_paths(base, after) if p.split(".")[0] not in IGNORED]
    unexplained = [p for p in actual if not any(p == a or p.startswith(a + ".") for a in authorized)]
    out = {"compared_against": f"revision {base['revision']} model", "requested": req, "dependencies": deps,
           "visual_dependencies": vis, "notes": notes,
           "actual_changed_paths": actual, "unexplained": unexplained, "status": "fail" if unexplained else "pass"}
    if scope:
        leaves = [p for p in leaf_paths(base) if p.split(".")[0] not in IGNORED]
        frozen = [p for p in leaves if not any(p == x or p.startswith(x + ".") for x in authorized)]
        out["frozen"] = {"rule": "keep everything else", "frozen_leaf_paths": len(frozen), "of_total": len(leaves),
                         "authorized": sorted(authorized), "violations": unexplained}
    return out


def leaf_paths(o, prefix=""):
    """Every leaf property path of a model (id'd lists addressed by id, like diff_paths)."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaf_paths(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(o, list) and o and all(isinstance(x, dict) and "id" in x for x in o):
        for x in o:
            yield from leaf_paths(x, f"{prefix}.{x['id']}")
    else:
        yield prefix


def probe_requested(changes, rb, ra) -> list:
    """Check requested edits against the actual renders, not just the model."""
    img_a = np.asarray(Image.open(ra["png"]).convert("RGB"))
    img_b = np.asarray(Image.open(rb["png"]).convert("RGB"))
    resized = img_a.shape != img_b.shape  # canvas changed (reflow): pixel-by-pixel probes do not apply
    out = []
    for c in (c for c in changes if c["kind"] == "requested"):
        p, res = c["path"], {"path": c["path"], "status": "unknown", "probe": "no render probe for this property"}
        nid = p.split(".")[1] if p.startswith("nodes.") else None
        if nid and resized:
            fp = (ra["bounds"].get(nid) or {}).get("rendered")
            H, W = img_a.shape[:2]
            inside = bool(fp) and fp[0] >= -0.5 and fp[1] >= -0.5 and fp[0] + fp[2] <= W + 0.5 and fp[1] + fp[3] <= H + 0.5
            res = {"path": p, "status": "pass" if inside else "fail",
                   "probe": f"canvas changed to {W}x{H}; node rendered at {fp} (reflow_preserve carries the layout verdict)"}
        elif nid and p.endswith((".geometry.x", ".geometry.y")):
            ax = 0 if p.endswith(".x") else 1
            b0, b1 = (rb["bounds"].get(nid) or {}).get("rendered"), (ra["bounds"].get(nid) or {}).get("rendered")
            if b0 and b1:
                moved = b1[ax] - b0[ax]
                res = {"path": p, "status": "pass" if abs(moved - (c["after"] - c["before"])) <= 0.5 else "fail",
                       "probe": f"rendered footprint moved {moved}px (requested {c['after'] - c['before']})"}
        elif nid and p.endswith(".content"):
            fit = ra["fit"].get(nid, {})
            res = {"path": p, "status": "pass" if fit.get("status") in ("fits", "fitted") else "fail",
                   "probe": f"rendered; fit={fit.get('status')} size={fit.get('size')} lines={fit.get('lines')}"}
        elif nid and p.endswith(".asset"):
            m = _mask(ra, nid, img_a.shape[:2])
            changed = int(np.count_nonzero((np.abs(img_a.astype(int) - img_b.astype(int)).max(axis=2) > 0) & m))
            res = {"path": p, "status": "pass" if changed else "fail", "probe": f"{changed} pixels changed inside the node's footprint"}
        elif p.startswith("tokens.") and isinstance(c["after"], str) and c["after"].startswith("#"):
            target = [int(c["after"][i:i + 2], 16) for i in (1, 3, 5)]
            bound = sorted({d["path"].split(".")[1] for d in changes if d["kind"] == "visual" and d["why"] == "bound to the edited token"})
            hits = {}
            for nid2 in bound:
                px = img_a[_mask(ra, nid2, img_a.shape[:2])]
                close = px[np.abs(px.astype(int) - target).max(axis=1) <= 6] if len(px) else px
                hits[nid2] = bool(len(close)) and delta_e(np.median(close, axis=0), target) <= 1
            res = {"path": p, "status": "pass" if hits and all(hits.values()) else ("unknown" if not hits else "fail"),
                   "probe": f"new colour present in each bound node's footprint: {hits}"}
        elif nid and p.split(".", 2)[-1].split(".")[0] in MODEL_ONLY:
            res = {"path": p, "status": "pass", "probe": "model-only property (no visual effect expected)"}
        elif nid:  # generic: something must change inside the node's own footprint
            m = _mask(ra, nid, img_a.shape[:2]) | _mask(rb, nid, img_a.shape[:2])
            k = int(np.count_nonzero((np.abs(img_a.astype(int) - img_b.astype(int)).max(axis=2) > 0) & m))
            res = {"path": p, "status": "pass" if k else "unknown",
                   "probe": f"{k} pixels changed inside the node's footprint" + ("" if k else " (requested change has no visible effect)")}
        out.append(res)
    return out


def visual_changes(base_png, cand_png, rb, ra, affected, after, out_png) -> dict:
    a, b = decode_rgba(base_png), decode_rgba(cand_png)  # alpha changes count as changes
    H, W = a.shape[:2]
    changed = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > 0
    whole = any(n["type"] == "background" and n["id"] in affected for n in after["nodes"])
    infl = np.ones((H, W), bool) if whole else np.zeros((H, W), bool)
    if not whole:
        for nid in affected:
            infl |= _mask(rb, nid, (H, W)) | _mask(ra, nid, (H, W))
        from scipy.ndimage import binary_dilation

        infl = binary_dilation(infl, iterations=DILATE_PX)
    by_node = []
    for n in after["nodes"]:
        if n["type"] in ("background", "group"):
            continue
        m = _mask(ra, n["id"], (H, W)) | _mask(rb, n["id"], (H, W))
        k = int(np.count_nonzero(changed & m))
        if k:
            why = "edited / dependency" if n["id"] in affected else (
                "translucent or blended over a changed region (properties unchanged)" if n.get("opacity", 1) < 1 or n.get("blend", "normal") != "normal"
                else "overlaps a changed region (antialiased edges or backdrop; properties unchanged)")
            by_node.append({"node": n["id"], "changed_pixels": k, "affected": n["id"] in affected, "why": why})
    viz = (np.asarray(Image.fromarray(b).convert("L").convert("RGB")) * 0.5).astype(np.uint8)  # (RGBA -> L ignores alpha; display only)
    viz[infl & ~changed] = (viz[infl & ~changed] * 0.6 + np.array([0, 60, 160]) * 0.4).astype(np.uint8)
    viz[changed & infl] = [255, 200, 0]
    viz[changed & ~infl] = [255, 0, 0]
    Image.fromarray(viz).save(out_png)
    outside = int(np.count_nonzero(changed & ~infl))
    return {"changed_pixels": int(changed.sum()), "inside_influence": int(np.count_nonzero(changed & infl)),
            "outside_influence": outside,
            "influence": {"method": "union of per-node alpha masks (before + after) of edited nodes and dependencies, dilated "
                                    f"{DILATE_PX}px; declared before the pixel comparison", "nodes": affected,
                          "fraction": float(infl.mean()), "whole_canvas": whole},
            "by_node": by_node,
            "compositing_consequences": [x for x in by_node if not x["affected"] and x["why"].startswith("translucent")],
            "status": "not_applicable" if whole else ("pass" if outside == 0 else "fail"),
            "note": "whole-canvas influence: property/invariant checks carry the verdict" if whole else "",
            "artifact": str(out_png), "legend": "yellow = changed inside influence, red = changed OUTSIDE influence, blue = influence"}


def verify_change(tdir, vd, base, after, changes, mode, scope=None, origin=None, cumulative=None) -> dict:
    rb, ra = render_cached(tdir, vd, base), render_cached(tdir, vd, after)
    v = {"model_changes": model_changes(base, after, changes, scope), "requested_edits": probe_requested(changes, rb, ra),
         "renders": {"base": rb["png"], "candidate": ra["png"]}, "renderer": ra.get("pin_check")}
    base_png, against = rb["png"], f"revision {base['revision']} render (pinned renderer)"
    ab = approved_baseline(tdir, base)
    checks = [v["model_changes"]["status"]]
    if ab:
        same = pixel_metrics(decode_rgba(rb["png"]), decode_rgba(Path(tdir) / ab["path"]))["unequal_pixels"] == 0
        v["approved_baseline"] = {"path": ab["path"], "sha256": ab["sha256"], "pinned_re_render_reproduces_it": same}
        base_png, against = Path(tdir) / ab["path"], f"approved template baseline {ab['path']}"
        checks.append("pass" if same else "fail")
    out_png = Path(ra["png"]).with_name("visual_diff.png")
    if mode == "reflow":
        W, H = after["canvas"]["width"], after["canvas"]["height"]
        outside = [n for n, bb in ra["bounds"].items() if bb["rendered"] and (bb["rendered"][0] < 0 or bb["rendered"][1] < 0
                   or bb["rendered"][0] + bb["rendered"][2] > W or bb["rendered"][1] + bb["rendered"][3] > H)]
        ro_b, ro_a = reading_order(base), reading_order(after)
        nodes_ = [n for n in after["nodes"] if n["type"] not in ("background", "group")]
        new_overlaps = []
        for i, n1 in enumerate(nodes_):
            for n2 in nodes_[i + 1:]:
                g = [(r["bounds"].get(n["id"]) or {}).get("rendered") for r in (ra, rb) for n in (n1, n2)]
                if all(g) and _intersects(g[0], g[1]) and not _intersects(g[2], g[3]):
                    new_overlaps.append([n1["id"], n2["id"]])
        v["reflow_preserve"] = {"target_dims": [W, H], "outside_canvas": outside, "reading_order_preserved": ro_b == ro_a,
                                "reading_order": ro_a, "new_overlaps": new_overlaps,
                                "text_fit": {k: x["status"] for k, x in ra["fit"].items()},
                                "status": "pass" if not outside and ro_b == ro_a and not new_overlaps else "fail",
                                "note": "whole-image pixel comparison across aspect ratios is not an identity test"}
        checks.append(v["reflow_preserve"]["status"])
    else:
        affected = sorted({c["path"].split(".")[1] for c in changes if c["path"].startswith("nodes.")})
        v["visual_changes"] = dict(compared_against=against, **visual_changes(base_png, ra["png"], rb, ra, affected, after, out_png))
        checks.append(v["visual_changes"]["status"])
        locks = [lk for lk in after["locks"] if lk["kind"] == "pixel" and lk.get("box")]
        if locks:
            a, b = decode_rgba(base_png), decode_rgba(ra["png"])
            ch = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > 0
            res = []
            for lk in locks:
                x, y, w, h = [int(round(t)) for t in lk["box"]]
                k = int(np.count_nonzero(ch[max(0, y):y + h, max(0, x):x + w]))
                res.append({"lock": lk["id"], "box": lk["box"], "changed_pixels": k, "status": "pass" if k == 0 else "fail"})
            v["pixel_locks"] = res
            checks += [r["status"] for r in res]
    ab0 = approved_baseline(tdir, origin) if origin is not None and mode != "reflow" else None
    same_canvas = origin is not None and [origin["canvas"][k] for k in ("width", "height")] == [after["canvas"][k] for k in ("width", "height")]
    if ab0 and not same_canvas:  # an earlier reflow changed the canvas: model changes still checked, pixels are not an identity test
        mc0 = model_changes(origin, after, cumulative, scope)
        v["vs_approved_baseline"] = {"baseline": ab0["path"], "model_changes": mc0, "visual_changes": {
            "status": "not_applicable", "note": "canvas differs from the approved baseline (reflowed variant); see reflow_preserve"}}
        checks.append(mc0["status"])
    elif ab0:  # cumulative: everything authorised since the approved baseline, checked against that baseline image
        ro = render_cached(tdir, vd, origin)
        aff = sorted({c["path"].split(".")[1] for c in cumulative if c["path"].startswith("nodes.")})
        mc0 = model_changes(origin, after, cumulative, scope)
        vc0 = visual_changes(Path(tdir) / ab0["path"], ra["png"], ro, ra, aff, after, Path(ra["png"]).with_name("visual_diff_vs_baseline.png"))
        v["vs_approved_baseline"] = {"baseline": ab0["path"], "model_changes": mc0,
                                     "visual_changes": dict(compared_against=f"approved template baseline {ab0['path']}", **vc0)}
        checks += [mc0["status"], vc0["status"]]
    checks += [r["status"] for r in v["requested_edits"]]
    v["status"] = "fail" if "fail" in checks else ("pass_with_unknowns" if "unknown" in checks else "pass")
    return v
