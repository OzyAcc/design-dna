# Design DNA — build report

**Version 2.0.0 · 6 October 2026 · status: 32/32 acceptance checks passing, 1 unverified (Chrome 154 / Edge 154, Windows 10)**

Sections 3–8 describe the 1.0.0 build. Section 2 records what 2.0.0 changed, why, and how it was verified.

This report records what was built from the Design DNA specification ([SPEC.md](SPEC.md)), how it was verified,
what broke during verification and how it was fixed, and what remains unsupported. It is written for people who
want to trust — or challenge — the engine's claims.

## Contents

1. Summary
2. Version 2.0.0
3. What was built (1.0.0)
4. How it was verified
5. Results (1.0.0 run)
6. Engineering log: failures found by acceptance and their fixes (1.0.0)
7. Specification compliance
8. Known limitations
9. Reproducing everything

---

## 1. Summary

Design DNA turns a visual reference into an **evidence-backed, editable, persistent template**, rebuilds it with a
deterministic renderer, compares the rebuild with the reference region by region, and applies later edits as
verified transactions. Every stored value carries a status (`observed | measured | inferred | unknown |
not_applicable`) and points at the evidence that produced it.

The headline result: from a flattened PNG of a layered poster, plus the supplied original product photo, vector
logo and candidate font files, the engine measured the frames, text baselines, font sizes, letter tracking,
drop-shadow offset and blur, photo grading and a translucent overlay. It reached **sub-pixel / sub-percent
accuracy** and still refused to claim the font's identity. The rebuild passed the `editable_close` pixel profile,
and since 2.0.0 the test asserts that verdict.

## 2. Version 2.0.0

2.0.0 answers two inputs:

- **A v2 specification.** Make the package complete and reviewable/adaptable for other agent hosts. It asked for
  portable persistent templates, an enforced renderer pin, a "keep everything else" that cannot drift, an SVG
  export that states and verifies its contents, complete scan evidence, and adaptation checks against the approved
  baseline.
- **An independent repository audit of 1.0.0** with eight findings (F1–F8) and three additional corrections.
  Every finding is fixed and has a regression check: [AUDIT-RESPONSE.md](AUDIT-RESPONSE.md).

### New and rebuilt modules

| Script | Responsibility |
|---|---|
| `renderer_env.py` | browser launch, the environment fingerprint, `make_pin` / `compare_pin` (hard fields stop work, soft fields are reported) |
| `baseline.py` | `reconstruct`: approve + pin the first baseline per model content; re-runs prove reproducibility. `migrate_baseline`: preview, then explicit confirm |
| `svg_export.py` | element classification, self-contained SVG + manifest, round-trip verification of the exported file |
| `verify_change.py` | cache keyed by scene + tool + renderer and re-verified on hit; model-change report (requested / dependency / visual / note); mask-accurate visual-change report; checks against the previous revision and the approved baseline |
| `bundle.py` | `.dnab` export / validate / import, font embed or reference-by-hash, `StorageBackend` + `FilesystemBackend`, library lookup |
| `ops.py`, `apply_patch.py` | locks on actual leaf diffs (ancestors, removals, both states); pixel locks; keep-everything-else scope; reported constraint relaxation; rejected-transaction records |
| `compare_render.py` | RGBA identity vs composited appearance; regions without a footprint are `unknown`; missing evidence → `incomplete` |
| `validate_model.py` | required facets, sourced facts, interpretive categories never `measured`, passport completeness, composition-level editability (crop assemblies, baked content), slot limits |
| `render_static.py` | CSS/XML-escaped serialization, compiled-SVG allowlist, network blocking, text stroke, immutable outputs, per-node alpha masks |

### Engineering log (2.0.0)

| Symptom | Root cause | Fix |
|---|---|---|
| "Move the headline up 3 px, keep everything else" was rejected | a measured `gap` constraint between headline and accent bar changed, as the request implies | relaxable constraints touching an explicitly edited node are relaxed and **reported** (`relaxed_constraints`); hard constraints still conflict |
| A second edit's verification looked clean while the template had already drifted | each commit was compared only with its parent revision | cumulative check against the approved template baseline (matched by model content hash) on every commit |
| A refactor dropped a loop header in the region comparison | editing error caught by T01/T14 failing | restored; covered by the existing region assertions |
| Headless capture flake (`Unable to capture screenshot`) under heavy load | Chromium capture timing | bounded retry kept; renders are re-verified by hash anyway |
| The installer's backup of an old skill sat next to it in `~/.claude/skills` | two folders with the same skill name would both load | backups go to `~/design-dna/backups/` |
| The first full 2.0 run: T08/T09 crashed | tests still read the 1.0 render key `variant`, and the reflow probe compared images of different sizes | tests use `candidate`; requested-edit probes on a resized canvas check the rendered footprint and leave the layout verdict to `reflow_preserve`; the cumulative pixel check is `not_applicable` once a variant was reflowed (model changes are still checked) |
| T12: a missing asset file was not reported | the facet check reused the variable that held missing assets, so the report always returned an empty list | renamed; the error and the `missing_assets` status agree again |
| T01: `editable_close` came back `incomplete` | the operator scan defined no replaceable slots, and since the F1 fix a model without slots cannot claim editability | the scan now records its six slots, as a complete scan must |
| T26/T32 crashed with "3 templates match" | after T20/T21 imported copies under new ids, name lookup was (correctly) ambiguous | an exact template id always wins; ambiguity errors list the ids; the regressions address the template by id |

