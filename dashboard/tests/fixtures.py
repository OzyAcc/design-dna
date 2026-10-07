"""Synthetic, unbranded fixtures for dashboard tests (explicitly synthetic: drawn here, never presented as real work).

poster(): an 800x1000 editorial poster with a paper background, an accent bar, a kicker, a two-line serif headline,
a photo region and a dark CTA pill, drawn with the repository's vendored OFL/Bitstream Vera fonts.
product(): a simple chair-like product photo on a light ground.
The element boxes are returned so a test can act as the reviewer of a manual scan.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parents[2] / "skills" / "reverse-design" / "tests" / "fonts"
PAPER, INK, ACCENT = (246, 242, 234), (22, 19, 15), (200, 16, 46)


def _png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def poster() -> tuple[bytes, list[dict]]:
    W, H = 800, 1000
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    sans = ImageFont.truetype(str(FONTS / "LiberationSans-Bold.ttf"), 26)
    serif = ImageFont.truetype(str(FONTS / "DejaVuSerif-Bold.ttf"), 64)
    d.rectangle([60, 60, 179, 69], fill=ACCENT)
    d.text((60, 96), "NEW SEASON", font=sans, fill=ACCENT)
    d.text((60, 150), "Made to", font=serif, fill=INK)
    d.text((60, 230), "last years", font=serif, fill=INK)
    photo = Image.new("RGB", (680, 420))
    pd = ImageDraw.Draw(photo)
    for y in range(420):
        pd.line([(0, y), (680, y)], fill=(180 - y // 6, 160 - y // 8, 140 - y // 10))
    pd.ellipse([220, 90, 460, 330], fill=(120, 140, 110))
    photo = photo.filter(ImageFilter.GaussianBlur(1.2))
    im.paste(photo, (60, 380))
    d.rounded_rectangle([60, 860, 319, 923], radius=31, fill=INK)
    d.text((189, 892), "Shop now", font=sans, fill=PAPER, anchor="mm")
    elements = [
        {"key": "background", "type": "background", "role": "background", "bbox": [0, 0, W, H], "status": "accepted", "source": "user"},
        {"key": "accent", "type": "shape", "role": "accent", "bbox": [56, 56, 128, 18], "status": "accepted", "source": "user", "slot": False},
        {"key": "kicker", "type": "text", "role": "kicker", "bbox": [54, 92, 240, 40], "text": "NEW SEASON", "align": "left", "status": "accepted",
         "source": "user", "slot": True},
        {"key": "headline", "type": "text", "role": "headline", "bbox": [54, 150, 420, 170], "text": "Made to\nlast years", "align": "left",
         "status": "accepted", "source": "user", "slot": True},
        {"key": "photo", "type": "image", "role": "product", "bbox": [60, 380, 680, 420], "status": "accepted", "source": "user", "slot": True},
        {"key": "cta-pill", "type": "shape", "role": "button", "bbox": [56, 856, 268, 72], "status": "accepted", "source": "user", "slot": False},
        {"key": "cta", "type": "text", "role": "cta", "bbox": [120, 874, 140, 38], "text": "Shop now", "align": "center", "status": "accepted",
         "source": "user", "slot": True},
    ]
    return _png(im), elements


def product(color=(150, 110, 70), w=900, h=900) -> bytes:
    im = Image.new("RGB", (w, h), (236, 236, 232))
    d = ImageDraw.Draw(im)
    d.rectangle([w * 0.3, h * 0.35, w * 0.7, h * 0.55], fill=color)
    d.rectangle([w * 0.3, h * 0.12, w * 0.38, h * 0.55], fill=color)
    for x in (0.31, 0.66):
        d.rectangle([w * x, h * 0.55, w * (x + 0.03), h * 0.85], fill=tuple(int(c * 0.7) for c in color))
    return _png(im.filter(ImageFilter.GaussianBlur(0.8)))
