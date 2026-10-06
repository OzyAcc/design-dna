# Scan contract

Every category gets a result: `observed`, `measured`, `inferred`, `unknown` or `not_applicable`, stored in
`scene.scan.coverage.<category>` with a note, evidence ids, a confidence and `ambiguity` (unresolved alternatives).
A skipped category is not a pass. When `scan.state = complete`, `validate_model.py` **errors** on:

- a missing category, or a missing required **facet** (below) unless the category is `not_applicable`;
- an `observed`/`measured` finding with no evidence id (every fact needs a source);
- an `inferred` finding with no confidence;
- a communication category (`hierarchy_attention`, `message_mechanism`, `character_theme`, `usage_context`)
  marked `measured`. Visual measurements and communication hypotheses stay separate.

Required facets (each `{status, note, evidence_ids, confidence, ambiguity}`):

| Category | Facets |
|---|---|
| composition | grid, spacing, alignment, whitespace |
| geometry | position_size, radii_strokes, transforms |
| typography | text, font_candidates, font_identity, size_line_height, tracking, baselines_alignment, direction |
| color | role_tokens, gradients, opacity_blending |
| image_treatment | images, crop_intent, masks, treatment |
| depth_compositing | layering, shadows, blend_modes |
| surface_texture | textures |
| message_mechanism | message_delivery |

`font_identity` stays `unknown` unless source evidence names the file hash, because a matching candidate is not
proof of identity. The template passport must also answer name, character, goal, theme, suitable uses, message and
how the design delivers that message. Each answer is labelled `user_supplied`, `observed`, `suggested` or
`inferred`, and `validate_model.py` reports any gaps.

## Contents
1. Categories and tools
2. Coordinate contract
3. Color contract
4. Typography contract
5. Image, depth, texture contract
6. Communication contract
7. Evidence records

## 1. Categories and tools

| Category (`coverage` key) | Capture | Tool / method |
|---|---|---|
| `input_canvas` | size, aspect, format, alpha, ICC, orientation, framing, compression | `inspect_source.py` (automatic) |
| `composition` | zones, margins, grid, gutters, alignment axes, whitespace, overlaps | `measure.py profile` (bands/gaps), `measure.py edges` |
| `element_inventory` | every meaningful element, its group, role, stable id | Claude vision proposes; nodes in `scene.nodes` |
| `geometry` | position, size, rotation, radius, stroke, clipping | `measure.py ink` (flat ground), `measure.py edges` (shadowed/gradient ground), `measure.py radius` |
| `color` | role tokens, gradients, opacity | `sample_colors.py --sample / --ink-core / --gradient` |
| `typography` | exact text, family candidates, size, line height, tracking, baselines, alignment | transcription (manual_observation, no OCR here), `font_candidates.py`, `fit_text.py` |
| `image_treatment` | asset, crop, focal, fit, mask, grading | supplied original + model fit, or bounded reference crop with treatment `unknown` |
| `depth_compositing` | order, occlusion, opacity, blend, shadows | `measure.py shadow` (joint probe fit); opacity/colour as a family |
| `surface_texture` | paper, grain, halftone, baked texture | crops at enlargement; seeded `grain` effect node if editable |
| `lighting` | light direction, contact/cast shadows, highlights | inference from shadow offsets; label as inference |
| `hierarchy_attention` | likely first/second focal point, reading order | inference tied to visible evidence; never eye-tracking |
| `message_mechanism` | literal message, takeaway, promise, CTA, image-text relation | communication chains (section 6) |
| `character_theme` | editorial / premium / playful… with concrete evidence | inference; no unsupported adjectives |
| `usage_context` | format, channel, campaign stage, suitable/unsuitable uses | user brief first; otherwise `inferred` |
| `responsive_system` | variants, states, breakpoints, timing | a single still → `unknown` (set automatically) |
| `output_requirements` | target size, DPR, color space, export format, print | from the brief; missing → `unknown` with a probe |

Scan order: (1) metadata + artwork bounds; (2) composition + inventory; (3) text + typography; (4) role colors +
surfaces; (5) images, crops, masks, treatment; (6) layering, depth, lighting, effects; (7) hierarchy, message,
character, usage; (8) cross-check: render, compare, inspect region crops, fix the explaining parameter.

## 2. Coordinate contract

- Top-left origin, x right, y down, canvas pixels as canonical geometry; floats until rasterisation.
- `geometry` is canvas-space, pre-transform, layout bounds unless `bounds` says `ink`/`rendered`; `includes_stroke` explicit.
- Text: `geometry` = layout box; `first_baseline` + `line_height` place lines; ink bounds live in evidence.
- Paths store `d` in local units with `path_box`; transforms as `rotation` or a 6-value `transform` matrix.
- Measure relationships, not only boxes: `constraints` (`gap`, `anchor`, `equal`, `ratio`, `range`) between
  `<node>.<edge>` and `canvas.<edge>`; record optical adjustments as notes.
