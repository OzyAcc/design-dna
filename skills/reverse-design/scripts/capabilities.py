"""Capability report (Step A): what this machine can actually inspect and render right now.

  python capabilities.py            # JSON: implemented / partial / unsupported, with versions
Missing tools produce degraded or unsupported statuses; nothing here fabricates a capability.
"""
from __future__ import annotations

import json
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def pkg(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def main() -> int:
    from render_static import launch

    libs = {k: pkg(k) for k in ("pillow", "numpy", "scikit-image", "fonttools", "jsonschema", "playwright", "opencv-python")}
    browser = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b, ch = launch(p)
            browser = f"{ch} {b.version}"
            b.close()
    except Exception as e:  # report, never hide
        browser = f"unavailable: {e.__class__.__name__}: {str(e)[:120]}"
    from PIL import features

    ok = lambda *xs: all(xs)
    cap = {
        "libraries": libs, "renderer": browser, "pillow_raqm": features.check("raqm"), "tesseract": shutil.which("tesseract"),
        "capabilities": {
            "metadata_intake (raster)": "implemented" if libs["pillow"] else "unsupported",
            "pixel measurement / role color sampling": "implemented" if ok(libs["numpy"], libs["scikit-image"]) else "unsupported",
            "OCR": "implemented" if shutil.which("tesseract") else "unsupported: no OCR engine; transcription is manual_observation by Claude vision, labelled as such",
            "segmentation": "unsupported: element boundaries are assisted (Claude proposes, measure.py measures)",
            "font candidate comparison (supplied files)": "implemented" if ok(libs["fonttools"], "unavailable" not in str(browser)) else "unsupported",
            "font identification (unknown fonts)": "unsupported: ranks supplied candidates only; identity stays unknown without source evidence",
            "scene validation (JSON Schema)": "implemented" if libs["jsonschema"] else "unsupported",
            "deterministic static rendering (SVG via Chromium)": "implemented" if "unavailable" not in str(browser) else "unsupported",
            "complex-script shaping (Arabic, bidi)": "implemented via Chromium/HarfBuzz" if "unavailable" not in str(browser) else "unsupported",
            "comparison (exact, MAE/RMSE, SSIM, DeltaE2000, regions)": "implemented" if libs["scikit-image"] else "unsupported",
            "typed patches / variants / undo / index": "implemented",
            "adapters: pdf, psd/figma, website/ui, packaging, motion, 3d": "unsupported (static raster adapter only)",
            "generated/inpainted assets": "unsupported in-engine; supply files and they are tracked as synthesized assets",
        }}
    print(json.dumps(cap, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
