# Adapters and capabilities

Run `python scripts/capabilities.py` at intake: it reports what this machine can do right now (libraries,
renderer version, OCR, raqm). Missing tools degrade to `unsupported` / `unknown`; nothing is fabricated.

## Implemented (static flat graphics)

| Area | Implementation |
|---|---|
| Intake | raster PNG/JPEG/WebP/BMP/GIF(first frame)/TIFF; metadata, ICC→sRGB canonical copy, framing hypothesis |
| Measurement | `measure.py` ink / profile / edges / radius / shadow; `sample_colors.py`; `font_candidates.py`; `fit_text.py` |
| Model | JSON Schema 2020-12 validation (`jsonschema`), semantic checks, evidence resolution, editability shortcut detector |
| Render | SVG master → Playwright + Google Chrome / Microsoft Edge / bundled Chromium (first available; `DESIGN_DNA_BROWSER` pins), HarfBuzz shaping, bidi, DPR 1, `--force-color-profile=srgb`, LCD text off, GPU off, animations off, fonts from pinned files (`@font-face`, `font-synthesis:none`), images pre-decoded |
| Supported paint | solid, token, linear/radial gradient (sRGB interpolation) |
| Supported masks | rect radius, ellipse, path, asset (alpha/luminance), feather (shape masks) |
| Supported treatments | grayscale, saturate, contrast, brightness, hue_rotate, tint, blur (ordered SVG filter chain) |
| Supported effects | drop_shadow (offset, σ, spread, colour, opacity, blend; rendered as live `<use>` copies), layer_blur |
| Effect nodes | grain (seeded feTurbulence, deterministic), vignette |
| Blend modes | CSS `mix-blend-mode` set (normal … luminosity) |
| Compare | exact, MAE/RMSE, SSIM (scikit-image), ΔE2000, regions, geometry, typography, editability |
| Edits | typed ops, locks, constraints, transactions, variants, undo, export PNG + SVG |

Pinned renderer record (stored in every render report): browser channel + version, Playwright, Python, OS,
viewport, DPR, flags, colour policy, alpha, font files + hashes, randomness (seeded only).

## Explicitly unsupported (returns `unsupported`, never ignored)

- Adapters: PDF/document, PSD/Figma/AI source, website/UI live capture, packaging/dielines, motion/timing, 3D.
  Workaround offered: export a still and scan it (layers, states, timing stay `unknown`).
- OCR engine (none installed): transcription is Claude vision, labelled `manual_observation`.
- Automatic segmentation: element boundaries are proposed by Claude and measured by the tools (assisted).
- Font identification beyond supplied candidate files; identity needs source evidence.
- Effects: bevel/emboss, inner shadow, outer glow, gradient strokes, stroke align inside/outside, text-on-path,
  feathered asset masks, blend-if, 3D extrusion, perspective warps (matrix transforms only).
- Generated/inpainted assets inside the engine (supply the file; it is tracked as `generated`, never "recovered").
- Exact CMYK/print separations.

## Exports that cannot represent the master exactly

- SVG opened in design apps that ignore `@font-face`: text needs the font installed; SVG filters may be
  rasterised or approximated.
- JPEG: lossy, no alpha. PNG is the verified export.

## Adding an adapter

Add it behind the same evidence + scene contracts: an intake path that writes `source/` + evidence, a capability
line in `capabilities.py`, renderer support or an explicit `unsupported` validation entry, and at least one
acceptance test with retained inputs/outputs before calling it implemented.
