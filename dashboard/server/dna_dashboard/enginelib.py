"""In-process use of engine helpers that take an EXPLICIT template directory (never the DESIGN_DNA_HOME default).

Only pure functions are used here: content-hashed asset import, evidence records, JSON IO, font metadata, model hashes,
schema validation of a scene against its own directory. Anything that renders or reads the store root runs in an
isolated subprocess through engine.py instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import config

_loaded = False


def _load():
    global _loaded
    if not _loaded:
        p = str(config.get().engine_dir)
        if p not in sys.path:
            sys.path.insert(0, p)
        _loaded = True


def common():
    _load()
    import common as c

    return c


def validate():
    _load()
    import validate_model as v

    return v


def import_asset(tdir: Path, src: Path, kind: str, source: str, **extra) -> dict:
    return common().import_asset(Path(tdir), Path(src), kind, source, **extra)


def add_evidence(tdir: Path, records: list[dict]) -> list[str]:
    return common().add_evidence(Path(tdir), records)


def load_evidence(tdir: Path) -> dict:
    return common().load_evidence(Path(tdir))


def read_json(p):
    return common().read_json(p)


def write_json(p, data):
    return common().write_json(p, data)


def model_hash(scene) -> str:
    return common().model_hash(scene)


def font_names(path) -> dict:
    return common().font_names(path)


def font_cmap(path) -> set[int]:
    return common().font_cmap(path)


def check_scene(scene, tdir) -> dict:
    return validate().check_scene(scene, Path(tdir))


def editability(scene) -> dict:
    return validate().editability_report(scene)


def passport_report(passport) -> dict:
    return validate().passport_report(passport)


def pixel_diff(a, b) -> dict:
    """Decoded RGBA comparison with the engine's own decoder (alpha is data; no tolerance)."""
    _load()
    from compare_render import decode_rgba, pixel_metrics

    x, y = decode_rgba(a), decode_rgba(b)
    if x.shape != y.shape:
        return {"unequal_pixels": None, "status": "fail", "reason": f"dimensions differ {x.shape[:2]} vs {y.shape[:2]}"}
    pm = pixel_metrics(x, y)
    import numpy as np

    ys, xs = np.nonzero(np.any(x != y, axis=2))
    box = [int(xs.min()), int(ys.min()), int(xs.max()) - int(xs.min()) + 1, int(ys.max()) - int(ys.min()) + 1] if len(xs) else None
    return {"unequal_pixels": pm["unequal_pixels"], "max_channel_error": pm["max_channel_error"], "box": box,
            "status": "pass" if pm["unequal_pixels"] == 0 else "fail"}


def constants() -> dict:
    c = common()
    return {"categories": list(c.SCAN_CATEGORIES), "facets": {k: list(v) for k, v in c.REQUIRED_FACETS.items()},
            "interpretive": list(c.INTERPRETIVE), "statuses": list(c.STATUSES)}


def font_weight(path) -> int:
    from fontTools.ttLib import TTFont

    with TTFont(path, fontNumber=0, lazy=True) as f:
        return int(f["OS/2"].usWeightClass) if "OS/2" in f else 400


def font_library() -> list[dict]:
    """Font files the workspace may use as candidates: uploaded fonts, configured folders, and (by default) the
    repository's vendored OFL/Bitstream Vera set. Each entry carries its real names, hash and weight."""
    seen, out = set(), []
    for d in config.get().font_dirs:
        if not Path(d).exists():
            continue
        for f in sorted(Path(d).rglob("*")):
            if f.suffix.lower() not in (".ttf", ".otf") or not f.is_file():
                continue
            try:
                sha = common().sha256_file(f)
                if sha in seen:
                    continue
                names = font_names(f)
                seen.add(sha)
                out.append({"path": str(f), "sha256": sha, "names": names, "weight": font_weight(f),
                            "source": "uploaded" if Path(d) == config.get().fonts else "folder", "folder": str(d)})
            except Exception:
                continue
    return out


def covers(font_path, text: str) -> bool:
    cmap = font_cmap(font_path)
    return all(ord(ch) in cmap for ch in text if not ch.isspace())
