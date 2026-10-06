# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-10-06

### Added
- `reverse-design` Claude Code skill ("Design DNA") with plugin + marketplace manifests.
- Evidence model: per-property provenance, evidence store, 16-category scan coverage.
- Versioned JSON Schemas (2020-12): scene, evidence, template passport, typed patch.
- Measurement tools: ink bounds, projection profiles, sharp-edge scanlines, corner-radius circle fit, joint
  multi-probe shadow fit, role colour sampling (patch / ink-core / gradient), font candidate ranking with contact
  sheets, render-fitted typography (ink-moment seeding + coordinate descent + Nelder–Mead).
- Deterministic renderer: scene → SVG master → PNG via Playwright (Chrome → Edge → bundled Chromium),
  pinned fonts, `font-synthesis:none`, seeded grain; HarfBuzz shaping and bidi for Arabic.
- Comparison engine: exact pixels, MAE/RMSE, SSIM (global + per region), ΔE2000, geometry, typography,
  editability (reference-background shortcut detector); profiles `exact_pixels`, `editable_close`,
  `adapt_preserve`, `reflow_preserve`.
- Typed transactions: set / replace / move / resize / remove / add / lock / unlock / adapt / reflow, hard and soft
  locks, constraints, render-probed verification, immutable revisions, undo, export (PNG + SVG master).
- Formal command interface (`dna.py`) and template index (`list`, `find`, load by name).
- Acceptance suite: 14 executed demonstrations with retained evidence; CI on Windows.
