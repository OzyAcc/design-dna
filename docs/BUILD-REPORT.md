# Design DNA — build report

**Version 1.0.0 · 6 October 2026 · status: 14/14 acceptance demonstrations passing (Chrome 154, Windows 10)**

This report records what was built from the Design DNA specification ([SPEC.md](SPEC.md)), how it was verified,
what broke during verification and how it was fixed, and what remains unsupported. It is written for people who
want to trust — or challenge — the engine's claims.

## Contents

1. Summary
2. What was built
3. How it was verified
4. Results
5. Engineering log: failures found by acceptance and their fixes
6. Specification compliance
7. Known limitations
8. Reproducing everything

---

## 1. Summary

Design DNA turns a visual reference into an **evidence-backed, editable, persistent template**, rebuilds it with a
deterministic renderer, compares the rebuild with the reference region by region, and applies later edits as
verified transactions. Every stored value carries a status (`observed | measured | inferred | unknown |
not_applicable`) and points at the evidence that produced it.

The headline result: given only a flattened image of a layered poster, the engine recovered its frames, text
baselines, font sizes, letter tracking, drop-shadow offset and blur, photo grading and a translucent overlay to
**sub-pixel / sub-percent accuracy**, while still refusing to claim the font's identity — and the rebuild passed the
`editable_close` pixel profile.

## 2. What was built

### Skill and packaging
| Item | Purpose |
|---|---|
| `skills/reverse-design/SKILL.md` | triggers, non-negotiable honesty rules, workflow A–F, request → command examples |
| `references/` (5 contracts) | scan, scene model, commands, fidelity, adapters — loaded on demand |
| `schemas/` (4 JSON Schemas 2020-12) | scene, evidence, template passport, typed patch |
| `.claude-plugin/` | plugin + marketplace manifests (validated with `claude plugin validate`) |
| `install.ps1`, `install.sh` | copy the skill, install dependencies, print a capability report (existing installs are moved aside, never deleted) |

### Engine (`skills/reverse-design/scripts/`)
| Script | Responsibility |
|---|---|
| `common.py` | store layout, hashing, atomic JSON writes, immutable content-addressed files, evidence store, property addressing (`headline.content`, `tokens.accent.primary`, `hero.effects.cast_shadow.opacity`) |
| `inspect_source.py` | intake: preserve source bytes + hash, metadata (ICC, EXIF, JPEG subsampling), canonical sRGB copy, framing hypothesis, skeleton template + passport; explicit `unsupported_adapter` for PDF/PSD/UI/motion |
| `measure.py` | ink bounds + baselines, projection profiles (grids/gutters), **sharp-edge scanlines** (immune to soft shadows), **least-squares corner radius**, **joint multi-probe shadow fit** (σ, per-channel strength, per-side offsets, opacity/colour family) |
| `sample_colors.py` | role tokens from inset patches, `--ink-core` for thin text strokes, `--gradient` stops; refuses to call textured regions solid |
| `font_candidates.py` | ranks supplied font files by ink IoU, flags ties, writes a contact sheet, estimates size from ink height and width; identity only verified by source evidence naming the file hash |
| `fit_text.py` | render-fits size / tracking / x / baseline per candidate: ink-moment seeding (glyph spread → size, centroids → origin + tracking), coordinate descent, Nelder–Mead for coupled parameters |
| `validate_model.py` | JSON Schema + semantics: tree integrity, token/evidence/asset references, hashes, glyph coverage, Arabic tracking, unsupported features, **reference-background shortcut detector** |
| `render_static.py` | scene → SVG master → PNG in pinned Chromium (Chrome → Edge → bundled Chromium): fonts from files, `font-synthesis:none`, DPR 1, sRGB, fitted text policies, per-node isolated bounds |
| `compare_render.py` | metric panel: exact pixels, MAE/RMSE, SSIM (global info + per region), geometry by ink boxes, ΔE2000 per token sample, content vs transcription, editability; heatmap, overlay, side-by-side, region crops |
| `ops.py` | typed operations (set, replace, move, resize, remove, add, lock, unlock, adapt, reflow) with explicit dependency records, lock coverage, constraint evaluation |
| `apply_patch.py` | transactions: base-revision guard → ops → locks → constraints → validation → render + verify (`adapt_preserve` / `reflow_preserve`) → immutable revision; undo; export |
| `dna.py` | the formal command language (21 commands + batch/status), session state, replayable scripts |
| `index_templates.py` | index, `list`, `find`, exact load by name/alias/id from disk |
| `annotate_scan.py` | annotated reference (ids, baselines, uncertainty markers, palette) + coverage report |
| `capabilities.py` | what this machine can actually do (libraries, renderer, OCR, shaping) |

### Acceptance suite (`skills/reverse-design/tests/`)
Deterministic fixtures (procedural product photos, a vector logo, a known layered poster, a flattened 6-up JPEG
grid drawn by a different rasterizer), the 14 demonstrations, per-test evidence folders and a Markdown/JSON report.

