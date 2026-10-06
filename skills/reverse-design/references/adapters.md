# Adapters and capabilities

Run `python scripts/capabilities.py` at intake: it reports what this machine can do right now (libraries,
renderer version, raqm, tooling present). Installed tooling is not an adapter: OCR stays `unsupported` even if
tesseract exists, because nothing is wired to it. Missing tools degrade to `unsupported` / `unknown`.

## Implemented (static flat graphics)

| Area | Implementation |
|---|---|
| Intake | raster PNG/JPEG/WebP/BMP/GIF (first frame)/TIFF; metadata (raw header size kept), EXIF orientation applied, ICC→sRGB canonical copy; the canvas is the oriented canonical image |
| Measurement | `measure.py` ink / profile / edges / radius / shadow; `sample_colors.py`; `font_candidates.py`; `fit_text.py` |
| Model | JSON Schema 2020-12, semantic checks, evidence resolution, coverage + facet completeness, slot limits, passport completeness, editability (shortcut, assembly, baked content) |
| Render | scene → SVG → PNG via Playwright + Chrome / Edge / bundled Chromium; pinned after the baseline (`renderer_env.py`), drift stops work; HarfBuzz shaping, bidi; DPR 1, `--force-color-profile=srgb`, LCD text off, GPU off, animations off; fonts from content-hashed files (`@font-face`, `font-synthesis:none`); images pre-decoded; **network requests blocked** (only `file:` inside the template and `data:` load) |
| Serialization safety | asset ids and OpenType tags constrained by schema; every name written into CSS is a CSS-escaped string; `style` attributes are XML-escaped; every compiled SVG is parsed and refused if it contains anything beyond the drawing vocabulary (no `script`, `foreignObject`, links, `on*` handlers, external hrefs) |
| Paint | solid, token, linear/radial gradient (sRGB interpolation) — for fills and strokes |
| Text | live `<text>/<tspan>`, explicit lines, alignment by direction, tracking, line height, OpenType features + variation axes, horizontal scale, centre-aligned text stroke |
| Masks | rect radius, ellipse, path, asset (alpha/luminance), feather (shape masks) |
| Treatments | grayscale, saturate, contrast, brightness, hue_rotate, tint, blur (ordered SVG filter chain) |
| Effects | drop_shadow (offset, σ, spread, colour, opacity, blend; live `<use>` copies), layer_blur |
| Effect nodes | grain (seeded feTurbulence, deterministic), vignette |
| Compare | RGBA identity, appearance, MAE/RMSE, SSIM, ΔE2000, regions, geometry, typography, editability |
| Edits | typed ops, property + pixel locks, constraints, keep-everything-else scopes, transactions, variants, undo |
| Export | PNG + self-contained SVG + element manifest + round-trip verification |
| Persistence | portable `.dnab` bundles, FilesystemBackend, library retrieval by id/name |

Pin record (passport.render_pin, and every render report): browser channel + version, flags, DPR, colour policy,
font synthesis (hard — drift stops work); Playwright, Python, OS, package versions (soft — reported); viewport, alpha,
fonts + hashes, randomness (recorded). Exact tested versions: `requirements-lock.txt` at the package root.

## What the SVG export contains (`svg_export.py` manifest)

| Element | Exported as | Editable in design tools as |
|---|---|---|
| text node | `live_text`: `<text>/<tspan>` + embedded (or name-referenced) font | text, if the tool honours the font |
| shape / path / colour background | `vector` | geometry |
| image / photo background | `embedded_raster` (data URI) inside a clip/mask | a whole image only |
| grain | `procedural_texture` (feTurbulence, rendered at view time) | usually rasterised |
| shadows, layer blur, colour treatments | `filter_effects` on the element (live SVG filters) | often rasterised or dropped |

`is_editable_master` is always `false`: the scene model is the editable master. The manifest's claims are checked by
rendering the exported file itself (`svg_roundtrip`). Outlined text is never produced; text is either live or the
element is raster.

## Explicitly unsupported (returns `unsupported`, never ignored)

- Adapters: PDF/document, PSD/Figma/AI source, website/UI live capture, packaging/dielines, motion/timing, 3D.
  Workaround offered: export a still and scan it (layers, states, timing stay `unknown`).
- OCR (no integration): transcription is labelled `manual_observation`.
- Automatic segmentation: element boundaries are proposed by the operator and measured by the tools (assisted).
- Font identification beyond supplied candidate files; identity needs source evidence.
- Effects: bevel/emboss, inner shadow, outer glow, stroke align inside/outside, strokes on images/backgrounds/effect
  nodes, text-on-path, feathered asset masks, blend-if, 3D extrusion, perspective warps (matrix transforms only).
- Generated/inpainted assets inside the engine (supply the file; it is tracked as `generated`, never "recovered").
- Exact CMYK/print separations.
- A host persistent-storage adapter is not included; bundles + FilesystemBackend are (`references/storage.md`).

## Exports that cannot represent the master exactly

- SVG opened in design apps that ignore `@font-face` or SVG filters: text needs the font installed; filters may be
  rasterised or dropped. The manifest lists which elements are affected.
- JPEG: lossy, no alpha. PNG is the verified raster export.

## Adding an adapter

Add it behind the same evidence + scene contracts: an intake path that writes `source/` + evidence, a capability
line in `capabilities.py`, renderer support or an explicit `unsupported` validation entry, and at least one
acceptance test with retained inputs/outputs before calling it implemented.
