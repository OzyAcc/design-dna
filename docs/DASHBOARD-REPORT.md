# Design DNA dashboard: build report

Branch `claude/eager-gauss-j1fccc`, built from `main` at `73f2450`. This report covers what was built, the status of
each capability with its evidence, the closure of audit items A1–A5, what was verified, and what was not.

Setup, configuration and the user guide are in [`dashboard/README.md`](../dashboard/README.md).

## Runnable application

| | |
|---|---|
| Source | `dashboard/server/dna_dashboard` (FastAPI API + worker), `dashboard/web` (React 19 + TypeScript, Vite) |
| Schema | `db.py` `MIGRATIONS` (SQLite, WAL), applied on start or with `python -m dna_dashboard migrate` |
| Data | `DNA_DATA_DIR` (default `~/design-dna-dashboard`; `/data` volume in the container) |
| Dependencies | `dashboard/requirements.txt` (tested set: `dashboard/requirements-lock.txt`), `dashboard/web/package-lock.json` |
| Settings | `dashboard/.env.example` (no secrets) |
| Local | `python -m dna_dashboard all` in `dashboard/server`, after `npm ci && npm run build` in `dashboard/web` → **http://127.0.0.1:8765** |
| Container | `docker compose -f dashboard/docker-compose.yml up --build` → **http://127.0.0.1:8765** (sign in with `DNA_AUTH_TOKEN`) |

## Keys and setup each capability needs

