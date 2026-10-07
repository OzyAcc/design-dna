"""Typed operations, lock coverage and constraint evaluation for Design DNA patches.

Each op mutates a scene copy and returns change records:
  {"path": normalized path, "before": ..., "after": ..., "kind": "requested"|"dependency", "why": str}
Ops never touch properties they do not own; dependencies are explicit and reported.
"""
from __future__ import annotations

import re
from pathlib import Path

from common import DnaError, deep, diff_paths, find_node, import_asset, node_map, resolve  # noqa: F401
from validate_model import _walk_refs, resolved_font

COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
RTL_LANGS = {"ar", "he", "fa", "ur"}
EDGES = ("left", "right", "top", "bottom", "center_x", "center_y", "width", "height", "baseline")


def adopt_asset(scene, rec) -> dict:
    """Same content hash = same asset: keep the existing record instead of rewriting its provenance."""
    return scene["assets"].setdefault(rec["id"], rec)


def change(path, before, after, kind="requested", why=""):
    """kind: requested (asked for) | dependency (a model change the request implies) |
    visual (pixels change, model does not: e.g. token-bound fills) | note (information only, authorises nothing)."""
    return {"path": path, "before": before, "after": after, "kind": kind, "why": why}


# ------------------------------------------------------------------ locks
LOCK_CATEGORIES = {
    "layout": lambda p, n: n is not None and any(s in p for s in (".geometry", ".transform", ".first_baseline")),
    "typography": lambda p, n: n is not None and n["type"] == "text" and any(
        s in p for s in (".font", ".align", ".tracking", ".line_height", ".direction", ".lang")),
    "background": lambda p, n: n is not None and n["type"] == "background",
    "content": lambda p, n: n is not None and (p.endswith(".content") or p.endswith(".asset")),
    "color": lambda p, n: p.startswith("tokens.") or ".fill" in p or ".stroke" in p,
    "effects": lambda p, n: ".effects" in p or ".treatment" in p,
}


def lock_prefix(scene, target: str):
    if target.startswith("tokens."):
        return target
    n = find_node(scene, target.split(".")[0], required=False)
    if n is None:
        raise DnaError(f"lock target {target!r} is neither a category {sorted(LOCK_CATEGORIES)} nor a node/token path", "bad_lock")
    rest = target.split(".", 1)[1] if "." in target else ""
    return f"nodes.{n['id']}" + (f".{rest}" if rest else "")


WHOLE_NODE_CATEGORIES = {  # categories that a node's removal/replacement as a whole falls under
    "layout": lambda n: True, "typography": lambda n: n["type"] == "text", "background": lambda n: n["type"] == "background",
    "content": lambda n: n["type"] in ("text", "image", "background"), "color": lambda n: bool(n.get("fill") or n.get("stroke")),
    "effects": lambda n: bool(n.get("effects") or n.get("treatment")),
}


def lock_covers(scene, lock, path, node, alt_scene=None) -> bool:
    """True when `path` equals the locked path, lies under it, or is an ANCESTOR of it (the object holding the
    locked property was replaced or removed). Categories are evaluated for whole-node changes too."""
    t = lock["target"]
    if t in LOCK_CATEGORIES:
        if node is not None and re.fullmatch(r"nodes\.[^.]+", path):
            return WHOLE_NODE_CATEGORIES[t](node)
        return LOCK_CATEGORIES[t](path, node)
    try:
        pre = lock_prefix(scene, t)
    except DnaError:
        if alt_scene is None:
            raise
        pre = lock_prefix(alt_scene, t)  # the locked node may exist only in the other state (removed / added)
    return path == pre or path.startswith(pre + ".") or pre.startswith(path + ".")


