"""The font files the acceptance suite uses, by role.

Two sets with the same roles:
  windows   the Windows system fonts the 1.0.0 / 2.0.0 runs were verified with (Arial, Georgia, ...).
  portable  redistributable fonts vendored in tests/fonts/ (SIL OFL 1.1 / Bitstream Vera licence; see its README).
            The suite runs unchanged on Linux and macOS, and every machine sees byte-identical font files.
Default: `windows` when its fonts are installed, otherwise `portable`. DESIGN_DNA_FONTSET=portable|windows forces one.
"""
from __future__ import annotations

import os
from pathlib import Path

PORTABLE_DIR = Path(__file__).resolve().parents[1] / "fonts"
WINDOWS_DIR = Path("C:/Windows/Fonts")

# sans / serif: the true faces of the layered reference (T01 must rank them first among their candidates).
# arabic: covers Latin and Arabic (adaptation tests). caption: draws T02's captions (at caption_instance of the
# variable font) and is never a candidate.
# variable: has a `wdth` axis (T27). lookalikes: the other candidates next to T03's renamed duplicate.
SETS = {
    "windows": {"dir": WINDOWS_DIR, "sans": "arialbd.ttf", "serif": "georgiab.ttf", "arabic": "arialbd.ttf",
                "sans_candidates": ["arialbd.ttf", "verdanab.ttf", "tahomabd.ttf", "segoeuib.ttf", "calibrib.ttf", "trebucbd.ttf"],
                "serif_candidates": ["georgiab.ttf", "timesbd.ttf", "cambriab.ttf", "constanb.ttf"],
                "grid_extra_candidates": ["corbelb.ttf", "GOTHICB.TTF"], "lookalikes": ["verdanab.ttf", "tahomabd.ttf"],
                "caption": "bahnschrift.ttf", "caption_instance": "Bold", "caption_fallback": "segoeuib.ttf", "variable": "bahnschrift.ttf"},
    "portable": {"dir": PORTABLE_DIR, "sans": "LiberationSans-Bold.ttf", "serif": "DejaVuSerif-Bold.ttf", "arabic": "Amiri-Bold.ttf",
                 "sans_candidates": ["LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf", "Carlito-Bold.ttf"],
                 "serif_candidates": ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "Caladea-Bold.ttf"],
                 "grid_extra_candidates": [], "lookalikes": ["DejaVuSans-Bold.ttf", "Carlito-Bold.ttf"],
                 "caption": "OpenSans-wdth-wght.ttf", "caption_instance": "Bold", "caption_fallback": None,
                 "variable": "OpenSans-wdth-wght.ttf"},
}


def name() -> str:
    forced = os.environ.get("DESIGN_DNA_FONTSET")
    if forced:
        if forced not in SETS:
            raise SystemExit(f"DESIGN_DNA_FONTSET={forced!r}: expected one of {sorted(SETS)}")
        missing = [f for f in (SETS[forced]["sans"], SETS[forced]["serif"]) if not (SETS[forced]["dir"] / f).exists()]
        if missing:
            raise SystemExit(f"DESIGN_DNA_FONTSET={forced}: {missing} not found in {SETS[forced]['dir']}")
        return forced
    win = SETS["windows"]
    return "windows" if all((WINDOWS_DIR / win[k]).exists() for k in ("sans", "serif")) else "portable"


def font_dir() -> Path:
    return SETS[name()]["dir"]


def path(role: str) -> str | None:
    """Absolute forward-slash path of the role's file, or None when the set has none / it is not installed."""
    f = SETS[name()][role]
    p = font_dir() / f if f else None
    return p.as_posix() if p and p.exists() else None


def paths(role: str) -> list[str]:
    """The role's files that exist, in their listed order."""
    return [(font_dir() / f).as_posix() for f in SETS[name()][role] if (font_dir() / f).exists()]


def source() -> str:
    """Asset provenance for these files: installed system fonts, or font files supplied with the test kit."""
    return "system_font" if name() == "windows" else "supplied"


def full_name(p) -> str:
    """The font's full name (name ID 4), as font_candidates.py reports it."""
    from fontTools.ttLib import TTFont

    return TTFont(p)["name"].getDebugName(4)


def summary() -> dict:
    """Which set ran and the faces behind each role (recorded in the acceptance report)."""
    s = SETS[name()]
    one = {k: full_name(path(k)) if path(k) else None for k in ("sans", "serif", "arabic", "caption", "variable")}
    if one["caption"]:
        one["caption"] += f" ({s['caption_instance']} instance)"
    elif path("caption_fallback"):
        one["caption"] = full_name(path("caption_fallback"))
    return {"fontset": name(), "dir": font_dir().as_posix(), **one,
            "candidates": {k: [full_name(p) for p in paths(k)] for k in ("sans_candidates", "serif_candidates", "grid_extra_candidates")},
            "files": sorted({f for k, v in s.items() if k not in ("dir", "caption_instance")
                             for f in (v if isinstance(v, list) else [v]) if f})}
