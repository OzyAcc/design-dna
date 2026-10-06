"""Renderer environment: launch, environment snapshot, baseline pin, drift detection.

Intake may pick any available renderer (Chrome -> Edge -> bundled Chromium; DESIGN_DNA_BROWSER pins a channel).
Once a baseline is approved, `make_pin` records the exact environment in `scene.render_profile.pin`. Every later
render compares the live environment with the pin: a HARD difference (browser channel/version, viewport, device
scale, flags, colour/alpha policy, font files) stops the render with `renderer_drift` until an explicit baseline
migration is confirmed; SOFT differences (Python/package/OS versions) are reported, never hidden.
"""
from __future__ import annotations

import json
import os
import platform
from contextlib import contextmanager
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version

from common import DnaError, now

CHANNELS = ("chrome", "msedge", "chromium")  # chromium = Playwright's bundled build (`playwright install chromium`)
BROWSER_ARGS = ["--force-color-profile=srgb", "--disable-lcd-text", "--disable-gpu", "--font-render-hinting=none"]
COLOR_POLICY = "sRGB forced; image assets untagged -> treated as sRGB"
# Environment fields. Viewport, alpha and the font list are recorded too, but they follow the scene (a reflow changes
# the viewport, an adaptation may add a font asset), so they are not drift; a pinned font still in use must keep its hash.
HARD = ("channel", "browser_version", "device_scale_factor", "browser_args", "color_policy", "font_synthesis")
SOFT = ("playwright", "python", "os", "packages")
RECORDED = ("viewport", "alpha", "fonts", "animations", "randomness", "renderer")
PACKAGES = ("pillow", "numpy", "scikit-image", "scipy", "fonttools", "jsonschema", "playwright")


def requested_channel(pin=None):
    """DESIGN_DNA_BROWSER wins (so a deliberate switch is visible as drift); else the pinned channel; else auto."""
    return os.environ.get("DESIGN_DNA_BROWSER") or (pin or {}).get("channel")


def launch(p, channel=None):
    """Launch `channel` (or the first available of CHANNELS). Returns (browser, channel)."""
    from playwright.sync_api import Error

    channel = channel or os.environ.get("DESIGN_DNA_BROWSER")
    tried = []
    for ch in ([channel] if channel else CHANNELS):
        try:
            return p.chromium.launch(channel=None if ch == "chromium" else ch, args=BROWSER_ARGS), ch
        except Error as e:
            tried.append(f"{ch}: {str(e).strip().splitlines()[0][:160]}")
    raise DnaError("no Chromium-based browser could be launched" + (f" (requested {channel})" if channel else ""),
                   "renderer_unavailable", {"tried": tried,
                                            "fix": "install Google Chrome or Microsoft Edge, or run `python -m playwright install chromium`"})


@contextmanager
def browser(channel=None):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b, ch = launch(p, channel)
        try:
            yield b, ch
        finally:
            b.close()


def capture(page, **kw):
    """page.screenshot with a bounded retry: headless Chromium occasionally returns 'Unable to capture screenshot'."""
    from playwright.sync_api import Error

    for attempt in range(3):
        try:
            return page.screenshot(**kw)
        except Error:
            if attempt == 2:
                raise
            page.wait_for_timeout(250)


def _pkg(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def environment(channel, browser_version, W, H, alpha, fonts) -> dict:
    """Snapshot of everything that can change rasterisation, plus the software around it."""
    return {"renderer": "playwright-chromium", "channel": channel, "browser_version": browser_version,
            "viewport": [W, H], "device_scale_factor": 1, "browser_args": list(BROWSER_ARGS), "color_policy": COLOR_POLICY,
            "alpha": alpha, "font_synthesis": "none unless declared", "animations": "disabled",
            "randomness": "feTurbulence seeds fixed in scene", "fonts": sorted(fonts, key=lambda f: f["sha256"]),
            "playwright": _pkg("playwright"), "python": platform.python_version(), "os": platform.platform(),
            "packages": {k: _pkg(k) for k in PACKAGES}}


def make_pin(profile, reason="baseline approved") -> dict:
    pin = {k: profile[k] for k in HARD + SOFT + RECORDED if k in profile}
    pin.update(pinned_at=now(), reason=reason)
    return pin


def compare_pin(pin, env) -> dict:
    """Return {'hard': [...], 'soft': [...]} differences between a pin and the live environment."""
    def diffs(keys):
        return [{"field": k, "pinned": pin.get(k), "current": env.get(k)} for k in keys if pin.get(k) != env.get(k)]
    hard = diffs(HARD)
    now_fonts = {f["asset"]: f["sha256"] for f in env.get("fonts", [])}
    for f in pin.get("fonts", []):
        if f["asset"] in now_fonts and now_fonts[f["asset"]] != f["sha256"]:
            hard.append({"field": f"fonts.{f['asset']}", "pinned": f["sha256"], "current": now_fonts[f["asset"]]})
    return {"hard": hard, "soft": diffs(SOFT)}


def pin_of(scene, tdir=None):
    """The template-level pin (passport.render_pin) governs every variant; a scene-level pin is a fallback."""
    if tdir is not None:
        pp = Path(tdir) / "passport.json"
        if pp.exists():
            pin = json.loads(pp.read_text(encoding="utf-8")).get("render_pin")
            if pin:
                return pin
    return ((scene.get("render_profile") or {}).get("pin")) or None


def drift_error(pin, diff, where="render") -> DnaError:
    return DnaError(f"renderer environment differs from the pinned baseline environment ({where}); "
                    "reproducibility cannot be claimed until the baseline is explicitly migrated",
                    "renderer_drift", {"hard": diff["hard"], "soft": diff["soft"], "pinned_at": pin.get("pinned_at"),
                                       "fix": "dna.py 'migrate-baseline \"<template>\"' to preview the change, then add confirm"})
