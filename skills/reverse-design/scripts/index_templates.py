"""Template index: retrieval from disk, never from conversation memory.

  python index_templates.py rebuild
  python index_templates.py list [--all]
  python index_templates.py find <query words> [--aspect 4:5] [--readiness editable_close]
  python index_templates.py load "<name | alias | id>"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DnaError, read_json, store_root, write_json  # noqa: E402

FIELDS = ("character", "theme", "goal", "mechanism", "channels", "usage", "medium")


def _val(p, k):
    v = p.get(k)
    return v.get("value") if isinstance(v, dict) else v


def rebuild() -> list[dict]:
    rows = []
    for pp in sorted((store_root() / "templates").glob("*/passport.json")):
        p = read_json(pp)
        tdir = pp.parent
        variants = []
        for vj in sorted(tdir.glob("variants/*/variant.json")):
            v = read_json(vj)
            variants.append({"id": v["id"], "name": v["name"], "head": v["head"], "task": v["task"]})
        rows.append({"id": p["id"], "name": p["name"], "aliases": p["aliases"], "readiness": p["readiness"],
                     "aspect_ratio": p.get("aspect_ratio"), "fixture": p.get("fixture", False), "revision": p["revision"],
                     "baseline_match": p["baseline_match"], "dir": str(tdir), "variants": variants,
                     **{k: _val(p, k) for k in FIELDS}})
    write_json(store_root() / "index.json", {"templates": rows})
    return rows


def resolve_template(ref: str) -> dict:
    """Exact (case-insensitive) match on id, name or alias. Ambiguity is an error, never a guess."""
    r = ref.strip().lower()
    rows = rebuild()
    by_id = [t for t in rows if r == t["id"]]  # ids are unique: an exact id always wins
    hits = by_id or [t for t in rows if r == t["name"].lower() or r in [a.lower() for a in t["aliases"]]]
    if len(hits) != 1:
        raise DnaError(f"{len(hits)} templates match {ref!r}" + ("; use one of the ids" if hits else ""),
                       "unknown_template" if not hits else "ambiguous_target",
                       {"candidates": [{"id": h["id"], "name": h["name"]} for h in hits]})
    return hits[0]


def find(words, aspect=None, readiness=None):
    q = [w.lower() for w in words]
    out = []
    for t in rebuild():
        if aspect and t["aspect_ratio"] != aspect or readiness and t["readiness"] != readiness:
            continue
        hay = json.dumps({k: t.get(k) for k in ("name", "aliases") + FIELDS}, ensure_ascii=False).lower()
        score = sum(w in hay for w in q)
        if score or not q:
            out.append((score, t))
    return [t for _, t in sorted(out, key=lambda x: -x[0])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rebuild")
    s = sub.add_parser("list"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("find"); s.add_argument("words", nargs="*"); s.add_argument("--aspect"); s.add_argument("--readiness")
    s = sub.add_parser("load"); s.add_argument("ref")
    a = ap.parse_args()
    try:
        if a.cmd == "rebuild":
            print(f"{len(rebuild())} templates indexed -> {store_root() / 'index.json'}")
        elif a.cmd == "list":
            for t in rebuild():
                if a.all or not t["fixture"]:
                    print(f"{t['name']:<40} {t['id']:<34} {t['readiness']:<17} {t['aspect_ratio'] or '':<7} variants:{len(t['variants'])}"
                          + ("  [fixture]" if t["fixture"] else ""))
        elif a.cmd == "find":
            for t in find(a.words, a.aspect, a.readiness):
                print(f"{t['name']:<40} {t['id']:<34} {t['readiness']:<17} {t['aspect_ratio'] or ''}")
        else:
            print(json.dumps(resolve_template(a.ref), indent=2, ensure_ascii=False))
    except DnaError as e:
        print(json.dumps(e.as_dict(), indent=2))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