def check_locks(before, after, changes) -> tuple[list, list]:
    """Locks are enforced on the ACTUAL before/after leaf differences, not on what the ops declared, so replacing a
    parent object or deleting a node cannot slip past a lock. Hard locks conflict; soft locks yield only to a
    requested edit (recorded as override). Locks in effect = those of the candidate (an explicit unlock in the
    same patch is an explicit authorisation)."""
    nb, na = node_map(before), node_map(after)
    requested = {c["path"] for c in changes if c["kind"] == "requested"}
    actual = [p for p in diff_paths(before, after) if p.split(".")[0] not in ("locks", "assets", "revision", "base_revision",
                                                                                 "variant", "render_profile")]
    conflicts, overrides = [], []
    for p in actual:
        m = re.match(r"nodes\.([^.]+)", p)
        node = (na.get(m.group(1)) or nb.get(m.group(1))) if m else None
        kind = "requested" if any(p == r or p.startswith(r + ".") or r.startswith(p + ".") for r in requested) else "dependency"
        for lk in after["locks"]:
            if lk["kind"] == "pixel":  # pixel locks are verified on the render (verify_change.py)
                continue
            if lock_covers(after, lk, p, node, before):
                rec = {"lock": lk["id"], "target": lk["target"], "path": p, "kind": kind}
                if lk["hard"]:
                    conflicts.append(dict(rec, resolve=f"unlock {lk['target']} (or narrow the lock) to allow this change"))
                elif kind == "requested":
                    overrides.append(rec)
                else:
                    conflicts.append(dict(rec, resolve="dependency would change a soft-locked property; authorize it explicitly"))
    return conflicts, overrides


# ------------------------------------------------------------------ constraints
def edge_value(scene, ref: str):
    obj, edge = ref.rsplit(".", 1)
    if edge not in EDGES:
        raise DnaError(f"unknown edge {edge!r} in {ref!r}", "bad_constraint")
    if obj == "canvas":
        W, H = scene["canvas"]["width"], scene["canvas"]["height"]
        g = {"x": 0, "y": 0, "w": W, "h": H}
        base = None
    else:
        n = find_node(scene, obj)
        g, base = n["geometry"], n.get("first_baseline")
    vals = {"left": g["x"], "right": g["x"] + g["w"], "top": g["y"], "bottom": g["y"] + g["h"],
            "center_x": g["x"] + g["w"] / 2, "center_y": g["y"] + g["h"] / 2, "width": g["w"], "height": g["h"], "baseline": base}
    if vals[edge] is None:
        raise DnaError(f"{ref!r} has no baseline", "bad_constraint")
    return vals[edge]


def eval_constraint(scene, c) -> dict:
    a, b = edge_value(scene, c["a"]), edge_value(scene, c["b"])
    tol = c.get("tolerance", 0.5)
    if c["type"] in ("gap", "anchor"):
        actual, ok = a - b, abs((a - b) - c["value"]) <= tol
    elif c["type"] == "equal":
        actual, ok = a - b, abs(a - b) <= tol
    elif c["type"] == "ratio":
        actual = a / b if b else float("inf")
        ok = abs(actual - c["value"]) <= tol
    else:
        actual = a - b
        ok = c.get("min", float("-inf")) - tol <= actual <= c.get("max", float("inf")) + tol
    return {"id": c["id"], "ok": ok, "actual": round(actual, 3), "expected": c.get("value", [c.get("min"), c.get("max")])}


