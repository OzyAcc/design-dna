# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

Design DNA installs in every AI tool that can load it, starting with ChatGPT, from one skill and one engine; and
the acceptance suite runs off Windows (the first open item of the audit response).

### Added
- **Choose your AI tool**: ChatGPT (Skills upload for Business, Enterprise, Healthcare and Edu; Codex for every
  plan; a labelled instruction kit for Free, Plus and Pro), Codex, Claude Code, the Claude apps, Cursor, GitHub
  Copilot, Gemini CLI, Windsurf, Cline, Roo Code, OpenCode, Kiro, Junie, Goose, any host reading `.agents/skills`,
  and any assistant without skills. One guide per tool in `docs/hosts/`.
- **Compatibility registry** (`hosts/registry/*.json`): per host, the surfaces, install method, skill folders it
  reads, capability level, prerequisites, documentation sources (with how and when each was read) and test status
  per stage (install, discovery, invocation, scan, persistence, editing). `docs/hosts/COMPATIBILITY.md`, the guides
  and the README table are generated from it (`python install.py docs`; CI fails when they are stale).
- **Generated packages** from the canonical skill: ChatGPT and Claude skill zips (with hosted-sandbox notes), a
  plain skill zip, a Codex plugin with its marketplace, an Agent Plugins 1.0 package (Copilot), a Gemini CLI
  extension and the instruction kit (`python install.py package`). The `hosts` workflow attaches them to releases.
- **`install.py`**: `list`, `install`, `update`, `uninstall`, `doctor`, `package`, `docs`; target selection
  (ids, `detected`, `all`), user or project scope, `--dry-run`, skill folders or the host's own plugin and
  extension commands. Installed copies carry a stamp with every file's hash: update and uninstall touch only
  unmodified copies they installed, refuse otherwise, and `--force` moves to a backup instead of deleting.
  `doctor` checks Python, packages, Chromium and the store, and lists every copy each host can see, flagging
  duplicates. `install.sh` / `install.ps1` wrap it and still default to Claude Code.
- Installs straight from GitHub where the host supports it (`--from github`): Gemini CLI installs the repository as
  an extension (a generated root `gemini-extension.json`) without the trust-this-folder question it asks for
  local folders; Copilot installs `design-dna@design-dna` through the repository's own marketplace instead of the
  direct path installs it is deprecating. The Copilot download is now a marketplace with the plugin inside.
  `.claude-plugin` manifests and `gemini-extension.json` follow `VERSION`.
- `docs/hosts/EVIDENCE.md`: AI-host results (Claude Code verified end to end in two fresh sessions; Codex, Gemini
  CLI, Copilot and OpenCode discovery verified with their own CLIs) kept separate from operating-system results.
- `hosts/tests/`: installer and package tests for every target, and a host-discovery script that asks each host
  CLI what it sees.
- **Portable font set** for the acceptance suite (`tests/fixtures/fontset.py`, `tests/fonts/`): Liberation Sans/Serif
  Bold, DejaVu Sans/Serif Bold, Carlito Bold, Caladea Bold, Amiri Bold and Open Sans [wdth,wght], unmodified, with
  their SIL OFL 1.1 / Bitstream Vera licences and sha256 list. Every font role (the layered reference's sans and
  serif, the candidate lists, the Arabic + Latin font, T02's non-candidate caption face, T27's variable `wdth` font)
  comes from the set, and the expected faces are read from the files instead of hard-coded names.
  Windows machines with Arial and Georgia keep the verified `windows` set; elsewhere `portable` is used;
  `DESIGN_DNA_FONTSET` forces either. `report.json` records the set and the faces behind each role.
- CI job `acceptance-linux` (ubuntu-latest, `requirements-lock.txt`, portable fonts, its own evidence artifact).

### Changed
- `SKILL.md` declares `license` and `compatibility` (Agent Skills fields) and points at the repository for the
  acceptance suite, which installed copies leave out.
- `docs/CHATGPT-WORK.md` (an untested adaptation note) is replaced by `docs/hosts/chatgpt.md`.
- T02's caption baselines are held at the ink measurement and only size and x are render-fitted. The model's
  provenance already declared the baseline as measured from ink; fitting it against a substitute font had moved
  it by up to 1 px towards the substitute's glyph shapes.