- Proportions (`x/W`…) are derivable; `reflow` uses anchors + uniform scale `min(W2/W, H2/H)`.

## 3. Color contract

- Source profile preserved; `source/canonical.png` is the separately identified sRGB comparison copy (conversion
  string stored). Untagged = "assumed sRGB" (inferred), never silently stripped.
- Tokens are named by role (`background.paper`, `text.primary`, `accent.primary`, `cta.fill`), store value + `space`
  + sample boxes + method (`patch_median` or `ink_core`) + evidence ids. Never use a global histogram.
- Sample several clean interior patches per role (inset 2px). Spread > ΔE 2 or std > 8 = not a solid token.
- Thin strokes (text): `--ink-core` (stroke cores vs a ring background just outside the box).
- A blended result does not reveal underlying colour + opacity: store the family (see shadows) and the hypothesis.
- Gradients: structured stops from point samples (`--gradient`); stop positions are samples, not recovered stops.
- Print intent (CMYK) is out of scope for screen references.

## 4. Typography contract

- Exact Unicode text, punctuation, case, explicit `\n` line breaks, direction. OCR is unavailable here: transcription
  is `manual_observation` by Claude vision and stays a candidate.
- Look for source metadata / font files first. `font_candidates.py` ranks supplied files by ink-mask IoU and writes a
  contact sheet; ties (< 0.01) are reported. `identity.status` stays `unknown` unless a `source_extraction` evidence
  record names the file hash (then `verified`). A convincing look is still a candidate.
- `fit_text.py` fits size / tracking / x / baseline per candidate with the production renderer (ink-moment seed for
  tracked text, coordinate descent + Nelder-Mead). Fits are conditional on the candidate.
- Size ≠ ink height. Cap height, x-height, glyph widths, baselines and line spacing constrain the fit.
- Record synthetic bold/italic or horizontal scaling only when observed; the renderer sets `font-synthesis:none`
  unless declared. Never stretch a substitute to hide a mismatch.
- Outlined/raster lettering → `editability: outlined|raster`, not live text.
- Arabic: shaping and bidi come from Chromium/HarfBuzz; never reverse strings; tracking on Arabic is an error;
  glyph coverage is checked against the pinned font file (missing glyphs = error, no silent fallback).

## 5. Image, depth, texture contract

- Separate content asset / placement (`fit`, `focal`, `scale`, `crop`) / treatment (ordered ops) / mask / effects.
- Assets are content-hashed (`assets/<sha16>.<ext>`), immutable, with provenance: `supplied`, `reference_crop`
  (+ `derived_from` box), `generated`, `synthetic_fixture`, `system_font`, `source_extraction`.
- Treatment order matters (tint→contrast ≠ contrast→tint); supported ops: grayscale, saturate, contrast,
  brightness, hue_rotate, tint, blur.
- Each shadow is its own effect: offset, blur (σ px), spread, colour, opacity, blend, receiver.
  `measure.py shadow` fits σ, per-channel strength and per-side offsets; opacity/colour are a family
  (`a ≥ max(A)`, `c = 255(1 − A/a)`); normal vs multiply is indistinguishable on uniform ground.
- Baked shadows live in `asset.baked_effects`; replacing an asset with a baked shadow while a live shadow is enabled
  is a `double_shadow` conflict.
- Masks: `rect` (radius), `ellipse`, `path`, `asset` (alpha/luminance); `feather` for shape masks.
- Hidden pixels behind text or cutouts are unknown. Generated/inpainted fills are synthesized assets, never recovered.
- A single view of 3D/lighting is cue-level inference only.

## 6. Communication contract

Each mechanism is a 4-step chain stored in `communication.mechanisms[].chain`:
`visible choice → likely attention/association → intended takeaway → intended action`, with status (usually
`inferred`), confidence, evidence ids and `competing` readings. Also: `goal`, `literal_message`, `takeaway`,
`cta`, `word_image_relationship` (demonstration, metaphor, contrast, evidence, atmosphere, decoration), each a
claim `{value, status, confidence, evidence_ids, supplied_by_user}`. Keep the reference's original message apart
from the new task's goal: new copy on an old metaphor can say the wrong thing. Never claim conversion, audience
demographics, designer intent, eye movement or emotion as fact.

## 7. Evidence records

`evidence/evidence.json` (schema `evidence.schema.json`): `evidence_id`, `source_sha256`, region, object, method
(`direct_metadata | pixel_sampling | ocr | manual_observation | source_extraction | candidate_render_comparison |
inference | computed_measurement`), tool + version, value, units, uncertainty, status, confidence (+ justification;
labels are not calibrated probabilities), alternatives, limitations, resolving probe, artifacts. Re-measuring with
the same id supersedes. Properties reference evidence via `node.provenance["<prop>"]` and token `evidence_ids`;
a referenced id that does not exist is a validation error.