### Results (2.0.0)

Final run `20261006-234454`: **32/32 passed, 1 entry unverified by design**. Renderer: Chrome 154.0.8037.93
(Edge 154 for the drift test), Python 3.12.10, Windows 10. Evidence screenshots:
[images/evidence/v2.0.0](images/evidence/v2.0.0/).

| Kind | Checks | Result |
|---|---|---|
| Reconstruction | T01 — measured rebuild, `editable_close` asserted: max geometry error 0.46 px, head size 0.006 %, shadow σ 0.93 px | pass |
| Honest partial result | T02 — the other rasterizer's captions (Bahnschrift, not a candidate) fail and are reported; best substitute Tahoma Bold | pass |
| Preservation | T04, T05, T06, T15, T18, T19 | pass |
| Expected rejection | T07, T12, T13, T14, T16, T17 | pass |
| Adaptation / reflow / determinism / persistence | T08, T09, T10, T11 | pass |
| Portability | T20 — bundle round-trip after the working store was moved away | pass |
| Renderer integrity | T21 — a real Chrome → Edge switch is refused as drift until migrated; both Chromium 154 builds produced 0 differing pixels | pass |
| Export integrity | T22 — self-contained SVG (1.6 MB) rendered on its own and compared | pass |
| Audit regressions | T24–T33 | pass |
| Unverified integration | T23 — host storage adapter (no host available) | unverified |

### After 2.0.0: the suite off Windows (unreleased)

The first open item of the audit response was a Linux/macOS suite with redistributable fonts. On Linux the
unchanged 2.0.0 suite stopped before its first test: the fixtures opened `C:/Windows/Fonts/bahnschrift.ttf`.

Every font the suite touches now comes from a **font set** (`tests/fixtures/fontset.py`) of named roles. The
`windows` set is the verified 2.0.0 configuration. The `portable` set is open-licensed files vendored in
[`tests/fonts/`](../skills/reverse-design/tests/fonts/README.md), so every machine hashes the same font bytes.
Expected faces (T01's "true faces", T03's verified file) are read from the files rather than written as names.

| Role | windows | portable |
|---|---|---|
| sans (label, CTA) | Arial Bold | Liberation Sans Bold |
| serif (headline, no Arabic glyphs) | Georgia Bold | DejaVu Serif Bold |
| sans candidates | Arial, Verdana, Tahoma, Segoe UI, Calibri, Trebuchet (Bold) | Liberation Sans, DejaVu Sans, Carlito (Bold) |
| serif candidates | Georgia, Times New Roman, Cambria, Constantia (Bold) | DejaVu Serif, Liberation Serif, Caladea (Bold) |
| Arabic + Latin | Arial Bold | Amiri Bold |
| T02 captions (never a candidate) | Bahnschrift, Bold instance | Open Sans, Bold instance |
| variable `wdth` axis (T27) | Bahnschrift | Open Sans |