def check_constraints(before, after, mode, relax=(), requested_nodes=()) -> tuple[list, list]:
    """Newly broken constraints conflict, except (a) ids listed in `relax`, and (b) relaxable measured relationships
    that involve a node the user explicitly edited -- the request overrides the measurement, and the relaxation is
    reported with before/after values. Non-relaxable (required) constraints always conflict."""
    conflicts, notes = [], []
    for c in after["constraints"]:
        if c.get("modes") and mode not in c["modes"]:
            continue
        try:
            was, now_ = eval_constraint(before, c), eval_constraint(after, c)
        except DnaError as e:
            if e.code == "unknown_target":
                conflicts.append({"constraint": c["id"], "problem": "a referenced node was removed"})
                continue
            raise
        if not was["ok"]:
            notes.append({"constraint": c["id"], "note": "already unsatisfied before this patch", **was})
        elif not now_["ok"]:
            touched = {ref.rsplit(".", 1)[0] for ref in (c["a"], c["b"])} & set(requested_nodes)
            if c.get("relaxable", False) and (c["id"] in relax or touched):
                notes.append({"constraint": c["id"], "relaxed": True, "before": was["actual"], "after": now_["actual"],
                              "note": "relaxed by an explicit edit of " + ", ".join(sorted(touched)) if touched else "relaxed by request",
                              **now_})
            else:
                conflicts.append({"constraint": c["id"], "a": c["a"], "b": c["b"], "type": c["type"], **now_,
                                  "resolve": "change the request, move the related node too, or relax this constraint"
                                             + ("" if c.get("relaxable") else " (marked non-relaxable: edit the constraint)")})
    return conflicts, notes


# ------------------------------------------------------------------ ops
def _descendants(scene, n):
    idx = node_map(scene)
    out = []
    for c in n.get("children", []):
        out.append(idx[c])
        out += _descendants(scene, idx[c])
    return out


def op_set(scene, op, tdir):
    c, k, norm, node = resolve(scene, op["path"])
    before = c.get(k) if isinstance(c, dict) else c[k]
    v = op["value"]
    if before is not None and not (isinstance(before, (int, float)) and isinstance(v, (int, float))) \
            and type(before) is not type(v):
        raise DnaError(f"{op['path']}: expected {type(before).__name__}, got {type(v).__name__}", "type_mismatch")
    if isinstance(before, str) and COLOR_RE.match(before) and not (isinstance(v, str) and COLOR_RE.match(v)):
        raise DnaError(f"{op['path']}: {v!r} is not a #RRGGBB[AA] color", "type_mismatch")
    c[k] = v
    out = [change(norm, before, v)]
    if norm.startswith("tokens."):
        key = next(t for t in sorted(scene["tokens"], key=len, reverse=True) if norm.startswith(f"tokens.{t}."))
        for n in scene["nodes"]:
            for field in ("fill", "stroke", "font"):
                if key in _walk_refs(n.get(field), "token"):
                    out.append(change(f"nodes.{n['id']}.{field}", f"token:{key}", f"token:{key}",
                                      "visual", "bound to the edited token"))
    return out


def op_move(scene, op, tdir):
    n = find_node(scene, op["node"])
    out = []
    for m in [n] + _descendants(scene, n):
        g = m["geometry"]
        for axis, d in (("x", op["dx"]), ("y", op["dy"])):
            if d:
                out.append(change(f"nodes.{m['id']}.geometry.{axis}", g[axis], g[axis] + d,
                                  "requested" if m is n else "dependency", "" if m is n else "descendant of moved group"))
                g[axis] += d
        if m["type"] == "text" and op["dy"]:
            out.append(change(f"nodes.{m['id']}.first_baseline", m["first_baseline"], m["first_baseline"] + op["dy"],
                              "dependency", "baseline travels with its text box"))
            m["first_baseline"] += op["dy"]
    return out


def op_resize(scene, op, tdir):
    n = find_node(scene, op["node"])
    g = n["geometry"]
    anchor = op.get("anchor", "top-left")
    fx = {"top-left": 0, "bottom-left": 0, "center": .5, "top-right": 1, "bottom-right": 1}[anchor]
    fy = {"top-left": 0, "top-right": 0, "center": .5, "bottom-left": 1, "bottom-right": 1}[anchor]
    nx, ny = g["x"] + (g["w"] - op["w"]) * fx, g["y"] + (g["h"] - op["h"]) * fy
    out = [change(f"nodes.{n['id']}.geometry.{k}", g[k], v) for k, v in (("x", nx), ("y", ny), ("w", op["w"]), ("h", op["h"])) if g[k] != v]
    if n["type"] == "text" and ny != g["y"]:
        out.append(change(f"nodes.{n['id']}.first_baseline", n["first_baseline"], n["first_baseline"] + ny - g["y"], "dependency", "baseline travels with box"))
        n["first_baseline"] += ny - g["y"]
    g.update(x=nx, y=ny, w=op["w"], h=op["h"])
    return out


