# Fidelity contract

## Five claims — never merge them

| Claim | Proven by | Does not prove |
|---|---|---|
| Byte identity | sha256 / byte compare | anything about editability |
| Decoded pixel identity | zero unequal **RGBA** pixels, same dims, declared decode/colour policy (no matte) | metadata, layers, construction |
| Editable visual reconstruction | recreated elements within declared tolerances, complete scan, every slot independently editable | the designer's original source |
| Adaptation fidelity | requested properties changed (probed in pixels), every other property and pixel preserved against the approved baseline | whole-image identity (inappropriate after edits) |
| Communication fidelity | interpretation rubric (hierarchy, image-text relation, CTA) | audience response (needs user testing) |

**The 100% rule.** Do not promise 100% editable reconstruction from one flattened image: a pixel has many recipes
(font, opacity, blend, underlying colour, order) and hidden content is gone. Copying the reference keeps pixels but
fails independent replaceability. `editability_report` fails a template when a reference-derived raster covers ≥ 50%
of the canvas, when reference crops together cover ≥ 90% (a page assembled from fragments), or when a crop contains
more than 25% of another element's box (content baked in). An empty inventory or no slots is `incomplete`, never a
pass. Claim pixel identity only after a zero-difference comparison, and say how it was achieved
(`copying | asset_reuse | editable_rendering | mixed`). Identical pixels ≠ identical layers.

## Comparison protocol (`compare_render.py`)

- Compare the reference with the actual exported render. Equal dims required.
- Decode: Pillow; EXIF orientation applied; embedded ICC → sRGB; untagged = assumed sRGB.
  **Identity** uses decoded RGBA (alpha is data). **Appearance** (SSIM, MAE/RMSE, ΔE, crops) composites over the
  declared background and is reported separately as `appearance` — a transparent black pixel is not "identical" to
  an opaque white one, even though they look the same over white.
- No resize, blur, recolour or registration. (Photographed artwork needing registration: disclose the transform and
  compare geometry separately.)
- Artifacts: `side_by_side.png`, `overlay_50.png`, `diff_heatmap.png` (max-channel |diff| × 4, black→red→yellow),
  `crops/<node>.png` (reference | render | heat), `report.json`.

## Metric panel

| Check | Reported |
|---|---|
| exact_pixels | decoded RGBA: unequal count/fraction, max channel error, achieved_by |
| appearance | the same over the declared matte (info) |
| pixel error | MAE, RMSE (0–255, appearance) |
| SSIM global | value + settings (info only; never a verdict — blank space hides local errors) |
| regions | per element: SSIM (window 7, smaller odd window for small regions, < 3 → unknown), unequal fraction; an element without a rendered footprint is `unknown` |
| geometry | per non-image element: ink box in reference vs render, max edge error px |
| color | per token sample patch: ΔE2000 (patch median or ink-core, matching how it was sampled) |
| typography | content identical to transcription, line breaks, font identity status |
| editability | slot by slot: live / replaceable_raster / fail; overall pass / partial / fail / incomplete |
| communication | always `unknown` (interpretive) — it never blocks a visual profile |

Each check is `pass`, `fail` or `unknown`. Unknown is never a pass; missing evidence (no compared regions, no colour
samples, no transcription, incomplete editability) makes a profile `incomplete`. Do not combine metrics into a
percentage.

## Profiles

- `exact_pixels` — equal dims, zero unequal decoded RGBA pixels. No tolerances, masks or SSIM shortcuts.
- `editable_close` — tolerances declared in `scene.verification.tolerances` BEFORE iterating (defaults: anchors
  ≤ 1 px, identical copy + line breaks, solid ΔE2000 ≤ 1, region SSIM ≥ 0.99). `fail` if any check fails,
  `incomplete` if any required evidence is missing, else `pass`. A tolerance pass is not 100% identity.
- `adapt_preserve` — requested changes probed in the render; model changes ⊆ the authorised set; zero changed RGBA
  pixels outside the influence (union of the edited elements' own alpha masks before + after, dilated 2 px, declared
  before comparing). Checked against the previous revision AND cumulatively against the **approved template
  baseline image**; the pinned re-render of the approved baseline must reproduce it. A background edit = whole-canvas
  influence → property/invariant checks only (disclosed). Pixel locks: 0 changed pixels in each locked region.
- `reflow_preserve` — target dims, reading order, spacing anchors, content, no overflow/off-canvas/new overlaps.
  Whole-image pixel comparison across aspect ratios is not an identity test.
- `svg_roundtrip` — the exported SVG file rendered on its own equals the engine PNG (decoded pixels), every live
  text element equals the model text, every raster node is embedded.

## Readiness (template passport)

`exact_pixels` / `editable_close` are granted only when the profile passes **and** the scan is complete **and**
editability passes. Anything else is `partial_baseline` with the reasons written to `unresolved`. The first
reconstruct of a model approves its baseline and pins the renderer; later runs prove reproducibility into new
folders; nothing approved is overwritten. A renderer change needs `migrate-baseline … confirm preview=<id>`, bound to
the exact reviewed candidate. A pin recorded before a hard field existed is drift, not a match.

## Correction loop

Fix in this order: framing/dimensions → missing/wrong assets → transcription/font/shaping → major geometry →
crop/masks → colour → effects → texture/antialiasing. Change the parameter that explains the difference (use the
measurement tools: `edges`, `radius`, `shadow`, `fit_text`); never add compensating overlays. Iterations are
operator-driven; each tool call records its evidence. Stop when the declared profile passes, evidence blocks
progress, or the effort budget ends; keep the best verified baseline and report what blocked it.

## Acceptance suite (`tests/run_acceptance.py`)

Isolated store per run, outputs retained per test, `report.md` + `report.json`, results grouped by kind:

- **1–14 (v1):** measured rebuild scored against ground truth; unfamiliar flattened scan; duplicate fonts;
  headline-only edit; hero swap + double shadow; token swap; impossible fit; Arabic; reflow; determinism; undo +
  fresh-process reload; unsupported effect/adapter/missing asset; reference-background shortcut; small errors.
- **15–22 (v2):** keep everything else; conflicting explicit lock + pixel locks; overflow + Arabic shaping and
  missing glyphs; token isolation; image replacement handling; bundle round-trip after removing the working folder;
  renderer drift + migration; exported SVG rendered and checked.
- **23:** host persistent storage adapter — UNVERIFIED.
- **24–33:** regressions for every finding of the 2026-10-06 audit (`docs/AUDIT-RESPONSE.md`).
- **34–37:** regressions for the dashboard build audit: legacy pins need a decision (A1), migration confirmation is
  bound to the reviewed preview (A3), repeated fresh-process renders are identical (A2), hidden nodes don't break
  isolated-bounds checks.
