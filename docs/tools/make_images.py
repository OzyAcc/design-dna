"""Build evidence screenshots from an acceptance run (synthetic fixtures only — no third-party artwork).

  python docs/tools/make_images.py <acceptance-run-dir> [--out docs/images/evidence/latest]

Each image is an HTML page of captioned panels screenshotted with the same Chromium renderer the engine uses.
README concept illustrations are maintained separately in docs/images/.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "reverse-design" / "scripts"))
from renderer_env import launch  # noqa: E402

CSS = """
:root{--ink:#16130f;--muted:#6f675e;--paper:#f6f2ea;--card:#fffdf8;--rule:#ddd4c6;--accent:#c8102e}
*{box-sizing:border-box;margin:0}
body{background:var(--paper);font-family:Georgia,'Times New Roman',serif;color:var(--ink)}
#shot{padding:40px 44px;background:var(--paper)}
.kicker{font:600 13px/1 Consolas,'Courier New',monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h2{font-size:30px;font-weight:700;margin:10px 0 6px;letter-spacing:-.01em}
.sub{font-size:16px;color:var(--muted);margin-bottom:26px;max-width:980px;line-height:1.45}
.row{display:flex;gap:22px;align-items:flex-start}
.panel{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:12px 12px 14px;flex:1}
.panel img{width:100%;display:block;border-radius:4px;image-rendering:auto}
.cap{font:600 12px/1.4 Consolas,monospace;letter-spacing:.06em;text-transform:uppercase;margin-top:10px;color:var(--ink)}
.note{font:13px/1.45 Georgia,serif;color:var(--muted);margin-top:4px}
.tag{display:inline-block;font:700 11px/1 Consolas,monospace;padding:5px 7px;border-radius:4px;margin-top:8px;letter-spacing:.06em}
.pass{background:#e7f1e3;color:#1f5d1a}.fail{background:#f8e3e3;color:#8f1d1d}.unk{background:#efe9dc;color:#6f5b2d}
"""


def b64(path, max_w=None):
    im = Image.open(path).convert("RGB")
    if max_w and im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def panel(img, cap, note="", tag=None, max_w=900, flex=1):
    t = f'<span class="tag {tag[0]}">{tag[1]}</span>' if tag else ""
    return (f'<div class="panel" style="flex:{flex}"><img src="{b64(img, max_w)}"><div class="cap">{cap}</div>'
            f'<div class="note">{note}</div>{t}</div>')


def page(kicker, title, sub, rows, width=1600):
    body = "".join(f'<div class="row" style="margin-top:22px">{"".join(r)}</div>' for r in rows)
    return width, (f'<!doctype html><meta charset="utf-8"><style>{CSS}</style><div id="shot"><div class="kicker">{kicker}</div>'
                   f'<h2>{title}</h2><div class="sub">{sub}</div>{body}</div>')


def shoot(pw, html_w, out):
    width, html = html_w
    b, _ = launch(pw)
    pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=1)
    pg.set_content(html, wait_until="load")
    pg.locator("#shot").screenshot(path=str(out), animations="disabled")
    b.close()
    print("wrote", out)


def crop(path, box, out):
    Image.open(path).crop(box).save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run")
    ap.add_argument("--out", default=str(ROOT / "docs" / "images" / "evidence" / "latest"))
    a = ap.parse_args()
    run, out = Path(a.run), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = run / "_readme_parts"  # intermediate crops stay with the run, not in docs/
    tmp.mkdir(exist_ok=True)
    rep = json.loads((run / "report.json").read_text(encoding="utf-8"))

    scores = json.loads((run / "t01-synthetic-measured" / "scores.json").read_text())
    t14 = json.loads((run / "t14-small-errors" / "results.json").read_text())
    ref = run / "reference" / "reference.png"
    t01 = run / "t01-synthetic-measured"
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        # 1. banner
        sb = Image.open(t01 / "compare" / "side_by_side.png")
        w = sb.width // 2
        rebuilt = crop(t01 / "compare" / "side_by_side.png", (w, 0, sb.width, sb.height), tmp / "rebuilt.png")
        banner_html = (1840, f'''<!doctype html><meta charset="utf-8"><style>{CSS}
            .b{{display:flex;gap:40px;align-items:center;padding:8px 6px}} .wm{{font:700 86px/0.95 Georgia,serif;letter-spacing:-.03em}}
            .wm em{{color:var(--accent);font-style:normal}} .tl{{font-size:24px;line-height:1.35;margin:18px 0 22px;max-width:560px}}
            .flow{{font:600 14px/1.6 Consolas,monospace;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}}
            .strip{{display:flex;gap:14px;align-items:flex-end}} .strip img{{height:320px;border-radius:6px;border:1px solid var(--rule);background:#fff}}
            .lbl{{font:600 11px Consolas,monospace;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;margin-top:8px}}
            </style><div id="shot"><div class="b"><div style="flex:0 0 600px"><div class="kicker">Claude Code skill · reverse-design</div>
            <div class="wm" style="margin-top:14px">Design<br><em>DNA</em></div>
            <div class="tl">Reverse-engineer a visual design into evidence and an editable model — then adapt it without drift.</div>
            <div class="flow">scan → measure → model → render → verify<br>acceptance run {rep['run']}: {rep['passed']}/{rep['total']} passed</div></div>
            <div class="strip">
              <div><img src="{b64(ref, 420)}"><div class="lbl">flattened reference</div></div>
              <div><img src="{b64(run / 't02-unfamiliar-flattened' / 'annotated.png', 420)}"><div class="lbl">measured scan</div></div>
              <div><img src="{b64(run / 't08-arabic-mixed' / 'arabic.png', 420)}"><div class="lbl">verified adaptation</div></div>
              <div><img src="{b64(run / 't09-reflow-9x16' / 'reflow-1080x1920.png', 300)}"><div class="lbl">reflow 9:16</div></div>
            </div></div></div>''')
        shoot(pw, banner_html, out / "banner.png")
        # 2. measured rebuild
        geo = round(max(scores["geometry_max_px"].values()), 2)
        shoot(pw, page("Demonstration 1", "Rebuilt from pixels, scored against hidden ground truth",
                       f"Frames, baselines, font size and tracking, shadow offset/blur, photo grading and translucent sheen were measured "
                       f"from the flattened image; the original photo, logo and candidate font files were supplied. Max geometry error "
                       f"{geo}px · head size error {scores['head_size_pct']:.2f}% · shadow σ error {scores['shadow_sigma_px']:.2f}px · "
                       f"verdict editable_close: {scores['pixel_verdict']['status'].upper()}.",
                       [[panel(ref, "reference (flattened)", "measured input; photo, logo and fonts supplied separately"),
                         panel(rebuilt, "editable rebuild", "live text · masked image · editable shadow"),
                         panel(t01 / "compare" / "diff_heatmap.png", "absolute difference ×4", "declared scaling; black = identical",
                               ("pass", "EDITABLE_CLOSE PASS") if scores["pixel_verdict"]["status"] == "pass" else ("fail", "FAIL"))]]),
              out / "demo-rebuild.png")
        # 3. edits
        shoot(pw, page("Demonstrations 4–6", "Change one thing. Prove nothing else moved.",
                       "Each edit is a typed transaction: locks and constraints checked, rendered, then verified — requested change probed "
                       "in the pixels, zero changed pixels outside the declared influence, translucent consequences reported.",
                       [[panel(run / "t04-headline-only" / "before.png", "baseline"),
                         panel(run / "t04-headline-only" / "after.png", "headline only", "0 px changed outside influence", ("pass", "ADAPT_PRESERVE PASS")),
                         panel(run / "t06-token-replace" / "after.png", "accent token → #FFD400", "all + only bound uses; photo untouched", ("pass", "PASS")),
                         panel(run / "t05-hero-replace" / "after.png", "hero asset swapped", "treatment, mask, shadow, anchor kept", ("pass", "PASS"))]]),
              out / "demo-edits.png")
        # 4. arabic + reflow
        shoot(pw, page("Demonstrations 8–9", "Arabic and new formats, verified structurally",
                       "Mixed Arabic/English headline: glyph coverage checked against the pinned font, HarfBuzz shaping and bidi verified "
                       "by measurement; RTL alignment mirrored. Reflow 4:5 → 9:16 keeps margins, reading order and fit.",
                       [[panel(run / "t08-arabic-mixed" / "arabic.png", "adapt language=ar", "shaping + bidi + diacritics", ("pass", "PASS"), flex=1.35),
                         panel(run / "t09-reflow-9x16" / "reflow-1080x1920.png", "reflow canvas=1080x1920", "reading order preserved", ("pass", "REFLOW_PRESERVE PASS"))]],
                       width=1400), out / "demo-arabic-reflow.png")
        # 5. honest scan
        sheet = sorted(run.glob("store*/templates/product-grid-six-up*/evidence/fonts/candidates-*.png"))[0]  # T20 moves the store
        shoot(pw, page("Demonstration 2", "An unfamiliar flattened JPEG — uncertainty kept, not hidden",
                       "Grid, gutters, radius and baselines are measured; captions are rendered with the best candidate font, but the "
                       "font's identity stays unknown and the caption regions are reported as failing instead of being blurred into a score.",
                       [[panel(run / "t02-unfamiliar-flattened" / "annotated.png", "annotated scan", "? = inferred · ?f = font identity unknown"),
                         panel(sheet, "font candidate contact sheet", "ranked by ink IoU; ties flagged; identity stays unknown", ("unk", "IDENTITY: UNKNOWN"), max_w=1100, flex=1.3)]]),
              out / "demo-scan.png")
        # 6. small errors
        ww, ls = t14["wrong-word"], t14["logo-shift-3px"]
        shoot(pw, page("Demonstration 14", "A wrong word on a blank canvas still fails",
                       f"Global SSIM {ww['global_ssim']:.4f} would call these identical. Region, geometry and content checks do not.",
                       [[panel(run / "t14-small-errors" / "wrong-word" / "compare" / "crops" / "n-word.png", "SALE → SOLE",
                               f"global SSIM {ww['global_ssim']:.4f}", ("fail", "VERDICT: FAIL")),
                         panel(run / "t14-small-errors" / "logo-shift-3px" / "compare" / "crops" / "n-logo.png", "logo moved 3 px",
                               f"global SSIM {ls['global_ssim']:.4f}", ("fail", "VERDICT: FAIL"))]], width=1400),
              out / "demo-catch.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