- T21 uses any second installed browser channel (Edge, Chrome or Playwright's Chromium) for the real drift check,
  not only Edge; with none it stays unverified.
- `annotate_scan.py` no longer crashes on text nodes whose baseline is not measured yet (found by the Claude Code
  end-to-end run).
- T20 exports its font-referenced bundle to a folder of its own. With both bundles in one library, a lookup by
  name returns the newest export, so whenever the second export landed in a later second T20 imported the
  font-referenced bundle, which cannot import where its fonts are not installed (seen as a T20 crash cascading into
  T21-T32 on Linux). Library lookups (`fetch`, `bundle.py get`) also break same-second ties in favour of the
  self-contained bundle instead of file-name order.
- T20 resolves the font-referenced bundle's fonts from the font set's folder (`font_dirs`) as well as the system
  font folders.
- T01 also checks the CTA's horizontal position (within 1 px, like the label and headline), and a failed
  `editable_close` verdict now reports each failed region's SSIM, the fitted text parameters and the renderer.

## [2.0.0] — 2026-10-06

A complete, reviewable package: portable templates, an enforced renderer pin, scoped edits that cannot drift, a
verified SVG export, deeper scan evidence, and a fix with a regression check for every finding of the
6 October 2026 audit ([docs/AUDIT-RESPONSE.md](docs/AUDIT-RESPONSE.md)).

### Added
- **Portable template bundles** (`.dnab`): `export-template`, `validate-bundle`, `import-template`, `bundles`,
  `fetch` (by id, name or alias). Hash-listed manifests, fonts embedded or referenced by sha256, and a
  `StorageBackend` interface with a tested `FilesystemBackend`. The working store is now a cache.
- **Renderer pin**: the first approved baseline pins channel, version, flags, DPR, colour policy, font synthesis
  and font hashes. Drift stops rendering with `renderer_drift`. `migrate-baseline` previews the change, and
  `… confirm` adopts it with the old pin, new pin and pixel differences recorded.
- **"keep everything else"** as an allowed-change scope (the request + its dependencies). It adds no locks and
  removes none; a conflicting explicit lock is reported with options.
- **Pixel locks** (`lock pixels x,y,w,h`): zero changed pixels allowed inside the region.
- **Verification against the approved baseline** (cumulative) as well as the previous revision. Model changes
  (requested / dependency / visual / note) and visual changes are reported separately. Influence is the union of
  the edited nodes' own alpha masks, dilated 2 px.
- **SVG export manifest**: each element is classified (live text / vector / embedded raster / procedural texture /
  filter effects). The SVG is self-contained (`data:` URIs). The exported file is rendered on its own and
  compared with the engine PNG (`svg_roundtrip`).
- **Scan facets**: required facets per category, each with status / source / method / confidence / ambiguity.
  Communication categories cannot be `measured`. Passport completeness covers name, character, goal, theme,
  usage, message and mechanism.
- Text stroke rendering (centre-aligned) for text, shapes and paths.
- `CAPABILITIES.md` (implemented / tested / partial / unsupported + SKILL.md claims audit), `INSTALL.md`,
  `requirements-lock.txt`, `docs/CHATGPT-WORK.md`, `docs/AUDIT-RESPONSE.md`, `references/storage.md`,
  `schemas/bundle.schema.json`.
- Acceptance demonstrations 15–22:
  - keep everything else
  - conflicting lock + pixel locks
  - overflow, Arabic shaping and missing glyphs
  - token isolation
  - image replacement
  - bundle round-trip after deleting the working folder
  - real Chrome ↔ Edge drift + migration
  - exported SVG rendered and checked
- Entry 23 (host storage adapter) is marked **unverified**. Regressions 24–33 cover one audit finding each.
- New README concept illustrations. The v1.0.0 acceptance screenshots are kept in `docs/images/evidence/v1.0.0/`.

### Changed
- `exact_pixels` compares decoded **RGBA**. Composited appearance is reported separately (`appearance`).
- Missing required evidence makes a profile `incomplete`, never `pass`, and an empty inventory makes editability
  `incomplete`. Readiness is promoted only when the verdict passes, the scan is complete and editability passes;
  otherwise it stays `partial_baseline` with written reasons.
- Editability also rejects pages assembled from reference crops (≥ 90 % combined coverage) and crops with another
  element baked in (> 25 % of its box).
- Locks are enforced on actual before/after leaf differences, including ancestor replacement and node removal.
- Relaxable measured constraints are relaxed only for explicitly edited nodes, and reported.
- Canvas, aspect and artwork bounds come from the EXIF-oriented canonical image.
- Render cache keys include the tool version and renderer fingerprint. Hits are re-verified and can be relocated.
- Baselines, re-runs, migrations and exports are immutable (new stamped folders, no overwrites).
- The acceptance report groups results by kind (reconstruction, honest partial result, preservation, expected
  rejection, portability, renderer integrity, export integrity, audit regression, unverified). T01 asserts its
  `editable_close` verdict, and test titles state their supplied inputs.
- T02 uses a reference flattened by a different rasterizer (Pillow/FreeType, JPEG 4:2:0).
- Installers back up an existing skill to `~/design-dna/backups/` instead of next to it in the skills folder.
- CI actions moved to their Node 24 majors (`checkout@v7`, `setup-python@v7`, `upload-artifact@v7`).

### Security
- Asset ids and OpenType tags are pattern-constrained, CSS names and `style` attributes are escaped, every
  compiled SVG is parsed against a drawing-only allowlist, and all network requests from the renderer are blocked.

### Fixed
- The capability report no longer claims OCR when tesseract is installed.
- OpenType `features` / `variation` settings produced invalid SVG.

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
