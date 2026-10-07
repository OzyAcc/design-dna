"""Compile an edit request into typed engine operations. Nothing here edits anything: the result is previewed (a dry-run
transaction reports scope, dependencies, lock and constraint conflicts) and committed only on an explicit apply.

Accepted forms, in order:
  1. the engine's formal syntax: set <path> = <json> · move <node> by x=<n>px y=<n>px · resize <node> to w=<n>px h=<n>px
     · lock <targets> [soft] · unlock <target> · hide <node> · show <node>
  2. common phrasings: "move the headline up 12px", "make the accent #FFD400", "change the headline to ...",
     "hide the logo"
  3. otherwise, when a copy provider is configured, Claude proposes typed ops from the node/token list (a proposal that
     the same preview step checks). User words are data: they never reach a shell or the engine's command parser.
"""
from __future__ import annotations

import json
import re
import shlex

from .errors import AppError

HEX = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def _px(v: str) -> float:
    return float(re.sub(r"px$", "", v))


def _node_ref(scene, word: str):
    word = word.lower().strip().removeprefix("the ").strip()
    for n in scene["nodes"]:
        if word in (n["id"].lower(), (n.get("alias") or "").lower(), (n.get("role") or "").lower()):
            return n
    hits = [n for n in scene["nodes"] if word and (word in (n.get("alias") or "").lower() or word in (n.get("role") or "").lower())]
    return hits[0] if len(hits) == 1 else None


def formal(line: str):
    t = shlex.split(line, posix=True)
    if not t:
        return None
    cmd, a = t[0].lower(), t[1:]
    kv = dict(x.split("=", 1) for x in a if "=" in x and not x.startswith("="))
    if cmd == "set" and len(a) >= 3 and a[1] == "=":
        raw = line.split("=", 1)[1].strip()
        try:
            val = json.loads(raw)
        except ValueError:
            val = raw.strip('"')
        return [{"op": "set", "path": a[0], "value": val}]
    if cmd == "move" and len(a) >= 2 and a[1] == "by" and ("x" in kv or "y" in kv):
        return [{"op": "move", "node": a[0], "dx": _px(kv.get("x", "0")), "dy": _px(kv.get("y", "0"))}]
    if cmd == "resize" and len(a) >= 2 and a[1] == "to" and "w" in kv and "h" in kv:
        return [{"op": "resize", "node": a[0], "w": _px(kv["w"]), "h": _px(kv["h"]), "anchor": kv.get("anchor", "top-left")}]
    if cmd == "lock" and a:
        if a[0] == "pixels" and len(a) > 1:
            return [{"op": "lock", "target": "region", "kind": "pixel", "box": [float(v) for v in a[1].split(",")], "hard": True}]
        return [{"op": "lock", "target": x, "hard": "soft" not in a} for x in a[0].split(",")]
    if cmd == "unlock" and a:
        return [{"op": "unlock", "target": x} for x in a[0].split(",")]
    if cmd in ("hide", "show") and len(a) == 1 and "." not in a[0] and a[0] != "the":
        return [{"op": "set", "path": f"{a[0]}.visible", "value": cmd == "show"}]
    return None


def phrasing(scene, text: str):
    s = text.strip().rstrip(".").lower()
    m = re.match(r"(?:move|nudge|shift) (?:the )?(.+?) (up|down|left|right) (?:by )?(\d+(?:\.\d+)?) ?(?:px|pixels?)$", s)
    if m:
        n = _node_ref(scene, m.group(1))
        if n:
            dx, dy = DIRS[m.group(2)]
            k = float(m.group(3))
            return [{"op": "move", "node": n["id"], "dx": dx * k, "dy": dy * k}]
    m = re.match(r"(?:make|change|set|turn) (?:only )?(?:the )?(.+?) (?:colou?r )?(?:to |into )?(#[0-9a-f]{6})$", s)
    if m:
        target = m.group(1).replace(" colour", "").replace(" color", "").strip()
        tok = [k for k in scene["tokens"] if target in k.lower() or target.replace(" ", ".") in k.lower()]
        if len(tok) == 1:
            return [{"op": "set", "path": f"tokens.{tok[0]}", "value": m.group(2).upper()}]
    m = re.match(r"(?:change|set) (?:the )?(.+?) (?:text |copy )?to [\"“']?(.+?)[\"”']?$", text.strip(), re.I)
    if m:
        n = _node_ref(scene, m.group(1))
        if n and n["type"] == "text":
            return [{"op": "set", "path": f"{n['id']}.content", "value": m.group(2)}]
    m = re.match(r"(hide|show) (?:the )?(.+)$", s)
    if m:
        n = _node_ref(scene, m.group(2))
        if n:
            return [{"op": "set", "path": f"{n['id']}.visible", "value": m.group(1) == "show"}]
    return None