| Symptom (first Linux run) | Root cause | Fix |
|---|---|---|
| Setup crashed: `cannot open resource` | Windows font paths hard-coded in fixtures and tests | font set roles; portable fonts vendored with licences |
| T02: one caption baseline 1.03 px from the truth (limit 1 px) | the baseline was render-fitted together with size and x against a substitute font, which pulled it towards the substitute's glyph shapes. The node's provenance already said "measured from ink" | the baseline is held at the ink measurement (exact here); only size and x are fitted, so the provenance is now true |
| T17 crashed: `fit_conflict` on the long Arabic headline with a 56 px minimum | the first portable Arabic font (DejaVu Sans Bold) sets that line at 1244 px at 56 px in a 920 px box. The engine was right to refuse | Amiri Bold: fits at 62 px, overflows at 84 px, as Arial does |
| T21 could only test a switch to Edge | the second channel was hard-coded | the first other installed channel (Edge, Chrome, Playwright's Chromium) is used; none → unverified |

**Linux run `20261007-000228`: 31/31 passed, 2 unverified.** Ubuntu 24.04 container, Python 3.13.16, the packages of
`requirements-lock.txt` except Playwright 1.56.0 with its Chromium 141.0.7390.37 (the build installed in that
container), portable fonts, 4 minutes. T21 is unverified there because no second browser channel was installed.
T23 is unverified by design.

- T01 with different faces: max geometry error 0.46 px, headline size 0.004 %, label tracking 0.002 px, baselines
  ≤ 0.03 px, shadow σ 0.93 px. The true faces (Liberation Sans Bold, DejaVu Serif Bold) ranked first; identity
  stays `unknown`. `editable_close` passes.
- T02: frames within 1 px, captions at the true baselines (485 / 932), best substitute Liberation Sans Bold. All six
  caption regions fail and are reported; readiness stays `partial_baseline`.
- T10 determinism, T20 bundle round-trip and T22 SVG round-trip hold with 0 differing pixels on this renderer too.

**Re-run after the host packaging work: `20261007-005538`, 31/31 passed, 2 unverified**, with two engine fixes: an
in-progress scan no longer crashes `annotate_scan.py`, and library lookups break export-time ties in favour of the
self-contained bundle (a same-second export pair had made T20 import the font-referenced bundle and fail).

**Re-run with Google Chrome for Testing 154.0.8037.57 (the version GitHub's Ubuntu runners carry):
`20261007-011727`, 32/32 passed, 1 unverified (T23, by design).** Two browser channels were installed, so T21's real
drift check ran (Chrome pinned, Playwright's Chromium as the switch). This run also carries the real fix for the
T20 crash above: a lookup by name returns the newest export, and the font-referenced bundle was the newer one
whenever its export landed in a later second than the self-contained one, which the same-second tie-break did not
cover. T20 now keeps the two bundles in separate folders. T01 alone also passes with the CI job's exact Python
(3.12) and `requirements-lock.txt` packages.

The CI workflow gains an `acceptance-linux` job (ubuntu-latest, portable fonts, `requirements-lock.txt`). It runs
on the next push to `main` or pull request; its results are not part of this report yet. macOS is untested.


## 3. What was built (1.0.0)

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

## 4. How it was verified

- Every demonstration runs for real in an isolated template store and keeps its inputs and outputs.
- Demonstrations 1 and 2 are **operator-assisted scans**: the operator (Claude) proposes coarse regions and reads
  captions; every number is produced by the measurement tools and stored as evidence first. Ground truth (where it
  exists) is read only at the end, to score the result.
- Reference and rebuild are compared as decoded pixels under a declared policy (no resizing, blurring or alignment).
- The suite runs on Windows in CI (lint + schema check on Ubuntu).

## 5. Results (1.0.0 run)

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

## 6. Engineering log: failures found by acceptance and their fixes (1.0.0)

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

## 7. Specification compliance

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
| 5 Commands + mandatory edit behaviour | Implemented | all commands; property, category and pixel-region locks enforced (2.0.0); "keep everything else" is an allowed-change scope |
| 6 Reconstruction and rendering | Implemented for static flat graphics | other adapters return `unsupported`; generation/inpainting is not part of the engine |
| 7 Verification and acceptance | Implemented | metric panel, five profiles (incl. `svg_roundtrip`), 22 demonstrations + 10 audit regressions; the correction loop is operator-driven (iterations recorded in measurement logs) |
| 8 Architecture | Implemented | schema version 1.0.0 (no migrations needed yet), stable ids, immutable baselines, content-hashed assets, atomic saves, base-revision guard, undo, serialization-safe SVG compiler with an allowlist, renderer pin, portable bundles |

## 8. Known limitations

- **Adapters:** static raster only. PDF, layered sources (PSD/Figma/AI), live UI, motion, packaging and 3D are
  explicitly unsupported.
- **OCR and segmentation** are not automated; they are assisted and labelled.
- **Font identity** cannot be established from pixels; the engine ranks supplied candidates and stays `unknown`
  without source evidence. When the true font is not available, caption regions honestly fail (seen on a real
  client JPEG during development: photos matched exactly, captions failed with the best substitute at IoU 0.67;
  that client material is not part of this repository).
- **Reflow** anchors groups to edges and scales uniformly; tall formats can leave wide empty bands that need a
  design decision.
- **Host storage:** bundles work with any mounted folder; an API-only host store (e.g. ChatGPT Work) needs an
  adapter that is not included or tested.
- **Cross-machine reproduction:** the renderer pin detects a different browser or machine; identical pixels across
  machines are not claimed.
- **Platform:** verified on Windows with Chrome/Edge (Windows system fonts), and on Linux with Playwright's Chromium
  and the portable font set (one local run; the CI job is new). macOS is untested.

## 9. Reproducing everything

```bash
python -m pip install -r requirements-lock.txt        # exact tested versions
python skills/reverse-design/scripts/capabilities.py
python skills/reverse-design/tests/run_acceptance.py          # writes ~/design-dna/acceptance/<run>/report.md
python docs/tools/make_images.py ~/design-dna/acceptance/<run> --out docs/images/evidence/<version>   # evidence screenshots
```
