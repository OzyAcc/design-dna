"""Compile a scene model to an SVG master and render it to PNG in a pinned browser.

Usage: python render_static.py <template-id> --out <dir> [--scene file] [--isolate] [--formats png,svg]

Renderer: Playwright driving Google Chrome, else Microsoft Edge, else Playwright's bundled Chromium
(HarfBuzz shaping, bidi; DESIGN_DNA_BROWSER=chrome|msedge|chromium pins one) at DPR 1,
sRGB forced, LCD text off, GPU off, animations disabled, fonts loaded from pinned files.
Text fitting: `strict` reports overflow; `fit` shrinks only down to fit.min_size, then reports.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import platform
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DnaError, read_json, safe_path, sha256_file, template_dir, token_value, write_json  # noqa: E402
from validate_model import check_scene, resolved_font  # noqa: E402

CHANNELS = ("chrome", "msedge", "chromium")  # chromium = Playwright's bundled build (`playwright install chromium`)
CHANNEL = os.environ.get("DESIGN_DNA_BROWSER")  # pins one channel; unset = first of CHANNELS that launches
BROWSER_ARGS = ["--force-color-profile=srgb", "--disable-lcd-text", "--disable-gpu", "--font-render-hinting=none"]
FIT_STEP = 0.25


def fmt(v) -> str:
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def color(c: str):
    """'#RRGGBB[AA]' -> ('#rrggbb', alpha)."""
    return c[:7].lower(), (int(c[7:9], 16) / 255 if len(c) == 9 else 1.0)


class Compiler:
    def __init__(self, scene, tdir, href_mode="file", fit_sizes=None):
        self.scene, self.tdir, self.href_mode = scene, Path(tdir), href_mode
        self.fit_sizes = fit_sizes or {}
        self.defs: list[str] = []
        self.fonts: dict[str, str] = {}
        self.W, self.H = scene["canvas"]["width"], scene["canvas"]["height"]

    def href(self, asset_id: str) -> str:
        a = self.scene["assets"][asset_id]
        if self.href_mode == "file":
            return safe_path(self.tdir, a["path"]).as_uri()
        return a["path"]  # relative: export copies assets/ next to the svg

    def paint(self, p, gid: str):
        if p is None:
            return "none", 1.0
        if isinstance(p, dict) and "token" in p:
            return self.paint(token_value(self.scene, p["token"]), gid)
        if isinstance(p, str):
            return color(p)
        units = "objectBoundingBox" if p.get("units") == "node" else "userSpaceOnUse"
        stops = "".join(f'<stop offset="{fmt(s["offset"])}" stop-color="{color(s["color"])[0]}" '
                        f'stop-opacity="{fmt(color(s["color"])[1])}"/>' for s in p["stops"])
        if p["type"] == "linear":
            self.defs.append(f'<linearGradient id="{gid}" gradientUnits="{units}" x1="{fmt(p.get("x1", 0))}" '
                             f'y1="{fmt(p.get("y1", 0))}" x2="{fmt(p.get("x2", 1))}" y2="{fmt(p.get("y2", 0))}">{stops}</linearGradient>')
        else:
            self.defs.append(f'<radialGradient id="{gid}" gradientUnits="{units}" cx="{fmt(p.get("cx", .5))}" '
                             f'cy="{fmt(p.get("cy", .5))}" r="{fmt(p.get("r", .5))}">{stops}</radialGradient>')
        return f"url(#{gid})", 1.0

    def fill_attrs(self, p, gid, prefix="fill"):
        v, a = self.paint(p, gid)
        return f'{prefix}="{v}"' + (f' {prefix}-opacity="{fmt(a)}"' if a < 1 else "")

    # ------------------------------------------------------------ node kinds
    def text(self, n):
        f = resolved_font(self.scene, n)
        g, d = n["geometry"], n.get("direction", "ltr")
        size = self.fit_sizes.get(n["id"], f["size"])
        lh = n["line_height"] * size / f["size"]
        ax = {"left": g["x"], "center": g["x"] + g["w"] / 2, "right": g["x"] + g["w"]}[n["align"]]
        anchor = {"center": "middle", "left": "start" if d == "ltr" else "end",
                  "right": "end" if d == "ltr" else "start"}[n["align"]]
        if f.get("asset"):
            fam = self.fonts.setdefault(f["asset"], f"dna-{f['asset']}")
        else:
            fam = f.get("family", "sans-serif")
        synth = f.get("synthetic") or {}
        allowed = " ".join(css for key, css in (("bold", "weight"), ("italic", "style")) if synth.get(key))
        style = ["white-space:pre", "font-kerning:normal", f"font-synthesis:{allowed or 'none'}"]
        if f.get("features"):
            style.append("font-feature-settings:" + ",".join(f'"{k}" {v}' for k, v in f["features"].items()))
        if f.get("variation"):
            style.append("font-variation-settings:" + ",".join(f'"{k}" {fmt(v)}' for k, v in f["variation"].items()))
        hs = f.get("horizontal_scale", 1)
        tf = f' transform="translate({fmt(ax)} 0) scale({fmt(hs)} 1) translate({fmt(-ax)} 0)"' if hs != 1 else ""
        spans = "".join(f'<tspan x="{fmt(ax)}" y="{fmt(n["first_baseline"] + i * lh)}">{esc(line)}</tspan>'
                        for i, line in enumerate(n["content"].split("\n")))
        lang = f' xml:lang="{esc(n["lang"])}"' if n.get("lang") else ""
        return (f'<text font-family="{esc(fam)}" font-size="{fmt(size)}" font-weight="{fmt(f.get("weight", 400))}" '
                f'font-style="{f.get("style", "normal")}" {self.fill_attrs(n.get("fill", "#000000"), n["id"] + "-fill")} '
                f'letter-spacing="{fmt(n.get("tracking", 0))}" direction="{d}" text-anchor="{anchor}"{lang}{tf} '
                f'style="{";".join(style)}">{spans}</text>')

    def image_rect(self, asset, g, pl):
        aw, ah = asset["width"], asset["height"]
        if pl.get("crop"):
            cx, cy, cw, ch = pl["crop"]
            sx, sy = g["w"] / cw, g["h"] / ch
            return g["x"] - cx * sx, g["y"] - cy * sy, aw * sx, ah * sy
        if pl["fit"] == "fill":
            return g["x"], g["y"], g["w"], g["h"]
        k = {"cover": max(g["w"] / aw, g["h"] / ah), "contain": min(g["w"] / aw, g["h"] / ah), "none": 1}[pl["fit"]]
        k *= pl.get("scale", 1)
        dw, dh = aw * k, ah * k
        fx, fy = pl.get("focal", [0.5, 0.5])
        return g["x"] + (g["w"] - dw) * fx, g["y"] + (g["h"] - dh) * fy, dw, dh

    def clip(self, n, g):
        """Clip/mask attribute string for an image frame (images never spill outside their frame)."""
        m, cid = n.get("mask") or {"type": "rect", "radius": 0}, f"clip-{n['id']}"
        if m["type"] == "asset":
            a = self.scene["assets"][m["asset"]]
            self.defs.append(f'<mask id="{cid}" maskUnits="userSpaceOnUse" style="mask-type:{m.get("mode", "alpha")}">'
                             f'<image href="{esc(self.href(a["id"]))}" x="{fmt(g["x"])}" y="{fmt(g["y"])}" '
                             f'width="{fmt(g["w"])}" height="{fmt(g["h"])}" preserveAspectRatio="none"/></mask>')
            return f'mask="url(#{cid})"'
        if m["type"] == "rect":
            shape = (f'<rect x="{fmt(g["x"])}" y="{fmt(g["y"])}" width="{fmt(g["w"])}" height="{fmt(g["h"])}" '
                     f'rx="{fmt(m.get("radius", 0))}"/>')
        elif m["type"] == "ellipse":
            shape = (f'<ellipse cx="{fmt(g["x"] + g["w"] / 2)}" cy="{fmt(g["y"] + g["h"] / 2)}" '
                     f'rx="{fmt(g["w"] / 2)}" ry="{fmt(g["h"] / 2)}"/>')
        else:
            bw, bh = m["box"]
            shape = (f'<path d="{esc(m["d"])}" transform="translate({fmt(g["x"])} {fmt(g["y"])}) '
                     f'scale({fmt(g["w"] / bw)} {fmt(g["h"] / bh)})"/>')
        if m.get("feather"):
            self.defs.append(f'<filter id="{cid}-f"><feGaussianBlur stdDeviation="{fmt(m["feather"])}"/></filter>'
                             f'<mask id="{cid}" maskUnits="userSpaceOnUse"><g fill="#fff" filter="url(#{cid}-f)">{shape}</g></mask>')
            return f'mask="url(#{cid})"'
        self.defs.append(f'<clipPath id="{cid}">{shape}</clipPath>')
        return f'clip-path="url(#{cid})"'

    def treatment(self, n) -> str:
        ops = n.get("treatment") or []
        if not ops:
            return ""
        fid, cur, prims = f"treat-{n['id']}", "SourceGraphic", []
        for i, t in enumerate(ops):
            r, a = f"t{i}", t.get("amount", 1)
            if t["op"] in ("grayscale", "saturate"):
                prims.append(f'<feColorMatrix in="{cur}" type="saturate" values="{fmt(1 - a if t["op"] == "grayscale" else a)}" result="{r}"/>')
            elif t["op"] == "hue_rotate":
                prims.append(f'<feColorMatrix in="{cur}" type="hueRotate" values="{fmt(a)}" result="{r}"/>')
            elif t["op"] in ("contrast", "brightness"):
                icpt = 0.5 - 0.5 * a if t["op"] == "contrast" else 0
                funcs = "".join(f'<feFunc{c} type="linear" slope="{fmt(a)}" intercept="{fmt(icpt)}"/>' for c in "RGB")
                prims.append(f'<feComponentTransfer in="{cur}" result="{r}">{funcs}</feComponentTransfer>')
            elif t["op"] == "tint":
                c, ca = color(t["color"])
                prims.append(f'<feFlood flood-color="{c}" flood-opacity="{fmt(ca)}" result="{r}f"/>'
                             f'<feBlend in="{cur}" in2="{r}f" mode="multiply" result="{r}m"/>'
                             f'<feComposite in="{r}m" in2="{cur}" operator="arithmetic" k2="{fmt(a)}" k3="{fmt(1 - a)}" result="{r}x"/>'
                             f'<feComposite in="{r}x" in2="SourceGraphic" operator="in" result="{r}"/>')
            elif t["op"] == "blur":
                prims.append(f'<feGaussianBlur in="{cur}" stdDeviation="{fmt(a)}" result="{r}"/>')
            cur = r
        self.defs.append(f'<filter id="{fid}" color-interpolation-filters="sRGB">{"".join(prims)}</filter>')
        return f' filter="url(#{fid})"'

    def image(self, n):
        a, g = self.scene["assets"][n["asset"]], n["geometry"]
        x, y, w, h = self.image_rect(a, g, n["placement"])
        img = (f'<image href="{esc(self.href(a["id"]))}" x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" '
               f'height="{fmt(h)}" preserveAspectRatio="none"{self.treatment(n)}/>')
        return f'<g {self.clip(n, g)}>{img}</g>'

    def shape(self, n):
        g = n["geometry"]
        attrs = self.fill_attrs(n.get("fill"), n["id"] + "-fill")
        if n.get("stroke"):
            attrs += " " + self.fill_attrs(n["stroke"]["color"], n["id"] + "-stroke", "stroke") + f' stroke-width="{fmt(n["stroke"]["width"])}"'
        if n["type"] == "path":
            bw, bh = n["path_box"]
            return (f'<path d="{esc(n["path"])}" {attrs} transform="translate({fmt(g["x"])} {fmt(g["y"])}) '
                    f'scale({fmt(g["w"] / bw)} {fmt(g["h"] / bh)})"/>')
        if n.get("shape") == "ellipse":
            return (f'<ellipse cx="{fmt(g["x"] + g["w"] / 2)}" cy="{fmt(g["y"] + g["h"] / 2)}" rx="{fmt(g["w"] / 2)}" '
                    f'ry="{fmt(g["h"] / 2)}" {attrs}/>')
        return (f'<rect x="{fmt(g["x"])}" y="{fmt(g["y"])}" width="{fmt(g["w"])}" height="{fmt(g["h"])}" '
                f'rx="{fmt(n.get("radius", 0))}" {attrs}/>')

    def background(self, n):
        if n.get("asset"):
            n2 = dict(n, geometry={"x": 0, "y": 0, "w": self.W, "h": self.H},
                      placement=n.get("placement") or {"fit": "cover"})
            return self.image(n2)
        return f'<rect x="0" y="0" width="{fmt(self.W)}" height="{fmt(self.H)}" {self.fill_attrs(n.get("fill"), n["id"] + "-fill")}/>'

    def effect_node(self, n):
        e, g, fid = n["effect"], n["geometry"], f"fx-{n['id']}"
        rect = f'x="{fmt(g["x"])}" y="{fmt(g["y"])}" width="{fmt(g["w"])}" height="{fmt(g["h"])}"'
        if e["kind"] == "grain":
            self.defs.append(f'<filter id="{fid}" x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB">'
                             f'<feTurbulence type="fractalNoise" baseFrequency="{fmt(e.get("frequency", 0.9))}" numOctaves="2" '
                             f'seed="{int(e.get("seed", 1))}" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter>')
            return f'<rect {rect} filter="url(#{fid})"/>'
        grad = {"type": "radial", "units": "node", "stops": [
            {"offset": e.get("inner", 0.6), "color": e.get("color", "#000000")[:7] + "00"},
            {"offset": 1, "color": e.get("color", "#000000")[:7] + "ff"}]}
        return f'<rect {rect} {self.fill_attrs(grad, fid)}/>'

    def shadow_filter(self, n, fx, i) -> str:
        fid = f"sh-{n['id']}-{i}"
        c, ca = color(fx.get("color", "#000000"))
        src = "SourceAlpha"
        spread = ""
        if fx.get("spread"):
            spread, src = f'<feMorphology in="SourceAlpha" operator="dilate" radius="{fmt(fx["spread"])}" result="sp"/>', "sp"
        self.defs.append(f'<filter id="{fid}" filterUnits="userSpaceOnUse" x="0" y="0" width="{fmt(self.W)}" '
                         f'height="{fmt(self.H)}" color-interpolation-filters="sRGB">{spread}'
                         f'<feGaussianBlur in="{src}" stdDeviation="{fmt(fx.get("blur", 0))}"/>'
                         f'<feOffset dx="{fmt(fx.get("dx", 0))}" dy="{fmt(fx.get("dy", 0))}" result="o"/>'
                         f'<feFlood flood-color="{c}" flood-opacity="{fmt(ca * fx.get("opacity", 1))}"/>'
                         f'<feComposite in2="o" operator="in"/></filter>')
        return fid

    def node(self, n) -> str:
        if not n.get("visible", True):
            return f"<!-- {n['id']} hidden -->"
        t = n["type"]
        if t == "group":
            idx = {x["id"]: x for x in self.scene["nodes"]}
            body = "".join(self.node(idx[c]) for c in n["children"])
        elif t == "text":
            body = self.text(n)
        elif t == "image":
            body = self.image(n)
        elif t in ("shape", "path"):
            body = self.shape(n)
        elif t == "background":
            body = self.background(n)
        else:
            body = self.effect_node(n)
        g = n["geometry"]
        attrs = [f'id="{n["id"]}"']
        if n.get("transform"):
            attrs.append(f'transform="matrix({" ".join(fmt(v) for v in n["transform"])})"')
        elif g.get("rotation"):
            attrs.append(f'transform="rotate({fmt(g["rotation"])} {fmt(g["x"] + g["w"] / 2)} {fmt(g["y"] + g["h"] / 2)})"')
        style = []
        if n.get("opacity", 1) != 1:
            style.append(f"opacity:{fmt(n['opacity'])}")
        if n.get("blend", "normal") != "normal":
            style.append(f"mix-blend-mode:{n['blend']}")
        if style:
            attrs.append(f'style="{";".join(style)}"')
        blurs = [fx for fx in n.get("effects", []) if fx["type"] == "layer_blur" and fx.get("enabled", True)]
        if blurs:
            fid = f"lb-{n['id']}"
            self.defs.append(f'<filter id="{fid}" color-interpolation-filters="sRGB">'
                             f'<feGaussianBlur stdDeviation="{fmt(blurs[0].get("blur", 0))}"/></filter>')
            attrs.append(f'filter="url(#{fid})"')
        shadows = ""
        for i, fx in enumerate(n.get("effects", [])):
            if fx["type"] == "drop_shadow" and fx.get("enabled", True):
                blend = fx.get("blend", "normal")
                st = f' style="mix-blend-mode:{blend}"' if blend != "normal" else ""
                shadows += f'<use href="#{n["id"]}" filter="url(#{self.shadow_filter(n, fx, i)})"{st}/>'
        return f'<g data-dna="{n["id"]}">{shadows}<g {" ".join(attrs)}>{body}</g></g>'

    def compile(self) -> str:
        body = "".join(self.node(n) for n in self.scene["nodes"] if not n.get("parent"))
        faces = "".join(
            f'@font-face{{font-family:"{fam}";src:url("{self.href(aid)}");font-weight:1 1000;font-style:normal;}}'
            for aid, fam in self.fonts.items())
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(self.W)}" height="{fmt(self.H)}" '
                f'viewBox="0 0 {fmt(self.W)} {fmt(self.H)}"><style>{faces}</style>'
                f'<defs>{"".join(self.defs)}</defs>{body}</svg>')


def compile_svg(scene, tdir, href_mode="file", fit_sizes=None):
    c = Compiler(scene, tdir, href_mode, fit_sizes)
    return c.compile(), c.fonts


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


def launch(p):
    """Launch the renderer: DESIGN_DNA_BROWSER if set, else the first of Chrome, Edge, bundled Chromium.
    Returns (browser, channel). The channel and version are recorded in every render profile."""
    from playwright.sync_api import Error

    tried = []
    for ch in ([CHANNEL] if CHANNEL else CHANNELS):
        try:
            return p.chromium.launch(channel=None if ch == "chromium" else ch, args=BROWSER_ARGS), ch
        except Error as e:
            tried.append(f"{ch}: {str(e).strip().splitlines()[0][:160]}")
    raise DnaError("no Chromium-based browser could be launched", "renderer_unavailable",
                   {"tried": tried, "fix": "install Google Chrome or Microsoft Edge, or run `python -m playwright install chromium`"})


@contextmanager
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b, ch = launch(p)
        try:
            yield b, ch
        finally:
            b.close()


def _load(page, svg: str, work: Path):
    work.mkdir(parents=True, exist_ok=True)
    f = work / "page.html"
    f.write_text('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;padding:0;background:transparent}'
                 f'svg{{display:block}}</style>{svg}', encoding="utf-8")
    page.goto(f.as_uri(), wait_until="load")
    faces = page.evaluate("""async () => { await Promise.all([...document.fonts].map(f => f.load().catch(() => null)));
        await document.fonts.ready; return [...document.fonts].map(f => [f.family, f.status]); }""")
    bad = [f for f in faces if f[1] != "loaded"]
    if bad:
        raise DnaError(f"fonts failed to load: {bad}", "font_load_failed")
    broken = page.evaluate("""async () => { const out = [];
        for (const im of document.querySelectorAll('image')) { const i = new Image(); i.src = im.getAttribute('href');
          try { await i.decode(); } catch (e) { out.push(im.getAttribute('href')); } } return out; }""")
    if broken:
        raise DnaError(f"images failed to decode: {broken}", "asset_load_failed")


def _measure_fit(page, scene) -> dict:
    texts = []
    for n in scene["nodes"]:
        if n["type"] == "text" and n.get("visible", True):
            f = resolved_font(scene, n)
            fit = n.get("fit") or {"policy": "strict"}
            texts.append({"id": n["id"], "w": n["geometry"]["w"], "h": n["geometry"]["h"], "size": f["size"],
                          "lh": n["line_height"], "policy": fit["policy"], "min": fit.get("min_size", f["size"]),
                          "maxLines": fit.get("max_lines", 999), "step": FIT_STEP})
    return page.evaluate("""(texts) => { const out = {};
      for (const t of texts) { const el = document.getElementById(t.id).querySelector('text');
        const spans = [...el.querySelectorAll('tspan')]; const n = spans.length;
        const check = (s) => { el.setAttribute('font-size', s);
          const widths = spans.map(x => x.getComputedTextLength());
          const lh = t.lh * s / t.size;
          return {widths, ok_w: Math.max(...widths) <= t.w + 0.5, ok_h: n * lh <= t.h + 0.5, ok_lines: n <= t.maxLines}; };
        let s = t.size, r = check(s);
        const fits = (r) => r.ok_w && r.ok_h && r.ok_lines;
        if (!fits(r) && t.policy === 'fit') { while (!fits(r) && s - t.step >= t.min - 1e-9) { s -= t.step; r = check(s); } }
        el.setAttribute('font-size', t.size);
        out[t.id] = {status: fits(r) ? (s === t.size ? 'fits' : 'fitted') : 'overflow', declared_size: t.size,
          size: s, lines: n, max_line_width: Math.max(...r.widths), box_w: t.w, box_h: t.h,
          height_needed: n * t.lh * s / t.size, policy: t.policy, min_size: t.min, ok_w: r.ok_w, ok_h: r.ok_h, ok_lines: r.ok_lines};
      } return out; }""", texts)


def _isolated_bounds(page, scene, W, H) -> dict:
    import io

    import numpy as np
    from PIL import Image

    out = {}
    for n in scene["nodes"]:
        page.evaluate("""(id) => { let s = document.getElementById('dna-iso'); if (!s) { s = document.createElement('style');
            s.id = 'dna-iso'; document.head.appendChild(s); }
            s.textContent = `[data-dna]{visibility:hidden} [data-dna="${id}"], [data-dna="${id}"] *{visibility:visible}`; }""", n["id"])
        lay = page.evaluate("(id) => { const r = document.querySelector(`[data-dna=\"${id}\"]`).getBoundingClientRect();"
                            " return [r.x, r.y, r.width, r.height]; }", n["id"])
        png = capture(page, clip={"x": 0, "y": 0, "width": W, "height": H}, omit_background=True, animations="disabled")
        alpha = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[:, :, 3]
        ys, xs = np.nonzero(alpha)
        out[n["id"]] = {"layout": [round(v, 3) for v in lay],
                        "rendered": None if not len(xs) else [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]}
    page.evaluate("() => { const s = document.getElementById('dna-iso'); if (s) s.remove(); }")
    return out


def render(scene, tdir, out_dir, isolate=False, formats=("png",), name="render") -> dict:
    """Render scene to <out_dir>/<name>.png (+ .svg master with copied assets). Raises DnaError on conflicts."""
    from importlib.metadata import version

    rep = check_scene(scene, tdir)
    if not rep["valid"]:
        raise DnaError("scene does not validate; refusing to render", "invalid_scene", rep)
    W, H = scene["canvas"]["width"], scene["canvas"]["height"]
    if W != int(W) or H != int(H):
        raise DnaError("canvas must be whole pixels to rasterize", "bad_canvas")
    W, H = int(W), int(H)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tdir) / ".render"
    with browser() as (b, channel):
        page = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        svg, fonts = compile_svg(scene, tdir)
        _load(page, svg, work)
        fit = _measure_fit(page, scene)
        over = {k: v for k, v in fit.items() if v["status"] == "overflow"}
        if over:
            raise DnaError("text does not fit under the declared constraints; nothing was shrunk or clipped",
                           "fit_conflict", {"overflow": over, "options": [
                               "shorten the copy", "enlarge the text box (unlock layout for that node)",
                               "allow another line (raise fit.max_lines and box height)",
                               "allow size reduction: set fit.policy=fit with a readable fit.min_size"]})
        sizes = {k: v["size"] for k, v in fit.items() if v["status"] == "fitted"}
        if sizes:
            svg, fonts = compile_svg(scene, tdir, fit_sizes=sizes)
            _load(page, svg, work)
        png = out_dir / f"{name}.png"
        capture(page, path=str(png), clip={"x": 0, "y": 0, "width": W, "height": H},
                        omit_background=scene["canvas"]["alpha"] == "transparent", animations="disabled", caret="hide")
        bounds = _isolated_bounds(page, scene, W, H) if isolate else {}
        bver = b.version
    result = {"png": str(png), "png_sha256": sha256_file(png), "fit": fit, "fitted_sizes": sizes, "bounds": bounds,
              "warnings": rep["warnings"], "editability": rep["editability"],
              "render_profile": {
                  "renderer": "playwright-chromium", "channel": channel, "browser_version": bver,
                  "playwright": version("playwright"), "python": platform.python_version(), "os": platform.platform(),
                  "viewport": [W, H], "device_scale_factor": 1, "browser_args": BROWSER_ARGS,
                  "color_policy": "sRGB forced; image assets untagged -> treated as sRGB", "alpha": scene["canvas"]["alpha"],
                  "font_synthesis": "none unless declared", "animations": "disabled",
                  "randomness": "feTurbulence seeds fixed in scene",
                  "fonts": [{"asset": a, "sha256": scene["assets"][a]["sha256"], "names": scene["assets"][a].get("font_names")} for a in fonts]}}
    if "svg" in formats:
        rel_svg, _ = compile_svg(scene, tdir, href_mode="relative", fit_sizes=sizes)
        (out_dir / f"{name}.svg").write_text(rel_svg, encoding="utf-8")
        (out_dir / "assets").mkdir(exist_ok=True)
        for a in scene["assets"].values():
            shutil.copy2(safe_path(tdir, a["path"]), out_dir / a["path"])
        result["svg"] = str(out_dir / f"{name}.svg")
        result["export_notes"] = ["SVG master references assets/ relatively; keep the folder together.",
                                  "Design apps that ignore @font-face need the font files installed to show identical text.",
                                  "SVG filters (shadows, treatments) may be rasterized or approximated by some editors."]
    write_json(out_dir / f"{name}.report.json", result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("template")
    ap.add_argument("--scene")
    ap.add_argument("--out", required=True)
    ap.add_argument("--isolate", action="store_true", help="also measure per-node rendered bounds")
    ap.add_argument("--formats", default="png,svg")
    ap.add_argument("--name", default="render")
    a = ap.parse_args()
    tdir = template_dir(a.template)
    try:
        r = render(read_json(a.scene or tdir / "scene.json"), tdir, a.out, a.isolate, a.formats.split(","), a.name)
    except DnaError as e:
        print(json.dumps(e.as_dict(), indent=2, ensure_ascii=False))
        return 2
    print(json.dumps({k: r[k] for k in ("png", "png_sha256", "fitted_sizes", "warnings")}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