| Need | For | Without it |
|---|---|---|
| Chromium (Playwright's, or Chrome/Edge) | every render, measurement, rebuild, edit and output | engine jobs fail with an infrastructure error naming the renderer |
| `ANTHROPIC_API_KEY` | **Analyze with Claude** (proposed elements, transcription, communication reading), AI copy drafts, free-text edits outside the formal phrasing | those buttons say a key is needed; drawing elements yourself, formal edit phrasing and typed edits all work |
| `OPENAI_API_KEY` with access to `DNA_IMAGE_MODEL` (default `gpt-image-2`) | creative generation; a generated product photo inside the template | those modes are blocked in preflight (`no image generation provider is configured`) |
| `DNA_AUTH_TOKEN` | any non-loopback bind (always in the container) | the server refuses to start on a public address |

## Outcome report

Status values: **Implemented and tested**; **Implemented but not live-tested**; **Blocked by configuration** (works
once the named key or setup exists); **Unimplemented**. Test ids refer to `dashboard/tests` unless marked *engine*,
which refers to `skills/reverse-design/tests/run_acceptance.py`.

| Capability | Status | Evidence | Next requirement |
|---|---|---|---|
| Fresh workspace, library cards, search, filters, collections, archive | Implemented and tested | T01, T28, screenshots 01/11 | — |
| Intake: upload and direct image link, for both roles; original bytes and hash; previews | Implemented and tested | T02 | — |
| Paste from the clipboard | Implemented and tested at the API (same endpoint, `source_kind=paste`) | T02 | a browser clipboard test |
| Web-page link: picker over the images the page declares, or an actionable failure | Implemented and tested | T03 (served pages: `og:image` first, `img` tags, tracking pixels skipped, scripts never run, a broken image flagged, a page without images gives an actionable error) | — |
| Intake protections: type, size, decompression bomb, private destinations, schemes, unsafe archives, path traversal | Implemented and tested | T27 | — |
| Workspace authentication (Bearer or session cookie + CSRF header); public bind refused without a token | Implemented and tested | T27 `test_workspace_authentication`; container smoke test (401 without a token) | multi-user accounts are not in scope |
| Template drafts: resumable, optimistic revisions, unknown stays unknown | Implemented and tested | T04 | — |
| Manual scan: reviewed boxes measured by the engine's tools; 16 categories with status | Implemented and tested | T05, screenshot 03/04 | — |
| Assisted scan (Claude proposes elements, transcription, communication) | Implemented but not live-tested | the orchestration ran with the labelled mock provider (T05: proposals stay unreviewed; measuring them is refused with 409 `unreviewed_proposals`) | run with an `ANTHROPIC_API_KEY` |
| Staged rebuild and compare, fresh-process reproducibility, saved at the readiness reached | Implemented and tested | T06; the base fixture honestly reaches `partial_baseline` (4 text regions outside `editable_close` tolerance), identical on the host and in the container | — |
| Template inspector: elements, palette, type, rules, instructions, message, slots, versions, coverage | Implemented and tested | T07, T28, screenshot 06 | — |
| Protected originals, copies with a new identity, verified edits, undo, versions, restore | Implemented and tested | T08 (parent bundle and model unchanged; restore adds v3), T14 (lock conflict keeps the head) | — |
| Free-text edits: formal phrasing compiled locally; anything else compiled by Claude | Formal: Implemented and tested (T08, T14). Claude: Implemented but not live-tested | `commands.py` | run with an `ANTHROPIC_API_KEY` |
| Template bundles: `.dnab` export, clean-store import, validation, reproduction | Implemented and tested | T25, T27 (unsafe bundle refused) | — |
| Renderer pin, legacy-pin decision, migration preview/confirm bound to the reviewed candidate | Implemented and tested | engine T34, T35; dashboard T20/T21 (`test_legacy_pin_blocks_generation_until_a_bound_migration`) | — |
| Products (primary/detail images, description, facts, instructions) | Implemented and tested | T09–T13 | — |
| Batch composer: stable pairs, exclusion, variants, per-output copy that survives reorder, reload and re-add | Implemented and tested | T09, T10, T12, screenshot 08 | — |
| Copy precedence, explicit blanks, bulk apply by product, template or group | Implemented and tested | T11 | — |
| AI copy drafts (Claude): stored beside each field, never replace manual text, unapproved until reviewed | Implemented but not live-tested | T11 with the mock provider (an unapproved draft blocks submission with 409) | run with an `ANTHROPIC_API_KEY` |
| Language and fit: Arabic glyph coverage (no silent fallback), shaping, long-copy overflow with options | Implemented and tested | T13 | — |
| Submission: idempotent, frozen template version and inputs | Implemented and tested | T16 (template edited and saved as v2 before the job ran; the output still uses v1's bundle and crimson accent), T23 (duplicate submission) | — |
| Editable adaptation: one transaction, `keep everything else`, verified against the approved baseline, PNG + self-contained SVG with round trip | Implemented and tested | T17 (verification `pass`, 0 px outside influence vs the approved baseline, SVG round trip `pass`, product photo in the slot), container end-to-end run | — |
| Concurrent jobs in isolated stores | Implemented and tested | T15 (two workers, overlapping, separate stores, different results) | — |
| Creative generation (OpenAI GPT Image): new artwork, or a generated photo inside the template | Implemented but not live-tested; **Blocked by configuration** here (no `OPENAI_API_KEY`) | T18 with the mock provider: provenance `generated`, preservation `not_applicable`, editability `none`; the generated slot image is recorded by the engine as `source: generated` | run with an `OPENAI_API_KEY` |
| Missing keys and provider errors | Implemented and tested | T19 (412 with the setup path; creative preflight blocked; adaptation still works; unauthorized/rate-limited → failed, refused → needs review) | — |
| Partial failure, scoped retry as a new revision, paid-request confirmation, cancel | Implemented and tested | T23 (unknown outcome → Needs review; blind retry 409 `confirm_paid_retry`; repeat click deduplicated; revised copy changes only that slot; queued cancel keeps finished files) | — |
| Restart and recovery | Implemented and tested | T24: a real worker process killed mid-render (job re-queued into a fresh store, completes on attempt 2, no orphaned engine process); killed while a paid request was in flight (Needs review, request `unknown`, never resent); cancel stops a running render | — |
| Results review, approval, single-file downloads, ZIP with `manifest.json` + `MANIFEST.txt` | Implemented and tested | T26 (hashes match, latest revision per output, no secrets or unrelated files), screenshot 09 | — |
| Settings: providers, renderer, limits, fonts; keys stored 0600 and picked up by a running worker | Implemented and tested | T19, T26, screenshot 10 | — |
| Responsive layout, keyboard use, accessible names | Implemented and tested | T28 (every page at 390 and 1280 px: no sideways scroll, no script errors, every visible control named; skip link, focus ring, phone menu) | a screen-reader pass |
| Container: web + separate worker on one volume, auth required | Implemented and tested | image built (Playwright base), health/401/runtime checked, a full template → output → ZIP run inside it; the `container` CI job builds it and checks health, 401 and the worker on GitHub | — |
| CI for the dashboard | Implemented and tested | `.github/workflows/dashboard.yml`: `test` (full suite, real browser) and `container` pass on GitHub's Ubuntu runners | — |
| PDF/PSD/Figma/AI intake, live website capture, background removal, OCR, automatic segmentation | Unimplemented (the engine reports them `unsupported`) | Settings → Input adapters | adapters |
| Multi-user accounts, roles, per-user history | Unimplemented (one workspace token) | — | an identity provider |

## Audit closure (A1–A5)

| Item | What changed | Evidence | Remaining |
|---|---|---|---|
| A1: legacy pin gap | `renderer_env.compare_pin` reports a hard field missing from an old pin (`text_rendering`) as drift: `pinned: "unrecorded (pin predates this field)"`, `legacy_pin: true`. Rendering stops with `renderer_drift` until a migration is reviewed and confirmed. In the dashboard the output becomes **Needs review** with a "migrate the renderer" message. A generated photo inside the template checks the pin (`engine_runner` `pin_check`: the live environment against the pin, nothing rendered) before its image request, so that refusal costs no paid request. | engine T34; dashboard T20/T21 (the output is refused, then succeeds after a bound migration); T18 (`test_creative_slot_on_a_drifted_pin_is_refused_before_the_paid_request`: a legacy pin, `renderer_drift`, zero provider requests) | — |
| A2: intermittent render difference | Added repeated fresh-process coverage: engine T36 renders an edited fixture four times, each in a new process, and requires identical pixels (main's T10 now does 8 launches). Every dashboard rebuild re-renders in a fresh process; a difference sends the job to **Needs review** with both renders kept. An output whose pinned re-render does not reproduce the approved baseline is refused as **Needs review** with the kind `baseline_not_reproduced`, the pixel count and location, and both images ("Baseline not reproduced" in Results); approving it is refused and a retry renders again with no paid request. Zero-difference preservation is unchanged; no tolerance was added and no mask was widened. **The cause is fixed on `main`** (merged here): Chrome now runs with `--disable-partial-raster`, recorded as the hard pin field `determinism_args`. | Before the fix, on Linux (Chromium 141) under full CPU load: **7/30** fresh-process renders of one approved baseline differed, always the same 3 px (max channel error 35) on the antialiased corner of the CTA pill; **0/30** idle. A dashboard output was refused for it while three render-heavy processes ran. Two other mitigations made no difference (one raster thread: 2/20; waiting two frames before capture: 2/20). **After merging the fix: 0/30 under the same load, 0/10 idle.** Evidence: [`docs/images/evidence/a2-2026-10-07/`](images/evidence/a2-2026-10-07/). Dashboard T22 drives the refusal path. | Not re-run on Windows in this build. A template pinned before the fix has no `determinism_args` in its pin: under A1 that is drift, so it needs a reviewed renderer migration before preservation is claimed again (fresh workspaces are unaffected). |
| A3: migration preview integrity | `migrate_baseline` writes an immutable `migration-preview.json` (`preview_id` and hashes of base revision, model, old pin, approved baseline, candidate PNG and new renderer fingerprint). `confirm preview=<id>` adopts that exact candidate file. It is refused when the model, pin, baseline, renderer or candidate changed, when the preview is unknown or already confirmed, and when no preview id is given. The previous pin and baseline hash are recorded; the old baseline stays. The dashboard sends the reviewed `preview_id` and rejects a mismatch (409 `preview_mismatch`). | engine T35 (stale model, changed candidate, changed renderer, wrong id); dashboard T20/T21 | — |
| A4: application orchestration | Claude (`anthropic_provider.py`, structured JSON output) proposes elements, transcriptions and communication readings. They are stored as proposals and must be reviewed: measuring unreviewed proposals is refused. Every value then comes from the engine's tools (`scan_build.py`), which write evidence, coverage and constraints. A scan is complete only when you confirm the review and nothing failed. Drawing elements yourself works without a key. Free-text edits compile locally for formal phrasing and through Claude otherwise. | T05 (mock-labelled proposals, unreviewed → 409), T04, T06 | a live Claude run (no key in this environment) |
| A5: generation boundary | `openai_provider.py` (Images edit API with the reference and product photos, sizes rounded to the API's rules, request recorded before sending, no automatic resend). Creative outputs are labelled generated, with prompt, inputs and provider metadata. They claim no preservation or editability. A generated photo inside the template goes through the engine as `source: generated` and still gets the deterministic checks for the template around it; the template's renderer pin is checked before the image is requested. | T18, T19, T23, T24 with the mock provider | a live OpenAI run (no key in this environment) |

## Engine mapping

Every engine call is a subprocess with an explicit store (`engine.py`, `engine_runner.py`). Template workspaces,
staging copies and per-job stores are separate folders, and an engine step dies with the worker that started it.

| Dashboard action | Engine |
|---|---|
| New template | `inspect_source.create_template` |
| Measure | `measure.py`, `sample_colors.py`, `font_candidates.py`, `fit_text.py`, evidence records, `validate_model` |
| Rebuild and compare | `baseline.reconstruct` in a staging copy, twice (approval, then fresh-process reproduction) |
| Save version / export bundle / import | `bundle.py` export → validate → sealed `.dnab`; import with `as_id` for copies |
| Edit, undo | `apply_patch.transact` (typed ops, `keep everything else`), undo |
| Fit preview | `ops.apply_ops` + `render_static.render` (nothing committed) |
| Output | import the frozen version into the job's store → `transact` → `export` (PNG, SVG + manifest, SVG round trip); a generated photo in the template runs `pin_check` (`render_static.current_environment` vs `renderer_env.compare_pin`) before the image request |
| Renderer migration | `baseline.migrate_baseline` preview, then confirm with the preview id |

## Verification

| Check | Command | Result |
|---|---|---|
| Dashboard integration suite (real engine, real Chromium, real worker process; test-only mock providers) | `python -m unittest -v test_intake test_templates test_batches test_execution test_ui` | 38 tests, OK (also re-run after merging `main`: 38 OK) |
| Engine acceptance (portable fonts, Linux) | `DESIGN_DNA_FONTSET=portable python skills/reverse-design/tests/run_acceptance.py` | 35 passed, 2 unverified (T21 needs a second browser channel; T23 host storage by design); includes T34–T37 and main's 8-launch T10; same result after merging `main` |
| Installer and package tests | `python -m unittest discover -s hosts/tests` | 16 tests, OK |
| Generated docs are current | `python install.py docs --check` | up to date |
| Static checks | `python -m pyflakes skills/reverse-design/scripts skills/reverse-design/tests hosts install.py dashboard/server dashboard/tests`; `npm run build` (tsc + vite) | clean |
| Container | `docker build -f dashboard/Dockerfile .`, web + worker containers, full flow inside | image built; health 200, unauthenticated 401; template measured → rebuilt (`partial_baseline`, reproduces) → v1 → output `completed`, verification `pass`, SVG round trip `pass` → ZIP |

**Not run:**

- Live Anthropic and OpenAI requests: no keys in this environment.
- The dashboard on Windows and macOS. On GitHub, the engine acceptance suite passed on Windows (Chrome) and Linux,
  and the installer tests on Windows, macOS and Ubuntu.
- Engine T21 needs a second browser channel; T23 (host storage) is unverified by design.
- A screen-reader pass.
- A browser clipboard paste.

The container build here needed one environment workaround. This sandbox's network blocks the Debian package
mirror, so the image uses Playwright's official base image, which already contains the browser libraries. The
proxy CA was added only for the local build and is not in the committed Dockerfile.

## Limitations to know

- **Templates pinned before the A2 fix** (no `determinism_args` in the pin) report renderer drift and need a reviewed
  migration on the template page before outputs are generated from them. Until then their outputs are refused as
  **Needs review**; a generated photo in the template is refused before its image request, so nothing is paid for.
  Templates created after this merge are pinned with the fix.
- The synthetic poster fixture reaches `partial_baseline`, not `editable_close`. PIL-drawn reference text and
  Chromium text differ beyond the declared tolerance. The dashboard saves and labels it as partial, and generation
  works with that limitation shown.
- Font identity stays unknown: the scan ranks the fonts in the library. Upload the right font to improve a rebuild.
- Unsent copy in the composer is kept in the browser (local storage) until it is saved, about a second after
  typing stops. Everything else is on the server.
- The workspace has one access token, not user accounts.