## 3. How it was verified

- Every demonstration runs for real in an isolated template store and keeps its inputs and outputs.
- Demonstrations 1 and 2 are **operator-assisted scans**: the operator (Claude) proposes coarse regions and reads
  captions; every number is produced by the measurement tools and stored as evidence first. Ground truth (where it
  exists) is read only at the end, to score the result.
- Reference and rebuild are compared as decoded pixels under a declared policy (no resizing, blurring or alignment).
- The suite runs on Windows in CI (lint + schema check on Ubuntu).

## 4. Results

Final run `20261006-205635`: **14/14 passed**, renderer Chrome 154.0.8037.93, Python 3.12, Windows 10.

### Demonstration 1 — measured rebuild of a known layered reference (scored against hidden ground truth)

| Parameter recovered from pixels | Error vs ground truth |
|---|---|
| accent bar, hero frame, CTA pill, logo geometry | 0 px |
| translucent sheen (circle fit) | 0.46 px |
| text x / baselines | ≤ 0.04 px / ≤ 0.26 px |
| font size (label / headline / CTA) | 0.30 % / 0.01 % / 0.06 % |
| letter tracking (label) | 0.05 px |
| line height | 0.29 px |
| corner radius | 0.4 px |
| drop shadow offset / blur σ / spread | 0.7 px / 0.93 px / 0.24 px |
| shadow strength vs the true opacity·colour family | 0.005 |
| photo grading: saturate / contrast | 0.009 / 0.005 |
| sheen opacity (white assumed) | 0.005 |
| best font candidates | Arial Bold, Georgia Bold, Arial Bold — the true faces; identity still reported `unknown` |
| pixel verdict | `editable_close` **pass** (communication: `unknown`, interpretive) |

### Demonstration 2 — unfamiliar flattened JPEG (drawn by a different rasterizer, font not among candidates)

- Grid recovered: columns 40 / 381 / 721, rows 105 / 552, frame 319 px (max error vs truth **1 px**); caption
  baselines within **0.09 px**; radius 9.4 px (truth 8 px, tolerance 2 px).
- Best substitute font: Tahoma Bold; identity `unknown`. All six caption regions **fail** and are reported as such;
  photos pass (region SSIM ≥ 0.99); readiness `partial_baseline` with the reasons in `unresolved`.

### Demonstrations 3–14 (key evidence)

| # | Evidence |
|---|---|
| 3 | Arial Bold and a byte-different, glyph-identical duplicate tie; identity `unknown` until a `source_extraction` record names the Arial Bold hash → `verified: Arial Bold` |
| 4 | Headline-only edit: **0** changed pixels outside the declared influence (9.1 % of the canvas); only `nodes.n-headline.content` changed in the model |
| 5 | Hero swap keeps treatment, focal anchor, mask and shadow; a cutout with a baked shadow is rejected (`double_shadow`) until the editable shadow is disabled in the same transaction |
| 6 | Accent token → `#FFD400`: bound uses = accent bar + CTA pill; **0** pixels outside them changed; the translucent sheen is reported as a compositing consequence; the photo's yellow clasp untouched |
| 7 | Overlong headline under `strict` fit: rejected with four options; head revision unchanged |
| 8 | Arabic + English headline: a font without Arabic glyphs is rejected; with a capable font, shaping verified (joined 192.5 px vs ZWNJ-separated 254.2 px), bidi verified (`!` renders at x 574 left of the first Arabic letter at x 935), `direction=rtl`, alignment mirrored |
| 9 | 4:5 → 9:16: reading order preserved, nothing off-canvas, no new overlaps, all text fits |
| 10 | Same model rendered twice incl. seeded grain: **0** unequal pixels; PNG bytes identical too |
| 11 | Undo restores the byte-identical revision file; a fresh process finds the template by name and re-renders it pixel-identically |
| 12 | `bevel_emboss`, `film_burn`, an unknown asset id, a missing asset file and a PDF input all return explicit statuses; the renderer refuses rather than rendering without them |
| 13 | Full-reference background + invisible live text: pixels can match, but editability fails and readiness never reaches `editable_close` |
| 14 | `SALE → SOLE` at global SSIM 0.9994 and a 3 px logo shift at 0.9987: both **fail** on region, content and geometry checks |

## 5. Engineering log: failures found by acceptance and their fixes

Acceptance tests were written before being trusted; most of them failed at least once. The failures were real
defects, and each fix made the engine more honest or more accurate:

