"""Shared helpers for Design DNA: store layout, hashing, atomic JSON, evidence, property addressing.

Design text, metadata and template files are treated as data. Nothing read from a
template is ever executed or interpolated into a shell command.
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SKILL_DIR / "schemas"
SCHEMA_VERSION = "1.0.0"
TOOL_VERSION = "design-dna 1.0.0"
STATUSES = ("observed", "measured", "inferred", "unknown", "not_applicable")
SCAN_CATEGORIES = (
    "input_canvas", "composition", "element_inventory", "geometry", "color", "typography",
    "image_treatment", "depth_compositing", "surface_texture", "lighting", "hierarchy_attention",
    "message_mechanism", "character_theme", "usage_context", "responsive_system", "output_requirements",
)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class DnaError(Exception):
    """Actionable failure. `code` is machine-readable; `detail` carries options/conflicts."""

    def __init__(self, msg: str, code: str = "error", detail: dict | None = None):
        super().__init__(msg)
        self.code = code
        self.detail = detail or {}

    def as_dict(self) -> dict:
        return {"status": "error", "code": self.code, "message": str(self), "detail": self.detail}


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- store layout
def store_root() -> Path:
    return Path(os.environ.get("DESIGN_DNA_HOME") or Path.home() / "design-dna")


def template_dir(tid: str) -> Path:
    if not ID_RE.match(tid or ""):
        raise DnaError(f"invalid template id {tid!r}", "bad_id")
    return store_root() / "templates" / tid


def slugify(text: str, limit: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].strip("-") or "template"


def safe_path(base: Path, rel: str) -> Path:
    """Resolve rel under base; refuse anything that escapes (directory traversal guard)."""
    base = Path(base).resolve()
    p = (base / rel).resolve()
    if p != base and base not in p.parents:
        raise DnaError(f"path escapes the template directory: {rel!r}", "path_traversal")
    return p


# ---------------------------------------------------------------- hashing + io
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _np_default(o):
    if hasattr(o, "item") and hasattr(o, "dtype"):  # numpy scalar -> python scalar
        return o.item()
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


def write_json(p, data) -> None:
    """Atomic save: temp file in the same directory, then os.replace."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_np_default)
    os.replace(tmp, p)


def write_immutable(p, data: bytes) -> None:
    """Content-addressed write. Existing identical file = no-op; different content = refuse."""
    p = Path(p)
    if p.exists():
        if sha256_file(p) != sha256_bytes(data):
            raise DnaError(f"immutable file {p} already exists with different content", "immutable_conflict")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def font_names(path) -> dict:
    from fontTools.ttLib import TTFont

    with TTFont(path, fontNumber=0, lazy=True) as f:
        name = f["name"]
        get = lambda i: (name.getDebugName(i) or "")
        axes = [a.axisTag for a in f["fvar"].axes] if "fvar" in f else []
        return {"family": get(1), "subfamily": get(2), "full": get(4), "postscript": get(6),
                "face_index": 0, "variation_axes": axes}


def font_cmap(path) -> set[int]:
    from fontTools.ttLib import TTFont

    with TTFont(path, fontNumber=0, lazy=True) as f:
        return set(f.getBestCmap() or {})


def import_asset(tdir, src, kind: str, source: str, **extra) -> dict:
    """Copy a file into <template>/assets/ under its content hash; return the asset record."""
    data = Path(src).read_bytes()
    digest = sha256_bytes(data)
    ext = Path(src).suffix.lower() or ".bin"
    rel = f"assets/{digest[:16]}{ext}"
    write_immutable(Path(tdir) / rel, data)
    rec = {"id": f"a-{digest[:12]}", "path": rel, "sha256": digest, "kind": kind, "source": source}
    if kind in ("image", "mask", "texture"):
        from PIL import Image

        with Image.open(Path(tdir) / rel) as im:
            rec.update(width=im.width, height=im.height, format=im.format, mode=im.mode)
    if kind == "font":
        rec["font_names"] = font_names(Path(tdir) / rel)
    rec.update(extra)
    return rec


# ---------------------------------------------------------------- evidence
def evidence_path(tdir) -> Path:
    return Path(tdir) / "evidence" / "evidence.json"


def load_evidence(tdir) -> dict:
    p = evidence_path(tdir)
    if p.exists():
        return read_json(p)
    return {"schema_version": SCHEMA_VERSION, "template_id": Path(tdir).name, "records": []}


def add_evidence(tdir, records: list[dict]) -> list[str]:
    """Append evidence records (same evidence_id replaces: re-measurement supersedes)."""
    store = load_evidence(tdir)
    by_id = {r["evidence_id"]: r for r in store["records"]}
    for r in records:
        r.setdefault("created", now())
        r.setdefault("source_state", "static")
        by_id[r["evidence_id"]] = r
    store["records"] = list(by_id.values())
    write_json(evidence_path(tdir), store)
    return [r["evidence_id"] for r in records]