def op_replace(scene, op, tdir):
    n = find_node(scene, op["node"])
    if n["type"] not in ("image", "background"):
        raise DnaError(f"{n['id']} is a {n['type']} node; replace targets image assets", "bad_target")
    # a synthesized image keeps its provenance (`generated`); it is never recorded as a supplied or recovered original
    rec = adopt_asset(scene, import_asset(tdir, op["file"], "image", op.get("source", "supplied"), baked_effects=op.get("baked_effects", [])))
    before = n.get("asset")
    n["asset"] = rec["id"]
    out = [change(f"nodes.{n['id']}.asset", before, rec["id"])]
    old = scene["assets"].get(before) or {}
    if old.get("width") and abs(old["width"] / old["height"] - rec["width"] / rec["height"]) > 0.01:
        out.append(change(f"nodes.{n['id']}.placement", "aspect " + f"{old['width'] / old['height']:.3f}",
                          "aspect " + f"{rec['width'] / rec['height']:.3f}", "note",
                          "new asset aspect differs; fit/focal anchor kept, visible crop changes (no deformation)"))
    baked = set(rec.get("baked_effects", []))
    live = [fx for fx in n.get("effects", []) if fx["type"] == "drop_shadow" and fx.get("enabled", True)]
    if baked & {"cast_shadow", "drop_shadow", "contact_shadow"} and live:
        raise DnaError("double shadow: the new asset already contains a baked shadow and the node has an editable one",
                       "double_shadow", {"node": n["id"], "editable_shadows": [fx["id"] for fx in live], "options": [
                           f"set {n.get('alias', n['id'])}.effects.{live[0]['id']}.enabled = false in the same patch",
                           "supply a clean cutout without the baked shadow"]})
    return out


def op_remove(scene, op, tdir):
    n = find_node(scene, op["node"])
    used = [s["id"] for s in scene["slots"] if s["node"] == n["id"]]
    if used and not op.get("force"):
        raise DnaError(f"{n['id']} backs slot(s) {used}; removing it breaks the template", "slot_conflict",
                       {"options": ["remove the slot too with force=true", "hide it instead: set <node>.visible = false"]})
    gone = [n] + _descendants(scene, n)
    ids = {m["id"] for m in gone}
    scene["nodes"] = [m for m in scene["nodes"] if m["id"] not in ids]
    if n.get("parent"):
        p = find_node(scene, n["parent"])
        p["children"] = [c for c in p["children"] if c != n["id"]]
    scene["slots"] = [s for s in scene["slots"] if s["node"] not in ids]
    return [change(f"nodes.{i}", "present", None) for i in sorted(ids)]


def op_add(scene, op, tdir):
    nd = deep(op["node_def"])
    if any(m["id"] == nd["id"] for m in scene["nodes"]):
        raise DnaError(f"node id {nd['id']} already exists", "duplicate_id")
    nd.setdefault("provenance", {"*": {"status": "inferred", "confidence": "unassessed", "note": "added by adaptation, not scanned"}})
    order = [m["id"] for m in scene["nodes"]]
    at = order.index(op["after"]) + 1 if op.get("after") in order else len(order)
    scene["nodes"].insert(at, nd)
    if nd.get("parent"):
        find_node(scene, nd["parent"])["children"].append(nd["id"])
    return [change(f"nodes.{nd['id']}", None, "present")]


