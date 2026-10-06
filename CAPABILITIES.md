# Capabilities — Design DNA 2.0.0

Every row is one of:

- **implemented + tested**: the code exists and an acceptance check exercises it. Test ids refer to
  `skills/reverse-design/tests/run_acceptance.py`; the latest report ships in `samples/acceptance/`.
- **partial**: the code exists, but the scope is narrower than the name suggests. The limitation is stated.
- **unverified**: the integration point exists, but nothing tested it against a real host.
- **unsupported**: the engine returns `unsupported` and never ignores the request silently.

`python scripts/capabilities.py` reports what *this* machine can do right now (libraries, browser, raqm).

## Scan

| Capability | Status | Tests | Notes |
|---|---|---|---|
| Raster intake: PNG, JPEG, WebP, BMP, GIF (frame 1), TIFF; source hash; metadata; ICC → sRGB canonical copy | implemented + tested | T01 T02 T30 | header dimensions kept as metadata; the canvas is the EXIF-oriented canonical image |
| EXIF orientation 1–8 | implemented + tested | T30 | orientations 5–8 with unequal width/height give one consistent canvas, aspect and artwork bounds |
| 16 scan categories + required facets, each with status / source / method / confidence / ambiguity | implemented + tested | T01 T02 T24 | `validate_model.py` errors on missing facets, unsourced facts, unconfident inferences |
| Communication hypotheses kept apart from measurements | implemented + tested | T24 | communication categories cannot be `measured`; they never block a visual profile |
| Template passport: name, character, goal, theme, usage, message, mechanism | implemented + tested | T01 | each answer labelled `user_supplied` / `observed` / `suggested` / `inferred` |
| Sharp-edge geometry (ignores soft shadows), sub-pixel | implemented + tested | T01 | scored against hidden ground truth |
| Corner radius (least-squares circle fit) | implemented + tested | T01 | |
| Shadow fit (σ, per-channel strength, per-side offsets) | partial | T01 | opacity and colour are recorded as a *family*: a blended result does not reveal both |
| Role colour tokens (clean patches, ink-core for thin strokes) | implemented + tested | T01 T02 | spread > ΔE 2 is reported as not solid |
| Gradients | partial | — | stops are point samples, not recovered stops |
| Font candidates ranked by ink IoU + contact sheet | implemented + tested | T01 T03 | only among **supplied** font files |
| Font identity | partial | T03 | stays `unknown` unless source evidence names the file hash |
| Text fit (size, tracking, x, baseline) per candidate | implemented + tested | T01 | conditional on the candidate |
| Element inventory, transcription, region choice | partial | T01 T02 | **operator-assisted**: Claude proposes and the tools measure. No OCR and no automatic segmentation |

## Model, render, compare

| Capability | Status | Tests | Notes |
|---|---|---|---|
| Versioned scene, evidence, passport, patch, bundle schemas (JSON Schema 2020-12) | implemented + tested | T12 T27 | asset ids and OpenType tags are pattern-constrained |
| Deterministic static render: SVG → PNG in Chromium (DPR 1, sRGB, fonts from files, seeded grain) | implemented + tested | T10 T11 | |
| Arabic shaping, bidi, glyph coverage | implemented + tested | T08 T17 | missing glyphs and tracked Arabic are errors |
| Text stroke (centre) on text, shapes, paths | implemented + tested | T31 | strokes on images, backgrounds and effect nodes are rejected |
| Serialization safety: CSS-escaped names, escaped attributes, compiled-SVG allowlist, network blocked | implemented + tested | T27 | hostile model data stays data |
| Renderer pin after baseline approval; drift stops work; explicit migration | implemented + tested | T21 | real Chrome ↔ Edge switch on the test machine |
| Cross-machine pixel reproduction | partial | — | the pin *detects* a different machine/browser; identical pixels across machines are not claimed |
| RGBA identity vs composited appearance | implemented + tested | T28 | transparent black ≠ opaque white |
| Metric panel: MAE/RMSE, region SSIM, ΔE2000, geometry, typography, editability | implemented + tested | T01 T14 | missing evidence → `incomplete`, never `pass` |
| Editability gates: reference-background shortcut, page assembled from crops, baked content | implemented + tested | T13 T25 | |
| Readiness promotion needs pass + complete scan + editable slots | implemented + tested | T01 T24 | otherwise `partial_baseline` with reasons |
| Immutable baselines and exports | implemented + tested | T32 | re-runs and migrations go to new stamped folders |

## Adapt