# ---------------------------------------------------------------- addressing
def node_map(scene) -> dict:
    return {n["id"]: n for n in scene["nodes"]}


def find_node(scene, ref: str, required: bool = True):
    """Resolve an id or alias to a node. Ambiguous alias = error (never guess)."""
    for n in scene["nodes"]:
        if n["id"] == ref:
            return n
    hits = [n for n in scene["nodes"] if n.get("alias") == ref or n.get("role") == ref]
    by_alias = [n for n in hits if n.get("alias") == ref]
    hits = by_alias or hits
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise DnaError(f"{ref!r} matches {len(hits)} nodes; name one explicitly",
                       "ambiguous_target", {"candidates": [n["id"] for n in hits]})
    if required:
        raise DnaError(f"no node with id/alias {ref!r}", "unknown_target")
    return None


def _step(obj, seg: str):
    if isinstance(obj, dict):
        if seg not in obj:
            raise DnaError(f"no property {seg!r}", "unknown_path")
        return obj[seg]
    if isinstance(obj, list):
        return obj[_list_index(obj, seg)]
    raise DnaError(f"cannot descend into {type(obj).__name__} with {seg!r}", "unknown_path")


def _list_index(lst: list, seg: str) -> int:
    if seg.isdigit() and int(seg) < len(lst):
        return int(seg)
    hits = [i for i, x in enumerate(lst) if isinstance(x, dict)
            and seg in (x.get("id"), x.get("type"), x.get("op"))]
    if len(hits) != 1:
        raise DnaError(f"list item {seg!r} matched {len(hits)} entries", "unknown_path")
    return hits[0]


def resolve(scene, path: str):
    """Address a property. Returns (container, key, normalized_path, node_or_None).

    Grammar: tokens.<token key>[.<field>]  |  <node id|alias>.<prop>[.<sub>...]  |  <top-level>.<prop>...
    Token keys may contain dots; the longest matching key wins. A bare token path addresses `.value`.
    """
    segs = path.split(".")
    if segs[0] == "tokens":
        rest = ".".join(segs[1:])
        for key in sorted(scene["tokens"], key=len, reverse=True):
            if rest == key or rest.startswith(key + "."):
                tail = rest[len(key) + 1:].split(".") if rest != key else ["value"]
                c, k = _walk(scene["tokens"][key], tail)
                return c, k, f"tokens.{key}." + ".".join(tail), None
        raise DnaError(f"unknown token in {path!r}", "unknown_path", {"tokens": sorted(scene["tokens"])})
    node = find_node(scene, segs[0], required=False)
    if node is not None:
        c, k = _walk(node, segs[1:])
        return c, k, f"nodes.{node['id']}." + ".".join(segs[1:]), node
    if segs[0] in scene and len(segs) > 1:
        c, k = _walk(scene[segs[0]], segs[1:])
        return c, k, path, None
    raise DnaError(f"cannot resolve {path!r}", "unknown_path")


def _walk(obj, segs):
    if not segs or segs == [""]:
        raise DnaError("path must address a property, not a whole object", "unknown_path")
    for s in segs[:-1]:
        obj = _step(obj, s)
    last = segs[-1]
    if isinstance(obj, list):
        return obj, _list_index(obj, last)
    return obj, last


def get_path(scene, path):
    c, k, _, _ = resolve(scene, path)
    if isinstance(c, dict) and k not in c:
        raise DnaError(f"{path!r} is not set", "unknown_path")
    return c[k]


def token_value(scene, key):
    tok = scene["tokens"].get(key)
    if tok is None:
        raise DnaError(f"token {key!r} is not defined", "missing_token")
    return tok["value"]


def deep(o):
    return copy.deepcopy(o)


def diff_paths(a, b, prefix="") -> list[str]:
    """Leaf paths that differ between two JSON values (lists of id'd dicts compared by id; 22 == 22.0)."""
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
        return [] if a == b else [prefix]
    if type(a) is not type(b):
        return [prefix or "."]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            p = f"{prefix}.{k}" if prefix else k
            if k not in a or k not in b:
                out.append(p)
            else:
                out += diff_paths(a[k], b[k], p)
        return out
    if isinstance(a, list):
        if all(isinstance(x, dict) and "id" in x for x in a + b):
            return diff_paths({x["id"]: x for x in a}, {x["id"]: x for x in b}, prefix) + \
                ([f"{prefix}.<order>"] if [x["id"] for x in a] != [x["id"] for x in b]
                 and set(x["id"] for x in a) == set(x["id"] for x in b) else [])
        return [] if a == b else [prefix]
    return [] if a == b else [prefix]