def compile_request(scene, text: str, job_id=None) -> dict:
    text = (text or "").strip()
    if not text:
        raise AppError("type a change to compile", "empty_command")
    if len(text) > 2000:
        raise AppError("that request is too long; describe one change at a time", "too_long")
    try:
        ops = formal(text)
    except (ValueError, KeyError):
        ops = None
    if ops:
        return {"ops": ops, "compiled_by": "formal syntax"}
    ops = phrasing(scene, text)
    if ops:
        return {"ops": ops, "compiled_by": "phrase rules"}
    return _with_model(scene, text, job_id)


OPS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ops", "explanation", "unsupported"],
              "properties": {"explanation": {"type": "string"}, "unsupported": {"type": "string"},
                             "ops": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                               "required": ["op", "path", "node", "value_json", "dx", "dy"],
                                                               "properties": {"op": {"enum": ["set", "move"]}, "path": {"type": "string"},
                                                                              "node": {"type": "string"}, "value_json": {"type": "string"},
                                                                              "dx": {"type": "number"}, "dy": {"type": "number"}}}}}}


def _with_model(scene, text, job_id):
    from .providers import ProviderError, for_capability, tracked

    try:
        prov = for_capability("copy")
    except ProviderError:
        raise AppError("this request is not in a supported form; use e.g. 'move headline up 10px', 'make the accent #FFD400', "
                       "'set headline.content = \"New text\"', or configure Claude to compile free-form requests", "not_compiled")
    if prov.mock:
        raise AppError("free-form compilation needs a real copy provider (the mock cannot compile requests)", "not_compiled")
    nodes = [{"id": n["id"], "alias": n.get("alias"), "type": n["type"], "role": n.get("role"), "geometry": n.get("geometry"),
              "content": n.get("content")} for n in scene["nodes"]]
    req = {"request": text, "nodes": nodes, "tokens": {k: v.get("value") for k, v in scene["tokens"].items()},
           "rules": "Return the smallest set of typed ops that does exactly what was asked and nothing else. 'set' uses path "
                    "<node id>.<property> or tokens.<token key> and value_json (a JSON literal); 'move' uses node, dx, dy in px. "
                    "If something cannot be expressed, leave ops empty and explain in unsupported."}
    from .providers.anthropic_provider import AnthropicProvider

    p = AnthropicProvider()
    content = [{"type": "text", "text": json.dumps(req, ensure_ascii=False)}]
    with tracked(p.name, "compile_edit", p.copy_model, job_id) as tr:
        data, meta = p._structured(p.copy_model, "You translate one design edit request into typed operations for a template engine.",
                                   content, OPS_SCHEMA, "medium", tr)
    ops = []
    for o in data.get("ops", []):
        if o["op"] == "set":
            try:
                val = json.loads(o["value_json"])
            except ValueError:
                val = o["value_json"]
            ops.append({"op": "set", "path": o["path"], "value": val})
        else:
            ops.append({"op": "move", "node": o["node"], "dx": o["dx"], "dy": o["dy"]})
    if not ops:
        raise AppError(data.get("unsupported") or "this change cannot be expressed as a supported operation", "unsupported_edit")
    return {"ops": ops, "compiled_by": f"{meta['provider']} {meta['model']}", "explanation": data.get("explanation"),
            "request_id": meta.get("request_id")}
