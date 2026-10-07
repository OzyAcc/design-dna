# Response to the repository audit of 6 October 2026

The audit reviewed v1.0.0 at commit `ede63fd`. Version 2.0.0 fixes every finding. Each finding has its own
regression check in the acceptance suite (T24–T33, `skills/reverse-design/tests/regressions.py`). Each check
reproduces the failure case described in the audit and asserts the corrected behaviour.

## Findings

| ID | Finding | Fix in 2.0.0 | Regression |
|---|---|---|---|
| F1 | An incomplete scan can receive an editable pass | Empty inventory / no slots → editability `incomplete`. A verdict with blocking unknowns or no compared regions → `incomplete`. A region with no rendered footprint → `unknown`. Readiness is promoted only when the verdict passes **and** the scan is complete **and** editability passes; otherwise `partial_baseline` with written reasons. Reference crops are assessed across the whole composition: ≥ 90 % combined coverage = assembled page, > 25 % of another element's box = baked content. | T24, T25 |
| F2 | Locks miss ancestor replacement and removal; "keep everything else" mapped to blanket locks | Locks are checked against the actual before/after leaf differences, covering equal, descendant and ancestor paths. Category membership is evaluated in both states, so a removed node is still covered. "keep everything else" is now an allowed-change *scope*: the request plus its dependencies. It adds and removes no locks, and an explicit lock on the target is a conflict until unlocked. | T26, T15, T16 |
| F3 | Font ids can inject markup into `<style>`; `features`/`variation` produce invalid XML | Asset ids and OpenType tags are pattern-constrained in the schema. Every name written to CSS is a CSS-escaped string, and `style` attributes are XML-escaped. Every compiled SVG is parsed and refused if it contains anything outside the drawing allowlist (no `script`, `foreignObject`, `on*`, external hrefs). The renderer blocks every network request. | T27 |
| F4 | Exact-pixel and preservation checks discard alpha | `exact_pixels` compares decoded **RGBA**. Composited appearance is reported separately as `appearance`. Preservation outside the influence uses RGBA. | T28 |
| F5 | Browser versions recorded, not enforced; cache trusts stale results | The first approved baseline pins the renderer (`passport.render_pin`). Hard fields are channel, version, flags, DPR, colour policy, font synthesis and pinned font hashes; any drift raises `renderer_drift` before rendering. `migrate-baseline` previews the change, and only `… confirm` adopts it, with the old pin, new pin and pixel differences recorded. The cache key includes the tool version and runtime fingerprint, and a hit is re-verified (files exist, PNG sha, masks, renderer). Exact versions are in `requirements-lock.txt`. | T21, T29 |
| F6 | EXIF rotation leaves a conflicting canvas | Canvas, aspect and artwork bounds come from the oriented canonical image; header dimensions are kept as metadata. | T30 (orientations 5–8) |
| F7 | Relocated templates keep unusable cached paths | Cached reports are rebased onto their current folder and a hit requires its files. Portable `.dnab` bundles carry hash manifests, `validate` / `import` / library lookup by id or name, and fonts embedded or referenced by hash. | T29, T20 (import after deleting the working folder) |
| F8 | T01 doesn't assert its verdict; inputs overstated | T01 now asserts `editable_close: pass` and has complete measured coverage. The test titles state the supplied inputs. `report.md` groups results by kind: reconstruction, honest partial result, preservation, expected rejection, portability, renderer integrity, export integrity, audit regression, unverified integration. README and BUILD-REPORT wording corrected. | T01, report |

## Additional corrections

| Audit item | Fix | Regression |
|---|---|---|
| Text stroke silently ignored | Rendered as a centre-aligned stroke on text. Strokes on node types the renderer can't draw (images, backgrounds, effect nodes) are rejected by validation. | T31 |
| Baselines and exports overwritten | The first run approves `baseline/rev-NNNN/`. Re-runs and migrations go to new stamped folders, exports to `rev-NNNN-<ts>`, and the renderer refuses to overwrite an existing `<name>.png`. | T32 |
| OCR reported as implemented when tesseract exists | The capability report says `unsupported: no OCR integration`, regardless of installed tooling. | T33 |

## Behaviour worth knowing

- **Unknown probes.** Some authorised changes have no pixel signature: an alias, a role, provenance. Their
  probe is `unknown`. A commit then verifies as `pass_with_unknowns`, and the unknown paths are listed. It still
  requires zero changed pixels outside the declared influence, against both the previous revision and the
  approved baseline. Any `fail` rejects the transaction.
- **What the pin proves.** The pin makes renderer drift detectable and keeps migration explicit. It does not
  claim identical pixels across machines; cross-machine reproduction is untested.

## The audit's comparison table, revisited

The audit compared v1.0.0 with another engine and listed areas where that engine was stronger. 2.0.0 covers each:

| Area | 2.0.0 |
|---|---|
| Runtime enforcement | pinned fingerprint + explicit `migrate-baseline … confirm` |
| Edit scope | "keep everything else" scope, dependency-aware, verified against the approved baseline |
| Pixel identity | decoded RGBA |
| Allowed pixel influence | per-node rendered alpha masks (including masks, rotation, shadows), dilated 2 px |
| Exported SVG verification | the exported file is rendered on its own and compared with the engine PNG; its manifest declares live text / vector / raster / filter effects |
| Persistence | integrity-checked portable bundles; host persistence (ChatGPT Work) is an **unverified** integration point (T23, `docs/CHATGPT-WORK.md`) |

## Dashboard build audit (A1–A5)

The dashboard build spec listed five items against 2.0.0. Their closure, evidence and the part of A2 that could not
be reproduced here are in [DASHBOARD-REPORT.md](DASHBOARD-REPORT.md#audit-closure-a1a5). In short:

- **A1, legacy pins:** a pin missing a hard field is now drift (T34).
- **A3, migration integrity:** confirmation is bound to the reviewed preview (T35).
- **A2, fresh-process reproducibility:** new coverage (T36; T10 now renders 8 fresh launches). The difference was
  reproduced on Linux under heavy CPU load (3 px at a curved edge, 7 of 30 renders) and is fixed by
  `--disable-partial-raster` (0 of 30 under the same load). Any remaining refusal surfaces as **Baseline not
  reproduced** in the dashboard.
- **A4, orchestration:** Claude proposals pass through review and the engine's measurement tools.
- **A5, generation:** an OpenAI image adapter, with generated results labelled and kept apart from the
  deterministic checks.

## Still open

- ~~A Linux/macOS fixture suite using redistributable fonts.~~ Done after 2.0.0 (unreleased): a portable font set
  vendored with its licences; Linux run 31/31 passed, 2 unverified ([BUILD-REPORT](BUILD-REPORT.md), section 2).
  A CI job for ubuntu-latest is added and has not run yet. macOS is still untested.
- A host storage adapter tested inside ChatGPT Work.
- Independent reproduction. Check the uploaded CI evidence (`acceptance-evidence` artifact) rather than this
  document.