def op_lock(scene, op, tdir):
    kind = op.get("kind", "property")
    if kind == "pixel":
        if not op.get("box") or len(op["box"]) != 4:
            raise DnaError("a pixel lock needs a box [x, y, w, h]", "bad_lock")
    elif op["target"] not in LOCK_CATEGORIES:
        lock_prefix(scene, op["target"])  # validates the target
    lid = f"lock-{len(scene['locks']) + 1}-{re.sub(r'[^a-z0-9]+', '-', op['target'].lower())}"[:60]
    lk = {"id": lid, "target": op["target"], "kind": kind, "hard": op.get("hard", True)}
    if kind == "pixel":
        lk["box"] = op["box"]
    scene["locks"].append(lk)
    return [change(f"locks.{lid}", None, lk)]


def op_unlock(scene, op, tdir):
    hit = [lk for lk in scene["locks"] if lk["target"] == op["target"]]
    if not hit:
        raise DnaError(f"no lock with target {op['target']!r}", "unknown_lock", {"locks": [lk["target"] for lk in scene["locks"]]})
    scene["locks"] = [lk for lk in scene["locks"] if lk not in hit]
    return [change(f"locks.{lk['id']}", lk, None) for lk in hit]


def op_adapt(scene, op, tdir):
    lang, rtl = op["language"], op["language"].split("-")[0] in RTL_LANGS
    out = []
    font_rec = None
    if op.get("font"):
        font_rec = adopt_asset(scene, import_asset(tdir, op["font"], "font", "supplied"))
    for ref, text in op["contents"].items():
        n = find_node(scene, ref)
        if n["type"] != "text":
            raise DnaError(f"{ref} is not a text node", "bad_target")
        pid = f"nodes.{n['id']}"
        out.append(change(f"{pid}.content", n["content"], text))
        n["content"] = text
        for k, v, why in (("lang", lang, "language adaptation"), ("direction", "rtl" if rtl else "ltr", "script direction")):
            if n.get(k) != v:
                out.append(change(f"{pid}.{k}", n.get(k), v, "dependency", why))
                n[k] = v
        if rtl and n.get("tracking"):
            out.append(change(f"{pid}.tracking", n["tracking"], 0, "dependency", "tracking breaks Arabic joining"))
            n["tracking"] = 0
        if op.get("mirror_alignment", True) and rtl and n["align"] in ("left", "right"):
            new = {"left": "right", "right": "left"}[n["align"]]
            out.append(change(f"{pid}.align", n["align"], new, "dependency", "RTL reading start moves to the right edge"))
            n["align"] = new
        if font_rec:
            f = n["font"]
            out.append(change(f"{pid}.font.asset", f.get("asset"), font_rec["id"], "dependency", "script needs a font with its glyphs"))
            f["asset"] = font_rec["id"]
            out.append(change(f"{pid}.font.identity", f.get("identity"), "verified: supplied file", "dependency",
                              "user-supplied font file is the identity"))
            f["identity"] = {"status": "verified", "candidates": [font_rec["font_names"]],
                             "evidence_ids": [], "resolving_probe": None}
    return out


def _anchor(n, W, H, axis):
    pol = (n.get("reflow") or {}).get(axis)
    if pol:
        return pol
    g = n["geometry"]
    c = (g["x"] + g["w"] / 2) / W if axis == "x" else (g["y"] + g["h"] / 2) / H
    lo, hi = ("left", "right") if axis == "x" else ("top", "bottom")
    return lo if c < 1 / 3 else (hi if c > 2 / 3 else "center")


def reading_order(scene):
    """Rows = nodes whose vertical centre falls inside the current row's span; rows top-down, x within a row.
    Decorative/texture layers are not part of the reading sequence."""
    items = [n for n in scene["nodes"] if n["type"] not in ("background", "group", "effect")
             and n.get("role") not in ("decoration", "texture")]
    rows = []
    for n in sorted(items, key=lambda n: n["geometry"]["y"]):
        g = n["geometry"]
        cy = g["y"] + g["h"] / 2
        if rows and rows[-1]["top"] <= cy <= rows[-1]["bottom"]:
            rows[-1]["items"].append(n)
            rows[-1]["bottom"] = max(rows[-1]["bottom"], g["y"] + g["h"])
        else:
            rows.append({"top": g["y"], "bottom": g["y"] + g["h"], "items": [n]})
    return [n["id"] for r in rows for n in sorted(r["items"], key=lambda n: n["geometry"]["x"])]