| Symptom | Root cause | Fix |
|---|---|---|
| Frame of a photo on a shadowed ground measured 34 px too large | threshold bounds counted the soft drop shadow as part of the frame | `measure.py edges`: sharp-step scanlines with sub-pixel boundaries; soft gradients never register |
| Translucent sheen's top edge wrong | same: the hero shadow darkened the ground above the threshold | least-squares circle through sharp boundary points |
| Corner radius read 26 px instead of 32 | counting rows until the edge looks straight under-reads by ≈ √R | least-squares fit of the per-row inset to a circle |
| Shadow parameters unstable from one profile | offset, blur and strength trade off when only the tail is visible | joint fit across four probes with shared σ and strength; opacity/colour reported as a family |
| Label size 2.8 % off, tracking 0.6 px off, fit stuck | size and tracking form a ridge that one-parameter moves cannot follow | Nelder–Mead stage after coordinate descent |
| Seeds from glyph edges 4 % small | thresholded edges clip the faint extremes of round/diagonal glyphs | seed from **ink-mass moments** (antialiasing preserves mass) against outline area moments (fontTools `StatisticsPen`) |
| Wrong serif candidate (Constantia) beat the true face | crude initial sizes put the true face in a worse local minimum | per-candidate seeding from its own ink-width size estimate |
| Text colour sampled as white | tight ink boxes are > 50 % ink, so "border = background" failed | ink-core sampler with a background ring just outside the box (shared by sampler and comparer) |
| Colour check failed on correct text | comparison used patch medians for tokens sampled as ink cores | tokens record `sample_method`; comparison uses the same method |
| Light photos on white lost 38 px of frame | profile threshold (40) above the photo/ground contrast | grid profiles use a sensitive threshold (10) |
| Reflow "broke" reading order | 20 px row buckets split a row after translation | rows grouped by vertical overlap; decorative layers excluded |
| Arabic adaptation flagged as drift | re-importing an existing font rewrote its provenance | same content hash = same asset record |
| Reflow flagged as drift | `22` vs `22.0` counted as a change | numeric comparison in the diff |
| Operator scan lost colour tokens | stale in-memory scene saved over tokens written by the sampler | reload before authoring |
| Intermittent "Unable to capture screenshot" | headless Chromium capture flake | bounded retry around screenshots |
| A planned undo test edit was rejected | the hard `layout` lock from the previous test covered it | correct behaviour; the test was changed, not the lock |

## 6. Specification compliance

| Spec section | Status | Notes |
|---|---|---|
| 1 Product contract, five claims, 100 % rule | Implemented | claims kept separate in reports; pixel identity reports how it was achieved |
| 2 Scan categories (16) | Implemented | every category gets a status; coverage enforced when a scan is marked complete |
| 2 Coordinate contract | Implemented | top-left canvas px, floats, layout vs ink vs rendered bounds, relationships as constraints; normalised proportions are derived on demand (reflow) rather than stored |
| 2 Colour contract | Implemented | role tokens with samples and method; blended colour/opacity as a family; CMYK out of scope |
| 2 Typography contract | Implemented / partial | candidates, contact sheets, render fits, glyph coverage, Arabic shaping; **no OCR engine** (transcription is labelled manual observation) |
| 2 Image, depth, texture | Implemented / partial | asset/placement/treatment/mask/effects separated, baked-shadow guard; 3D is cue-level inference only |
| 2 Communication contract | Implemented | four-step chains with status, competing readings |
| 3 Evidence, scene model, passport, index | Implemented | variants stored as directories of immutable revisions rather than an inline `variants` array |
| 4 Workflow A–F | Implemented | segmentation is assisted (Claude proposes, tools measure) |
| 5 Commands + mandatory edit behaviour | Implemented / partial | all commands; property locks enforced; **pixel-region locks exist in the schema but are not enforced yet** — pixel preservation is verified through the declared influence region |
| 6 Reconstruction and rendering | Implemented for static flat graphics | other adapters return `unsupported`; generation/inpainting is not part of the engine |
| 7 Verification and acceptance | Implemented | metric panel, four profiles, 14 demonstrations; the correction loop is operator-driven (iterations recorded in measurement logs) |
| 8 Architecture | Implemented | schema version 1.0.0 (no migrations needed yet), stable ids, immutable baselines, content-hashed assets, atomic saves, base-revision guard, undo, injection-safe data handling |

## 7. Known limitations

- **Adapters:** static raster only. PDF, layered sources (PSD/Figma/AI), live UI, motion, packaging and 3D are
  explicitly unsupported.
- **OCR and segmentation** are not automated; they are assisted and labelled.
- **Font identity** cannot be established from pixels; the engine ranks supplied candidates and stays `unknown`
  without source evidence. When the true font is not available, caption regions honestly fail (seen on a real
  client JPEG during development: photos matched exactly, captions failed with the best substitute at IoU 0.67;
  that client material is not part of this repository).
- **Reflow** anchors groups to edges and scales uniformly; tall formats can leave wide empty bands that need a
  design decision.
- **Pixel-region locks** are declared but not enforced as separate checks.
- **Platform:** verified on Windows with Chrome/Edge; the acceptance suite uses Windows system fonts.

## 8. Reproducing everything

```bash
python -m pip install -r requirements.txt
python skills/reverse-design/scripts/capabilities.py
python skills/reverse-design/tests/run_acceptance.py          # writes ~/design-dna/acceptance/<run>/report.md
python docs/tools/make_images.py ~/design-dna/acceptance/<run>   # regenerates the README images
```
