"""Deterministic synthetic assets for the acceptance suite (no randomness, no network).

  python build_fixtures.py <out_dir>
Writes: bag.png (photo-like product, contains a yellow brass clasp), bag2.png (different aspect),
bag_baked.png (RGBA cutout with a BAKED shadow), blank_1080x1350.png, logo.json (vector path),
grid_flattened.jpg + grid_truth.json (an 'unfamiliar' flattened 6-up product grid and its hidden truth).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def vgrad(w, h, top, bot):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
    return im


def bag(out: Path):
    im = vgrad(1200, 960, (233, 220, 200), (214, 196, 166))
    d = ImageDraw.Draw(im)
    d.ellipse([360, 760, 840, 830], fill=(196, 176, 146))                      # baked floor contact in the photo
    d.arc([470, 170, 730, 470], 180, 360, fill=(110, 58, 32), width=26)          # handle
    d.rounded_rectangle([380, 330, 820, 800], 36, fill=(138, 75, 42))            # body
    d.rounded_rectangle([380, 330, 820, 520], 36, fill=(110, 58, 32))            # flap
    d.rectangle([380, 480, 820, 520], fill=(110, 58, 32))
    d.ellipse([570, 490, 630, 550], fill=(212, 169, 60))                         # brass clasp (yellowish)
    d.line([(400, 560), (800, 560)], fill=(160, 96, 60), width=4)               # stitching
    im.save(out / "bag.png")


def bag2(out: Path):
    im = vgrad(900, 1100, (220, 227, 232), (201, 210, 217))
    d = ImageDraw.Draw(im)
    d.arc([300, 180, 600, 520], 180, 360, fill=(30, 50, 62), width=22)
    d.polygon([(220, 360), (680, 360), (740, 900), (160, 900)], fill=(47, 72, 88))
    d.rectangle([160, 860, 740, 900], fill=(36, 58, 72))
    im.save(out / "bag2.png")


def bag_baked(out: Path):
    im = Image.new("RGBA", (1000, 900), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([220, 760, 800, 860], fill=(0, 0, 0, 150))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(18)))      # the baked shadow
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([260, 260, 740, 800], 40, fill=(120, 30, 40, 255))
    d.arc([380, 90, 620, 380], 180, 360, fill=(90, 20, 28, 255), width=24)
    im.save(out / "bag_baked.png")


GRID_LABELS = ["ALBA", "MERIDIAN", "OSLO", "LUMEN", "NOVA", "SAGE"]


def room(i: int, size: int = 318) -> Image.Image:
    """Procedural 'interior photo': wall/floor gradients, a sofa, a wall frame, a lamp — distinct per index."""
    walls = [(222, 228, 236), (236, 230, 220), (226, 233, 224), (240, 236, 230), (230, 226, 236), (238, 232, 226)]
    sofas = [(70, 110, 160), (150, 170, 140), (196, 180, 160), (120, 90, 70), (60, 60, 70), (226, 190, 70)]
    w = walls[i]
    im = vgrad(size, size, w, tuple(max(0, c - 18) for c in w))
    d = ImageDraw.Draw(im)
    d.rectangle([0, int(size * .72), size, size], fill=tuple(max(0, c - 60) for c in w))           # floor
    fx = 40 + 30 * i % 90
    d.rectangle([fx, 40, fx + 90, 120], fill=(250, 250, 248), outline=(90, 90, 90), width=3)          # wall frame
    d.ellipse([fx + 25, 60, fx + 65, 100], fill=sofas[(i + 2) % 6])
    s = sofas[i]
    d.rounded_rectangle([50, 170, 270, 240], 18, fill=s)                                            # sofa back
    d.rounded_rectangle([40, 205, 280, 262], 14, fill=tuple(min(255, c + 20) for c in s))           # seat
    d.line([(250 - 10 * i, 60), (250 - 10 * i, 230)], fill=(60, 60, 60), width=3)                    # lamp pole
    d.ellipse([228 - 10 * i, 40, 272 - 10 * i, 72], fill=(250, 240, 210))
    return im.filter(ImageFilter.GaussianBlur(0.6))


def grid_flattened(out: Path):
    """An 'unfamiliar' flattened reference: drawn with Pillow/FreeType (not the engine's renderer), labels in a
    font outside the candidate list when available, rounded photo corners, saved as lossy 4:2:0 JPEG."""
    from PIL import ImageFont

    import fontset

    canvas = Image.new("RGB", (1080, 1080), "white")
    cols, rows, size, radius, baselines = [40, 381, 722], [105, 552], 318, 8, [485, 932]
    face = Path(fontset.path("caption") or fontset.path("caption_fallback"))
    font = ImageFont.truetype(str(face), 30)
    if face.name == fontset.SETS[fontset.name()]["caption"]:
        font.set_variation_by_name("Bold")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    d = ImageDraw.Draw(canvas)
    for i, name in enumerate(GRID_LABELS):
        r, c = divmod(i, 3)
        canvas.paste(room(i, size), (cols[c], rows[r]), mask)
        d.text((cols[c] + size / 2, baselines[r]), name, font=font, fill=(17, 17, 17), anchor="ms")
    canvas.save(out / "grid_flattened.jpg", quality=82, subsampling=2)
    (out / "grid_truth.json").write_text(json.dumps({
        "labels": GRID_LABELS, "frames": [[cols[i % 3], rows[i // 3], size, size] for i in range(6)], "radius": radius,
        "baselines": baselines, "label_font": face.name}), encoding="utf-8")


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    bag(out)
    bag2(out)
    bag_baked(out)
    grid_flattened(out)
    Image.new("RGB", (1080, 1350), (255, 255, 255)).save(out / "blank_1080x1350.png")
    (out / "logo.json").write_text(json.dumps({"d": "M0 56 L28 0 L50 40 L72 0 L100 56 L84 56 L72 30 L50 70 L28 30 L16 56 Z",
                                               "box": [100, 70]}), encoding="utf-8")
    print(f"fixtures -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