def op_reflow(scene, op, tdir):
    W, H = scene["canvas"]["width"], scene["canvas"]["height"]
    W2, H2 = op["canvas"]
    s = min(W2 / W, H2 / H)
    out = [change("canvas.width", W, W2), change("canvas.height", H, H2)]
    for n in scene["nodes"]:
        g, pid = n["geometry"], f"nodes.{n['id']}"
        old, snap = dict(g), deep(n)
        if n["type"] == "background" or (n.get("reflow") or {}).get("x") == "stretch" and (n.get("reflow") or {}).get("y") == "stretch":
            g.update(x=g["x"] * W2 / W, y=g["y"] * H2 / H, w=g["w"] * W2 / W, h=g["h"] * H2 / H)
        else:
            ax, ay = _anchor(n, W, H, "x"), _anchor(n, W, H, "y")
            w2, h2 = (g["w"] * W2 / W if ax == "stretch" else g["w"] * s), (g["h"] * H2 / H if ay == "stretch" else g["h"] * s)
            x2 = {"left": g["x"] * s, "stretch": g["x"] * W2 / W, "right": W2 - (W - g["x"] - g["w"]) * s - w2,
                  "center": W2 / 2 + (g["x"] + g["w"] / 2 - W / 2) * s - w2 / 2}[ax]
            y2 = {"top": g["y"] * s, "stretch": g["y"] * H2 / H, "bottom": H2 - (H - g["y"] - g["h"]) * s - h2,
                  "center": H2 / 2 + (g["y"] + g["h"] / 2 - H / 2) * s - h2 / 2}[ay]
            g.update(x=x2, y=y2, w=w2, h=h2)
            if n["type"] == "text":
                n["first_baseline"] = y2 + (n["first_baseline"] - old["y"]) * s
                n["line_height"] *= s
                n["tracking"] = n.get("tracking", 0) * s
                if s != 1:
                    n["font"]["size"] = resolved_font(scene, n)["size"] * s
            for fx in n.get("effects", []):
                for k in ("dx", "dy", "blur", "spread"):
                    if k in fx:
                        fx[k] *= s
            if "radius" in n:
                n["radius"] *= s
            if (n.get("mask") or {}).get("radius"):
                n["mask"]["radius"] *= s
        if g != old:
            out.append(change(f"{pid}.geometry", old, dict(g), "requested", f"reflow anchors x={_anchor(n, W, H, 'x')} y={_anchor(n, W, H, 'y')}"))
        out += [change(f"{pid}.{p}", None, None, "dependency", "scaled/anchored with its node by reflow")
                for p in diff_paths(snap, n) if not p.startswith("geometry")]
    out.append(change("canvas.artwork_bounds", scene["canvas"].get("artwork_bounds"), [0, 0, W2, H2], "dependency", "canvas resized"))
    scene["canvas"]["width"], scene["canvas"]["height"] = W2, H2
    scene["canvas"]["artwork_bounds"] = [0, 0, W2, H2]
    return out


OPS = {"set": op_set, "move": op_move, "resize": op_resize, "replace": op_replace, "remove": op_remove,
       "add": op_add, "lock": op_lock, "unlock": op_unlock, "adapt": op_adapt, "reflow": op_reflow}


def apply_ops(scene, ops, tdir: Path):
    after = deep(scene)
    changes = []
    for i, op in enumerate(ops):
        for c in OPS[op["op"]](after, op, tdir):
            c["op_index"] = i
            changes.append(c)
    return after, changes