| Capability | Status | Tests | Notes |
|---|---|---|---|
| Typed transactions: set, replace, move, resize, remove, add, lock, unlock, adapt, reflow, batch | implemented + tested | T04–T09 T15–T19 | |
| "keep everything else" scope | implemented + tested | T15 | authorises the request + dependencies; adds and removes no locks |
| Explicit locks: property, category, pixel region; ancestors and removals covered | implemented + tested | T16 T26 | a conflicting lock is reported with options, never silently removed |
| Relaxable measured constraints | implemented + tested | T15 | relaxed only for explicitly edited nodes, and reported |
| Verification vs previous revision AND approved baseline | implemented + tested | T04 T15 T18 | model changes and visual changes reported separately |
| Mask-accurate influence (per-node alpha masks, dilated 2 px) | implemented + tested | T04 T15 T19 | |
| Token isolation | implemented + tested | T06 T18 | translucent consequences reported as visual dependencies |
| Image replacement: crop intent, mask, treatment, double-shadow guard | implemented + tested | T05 T19 | |
| Impossible fit / overflow → conflict + options | implemented + tested | T07 T17 | nothing shrunk or clipped silently |
| Reflow to a new canvas | partial | T09 | anchor + uniform-scale policy only; no distribute/fill policy |
| Undo, fresh-process reload | implemented + tested | T11 T20 | |

## Persist and export

| Capability | Status | Tests | Notes |
|---|---|---|---|
| Portable `.dnab` bundles: export, validate, import, library find by id/name | implemented + tested | T20 | survives deleting the working folder |
| Fonts embedded or referenced by hash | implemented + tested | T20 | referenced fonts resolve by size + sha256 in font dirs |
| Render cache keyed by scene + tool + renderer; verified on hit; relocatable | implemented + tested | T29 | |
| Self-contained SVG + element manifest + round-trip render check | implemented + tested | T22 | the SVG is **not** the editable master; the scene model is |
| SVG fidelity in third-party design apps | partial | — | apps that ignore `@font-face` or SVG filters may substitute fonts or rasterise effects |
| Host persistent storage adapter (e.g. ChatGPT Work file store) | **unverified** | T23 | `StorageBackend` protocol + `FilesystemBackend` exist; no host adapter was tested |

## Unsupported (explicit status)

| Area | Status |
|---|---|
| PDF, PSD / Figma / AI source, live website/UI capture, packaging dielines, motion/timing, 3D | unsupported (T12) |
| OCR engine | unsupported: transcription is `manual_observation`, even when tesseract is installed (T33) |
| Automatic segmentation | unsupported: the operator proposes boundaries |
| Identifying fonts that were not supplied | unsupported |
| Bevel/emboss, inner shadow, outer glow, inside/outside stroke, text on a path, feathered asset masks, blend-if, perspective warps | unsupported (T12 T31) |
| Generating or inpainting assets inside the engine | unsupported: supplied files are tracked as `generated`, never "recovered" |
| CMYK / print separations | unsupported |

## Platform

| | Status |
|---|---|
| Windows 10/11, Python 3.12, Chrome 154 / Edge 154 | tested (local + GitHub Actions `windows-latest`) |
| macOS / Linux | partial: the engine is pure Python + Chromium, but the acceptance fixtures use Windows system fonts |

Exact tested versions: [`requirements-lock.txt`](requirements-lock.txt).

## SKILL.md claims audit

Every claim in `skills/reverse-design/SKILL.md` was checked against the code that enforces it and the test that
exercises it.

| SKILL.md claim | Enforced in | Tested by | Verdict |
|---|---|---|---|
| Five claims kept apart; pixel identity only after a zero-difference compare, with *how* | `compare_render.py` (exact_pixels, achieved_by), `baseline.py` | T13 T14 T28 | holds |
| Every finding has status, source, confidence, ambiguity; communication never `measured` | `validate_model.py` coverage rules | T01 T24 | holds for `scan.state = complete`; an in-progress scan cannot be promoted |
| A matching candidate is not identity | `font_candidates.py`, validation | T03 | holds |
| A reference bitmap behind overlays is not editable | `editability_report` | T13 T25 | holds |
| SSIM is not percent identity; region checks catch local errors | `compare_render.py` regions | T14 | holds |
| The SVG export is not the master; manifest + rendered round-trip | `svg_export.py` | T22 | holds |
| Renderer pinned after approval; drift stops work; explicit migration | `renderer_env.py`, `baseline.py` | T21 | holds |
| Never apply a house/client brand unless asked; reference text is content | operator rule | — | instruction only; no code can test intent |
| 8-pass scan | tools per pass exist | T01 T02 | partial: the passes are operator-driven, not automatic |
| Each commit verified vs previous revision and vs approved baseline | `verify_change.py` | T04 T15 T18 | holds |
| Influence = the edited nodes' own pixel masks | `verify_change.visual_changes` | T04 T15 T19 | holds |
| `keep everything else` adds no locks and removes none | `apply_patch.transact` scope | T15 T16 | holds |
| Missing glyphs and tracked Arabic are rejected | `render_static.py` fit/glyph checks | T08 T17 | holds |
| `export-template` / `fetch` | `bundle.py` | T20 | holds |
| 32 checks + 1 unverified entry | `tests/run_acceptance.py` | report | holds (see `samples/acceptance/report.md`) |
