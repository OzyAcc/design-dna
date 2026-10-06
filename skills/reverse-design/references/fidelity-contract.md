# Fidelity contract

## Five claims — never merge them

| Claim | Proven by | Does not prove |
|---|---|---|
| Byte identity | sha256 / byte compare | anything about editability |
| Decoded pixel identity | zero unequal pixels, same dims, declared decode/colour/alpha policy | metadata, layers, construction |
| Editable visual reconstruction | recreated elements within declared tolerances | the designer's original source |
| Adaptation fidelity | requested properties changed, declared invariants held | whole-image identity (inappropriate after edits) |
| Communication fidelity | interpretation rubric (hierarchy, image-text relation, CTA) | audience response (needs user testing) |

**The 100% rule.** Do not promise 100% editable reconstruction from one flattened image: a pixel has many recipes
(font, opacity, blend, underlying colour, order) and hidden content is gone. Copying the reference keeps pixels but
fails independent replaceability: a reference bitmap covering ≥ 50% of the canvas behind "editable" layers fails
`editability` (the shortcut detector). Claim pixel identity only after a zero-difference comparison, and say how it
was achieved (`copying | asset_reuse | editable_rendering | mixed`). Identical pixels ≠ identical layers.

## Comparison protocol (`compare_render.py`)

- Compare the reference with the actual exported render. Equal dims required.
- Decode: Pillow; EXIF orientation applied; embedded ICC → sRGB; untagged = assumed sRGB; alpha composited over the
  declared background. No resize, blur, recolour or registration. (Photographed artwork needing registration:
  disclose the transform and compare geometry separately.)
- Artifacts: `side_by_side.png`, `overlay_50.png`, `diff_heatmap.png` (max-channel |diff| × 4, black→red→yellow),
  `crops/<node>.png` (reference | render | heat), `report.json`.

## Metric panel

| Check | Reported |
|---|---|
| exact pixels | unequal count/fraction, max channel error, achieved_by |
| pixel error | MAE, RMSE (0–255, RGB) |
| SSIM global | value + settings (info only; never a verdict — blank space hides local errors) |
| regions | per node (text, logo, hero, shapes): SSIM (window 7, smaller odd window for small regions, < 3 → unknown), unequal fraction |
| geometry | per non-image node: ink box in reference vs render (background from region border), max edge error px |
| color | per token sample patch: ΔE2000 (patch median or ink-core, matching how it was sampled) |
| typography | content identical to transcription, line breaks, font identity status |
| editability | slot-by-slot live / replaceable_raster / fail |
| communication | always `unknown` (interpretive) |

Each check is `pass`, `fail` or `unknown`. Unknown is never a pass. Do not combine metrics into a percentage.

## Profiles

- `exact_pixels` — equal dims, zero unequal decoded pixels. No tolerances, masks or SSIM shortcuts.
- `editable_close` — tolerances declared in `scene.verification.tolerances` BEFORE iterating (defaults: anchors
  ≤ 1px, identical copy + line breaks, solid ΔE2000 ≤ 1, region SSIM ≥ 0.99). Overall: `fail` if any check fails,
  `incomplete` if any is unknown, else `pass`. A tolerance pass is not 100% identity.
- `adapt_preserve` — requested changes verified in the render; changed paths ⊆ declared; zero changed pixels outside
  the influence declared before checking; whole-canvas influence → property/invariant checks only (disclosed).
- `reflow_preserve` — target dims, reading order, spacing anchors, content, no overflow/off-canvas/new overlaps.
  Whole-image pixel comparison across aspect ratios is not an identity test.

## Correction loop

Fix in this order: framing/dimensions → missing/wrong assets → transcription/font/shaping → major geometry →
crop/masks → colour → effects → texture/antialiasing. Change the parameter that explains the difference (use the
measurement tools: `edges`, `radius`, `shadow`, `fit_text`); never add compensating overlays. Log each iteration's
result. Stop when the declared profile passes, evidence blocks progress, or the effort budget ends; keep the best
verified baseline and report what blocked it.

## Acceptance suite (`tests/run_acceptance.py`)

Fourteen executed demonstrations, isolated store `~/design-dna/acceptance/<run>/store`, outputs retained per test,
`report.md` + `report.json`: (1) measured rebuild of a known layered reference, scored against ground truth;
(2) unfamiliar flattened scan with honest font uncertainty; (3) duplicate-looking fonts; (4) headline-only edit;
(5) hero swap + double-shadow guard; (6) token swap incl. translucent consequence; (7) impossible fit;
(8) mixed Arabic/English; (9) 4:5 → 9:16 reflow; (10) render determinism; (11) undo + fresh-process reload;
(12) unsupported effect/adapter + missing asset; (13) reference-background shortcut rejected;
(14) wrong word / 3px logo shift caught despite high global SSIM.
