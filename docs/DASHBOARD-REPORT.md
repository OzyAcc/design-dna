# Design DNA dashboard: build report

Branch `claude/eager-gauss-j1fccc`, built from `main` at `73f2450` and merged as `6514902`; the fixes for the
dashboard audit of 2026-10-07 (D1–D4) were made on the same branch, restarted from `6514902`. This report covers
what was built, the status of each capability with its evidence, the closure of audit items A1–A5 and D1–D4, what
was verified, and what was not.

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
| Composer saves: ordered, acknowledged before Generate/preview/drafting, unsent copy kept until acknowledged (D1) | Implemented and tested | `ComposerWrites` browser tests (type then Generate at once, Leave empty inside the save delay, a slow earlier save, a failed save plus reload) | — |
| Copy precedence, explicit blanks, bulk apply by product, template or group | Implemented and tested | T11 | — |
| AI copy drafts (Claude): stored beside each field, never replace manual text, unapproved until reviewed | Implemented but not live-tested | T11 with the mock provider (an unapproved draft blocks submission with 409) | run with an `ANTHROPIC_API_KEY` |
| Language and fit: Arabic glyph coverage (no silent fallback), shaping, long-copy overflow with options | Implemented and tested | T13 | — |
| Submission: one key is one run of one content, frozen template version and inputs (D2) | Implemented and tested | T16 (template edited and saved as v2 before the job ran; the output still uses v1's bundle and crimson accent), T23 (duplicate submission), T29 (four concurrent submissions with one key make one run; the key with changed content → 409 `submission_changed`; lookup by key), `ComposerWrites` (a lost answer then a retry → the same run; a lost answer then a reload → the run is shown; a new Generate → a new run). Before D2 only a repeated request that got an answer was deduplicated: a failed or lost request cleared the key | — |
| Editable adaptation: one transaction, `keep everything else`, verified against the approved baseline, PNG + self-contained SVG with round trip | Implemented and tested | T17 (verification `pass`, 0 px outside influence vs the approved baseline, SVG round trip `pass`, product photo in the slot), container end-to-end run | — |
| Concurrent jobs in isolated stores | Implemented and tested | T15 (two workers, overlapping, separate stores, different results) | — |
| Creative generation (OpenAI GPT Image): new artwork with a text policy chosen before submitting (live text over the artwork, text drawn by the image model, imagery only), or a generated photo inside the template (D4) | Implemented but not live-tested; **Blocked by configuration** here (no `OPENAI_API_KEY`) | T18 with the mock provider: two outputs with different headlines each carry their own headline as live SVG text over text-free artwork (verification and SVG round trip pass); the drawn-text prompt contains the exact copy and approval needs `confirm_text`; imagery only marks the copy unused and keeps it out of the prompt; the generated slot image is recorded by the engine as `source: generated`; a drifted renderer is refused before any request (`T18.drift_before_paying`) | run with an `OPENAI_API_KEY`; whether a real model keeps the requested areas calm and spells drawn text correctly is not known |
| Missing keys and provider errors | Implemented and tested | T19 (412 with the setup path; creative preflight blocked; adaptation still works; unauthorized/rate-limited → failed, refused → needs review) | — |
| Partial failure, scoped retry as a new revision, paid-request confirmation, cancel | Implemented and tested | T23 (unknown outcome → Needs review; blind retry 409 `confirm_paid_retry`; repeat click deduplicated; revised copy changes only that slot; queued cancel keeps finished files) | — |
| Restart and recovery (D3) | Implemented and tested | T24 with a real worker process: killed mid-render (re-queued into a fresh store, completes on attempt 2, no orphaned engine process); killed while a paid request was in flight (Needs review, request `unknown`, never resent); stopped after the provider answered but before the result was stored (Needs review, not resent); stopped after the result was stored, and after the output files were written (re-queued, completes from the stored result, still one request); a damaged stored result (Needs review, not resent); a copy-drafting job resumed from its stored result; cancel stops a running render. Before D3 an answered request was treated as safe to re-run, and the re-run sent it again | power loss during a checkpoint write is not tested (only process kills) |
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
| A1: legacy pin gap | `renderer_env.compare_pin` reports a hard field missing from an old pin (`text_rendering`) as drift: `pinned: "unrecorded (pin predates this field)"`, `legacy_pin: true`. Rendering stops with `renderer_drift` until a migration is reviewed and confirmed. In the dashboard the output becomes **Needs review** with a "migrate the renderer" message. | engine T34; dashboard T20/T21 (the output is refused, then succeeds after a bound migration) | — |
| A2: intermittent render difference | Added repeated fresh-process coverage: engine T36 renders an edited fixture four times, each in a new process, and requires identical pixels (main's T10 now does 8 launches). Every dashboard rebuild re-renders in a fresh process; a difference sends the job to **Needs review** with both renders kept. An output whose pinned re-render does not reproduce the approved baseline is refused as **Needs review** with the kind `baseline_not_reproduced`, the pixel count and location, and both images ("Baseline not reproduced" in Results); approving it is refused and a retry renders again with no paid request. Zero-difference preservation is unchanged; no tolerance was added and no mask was widened. **The cause is fixed on `main`** (merged here): Chrome now runs with `--disable-partial-raster`, recorded as the hard pin field `determinism_args`. | Before the fix, on Linux (Chromium 141) under full CPU load: **7/30** fresh-process renders of one approved baseline differed, always the same 3 px (max channel error 35) on the antialiased corner of the CTA pill; **0/30** idle. A dashboard output was refused for it while three render-heavy processes ran. Two other mitigations made no difference (one raster thread: 2/20; waiting two frames before capture: 2/20). **After merging the fix: 0/30 under the same load, 0/10 idle.** Evidence: [`docs/images/evidence/a2-2026-10-07/`](images/evidence/a2-2026-10-07/). Dashboard T22 drives the refusal path. | Not re-run on Windows in this build. A template pinned before the fix has no `determinism_args` in its pin: under A1 that is drift, so it needs a reviewed renderer migration before preservation is claimed again (fresh workspaces are unaffected). |
| A3: migration preview integrity | `migrate_baseline` writes an immutable `migration-preview.json` (`preview_id` and hashes of base revision, model, old pin, approved baseline, candidate PNG and new renderer fingerprint). `confirm preview=<id>` adopts that exact candidate file. It is refused when the model, pin, baseline, renderer or candidate changed, when the preview is unknown or already confirmed, and when no preview id is given. The previous pin and baseline hash are recorded; the old baseline stays. The dashboard sends the reviewed `preview_id` and rejects a mismatch (409 `preview_mismatch`). | engine T35 (stale model, changed candidate, changed renderer, wrong id); dashboard T20/T21 | — |
| A4: application orchestration | Claude (`anthropic_provider.py`, structured JSON output) proposes elements, transcriptions and communication readings. They are stored as proposals and must be reviewed: measuring unreviewed proposals is refused. Every value then comes from the engine's tools (`scan_build.py`), which write evidence, coverage and constraints. A scan is complete only when you confirm the review and nothing failed. Drawing elements yourself works without a key. Free-text edits compile locally for formal phrasing and through Claude otherwise. | T05 (mock-labelled proposals, unreviewed → 409), T04, T06 | a live Claude run (no key in this environment) |
| A5: generation boundary | `openai_provider.py` (Images edit API with the reference and product photos, sizes rounded to the API's rules, request recorded before sending, result stored before use, no automatic resend; see D3 for the case that was missed). Creative outputs are labelled generated, with prompt, inputs and provider metadata. They claim no preservation or editability. A generated photo inside the template goes through the engine as `source: generated` and still gets the deterministic checks for the template around it. | T18, T19, T23, T24 with the mock provider | a live OpenAI run (no key in this environment) |

## Audit closure (D1–D4, dashboard audit of 2026-10-07)

The audit found that two claims in the first version of this report were only partly true: submission idempotency
held only when the first request got an answer, and restart recovery held only for a request still in flight. It
also found that the composer could submit content the server had not received, and that creative mode ignored the
reviewed copy. D1 and D2 were reproduced in a real browser against the code merged in `6514902` before they were
fixed; D3 and D4 were confirmed by reading that code (its recovery and prompt paths), since the test-only crash
points did not exist there.

| Item | What changed | Evidence | Remaining |
|---|---|---|---|
| D1 (P1): submission did not wait for the latest saves | One serial write queue per batch page (`web/src/writes.ts`): typing is saved after 900 ms; an explicit choice for the same field (Leave empty, Use inherited value, Use this draft) replaces the pending typed save; writes go one at a time, so an earlier, slower save can never land after a later one. **Generate**, **Check fit** and AI drafting first send everything pending and wait until the server has acknowledged it; if a save still fails after one more attempt, they stop and say so. Copy you typed is written to this browser's storage at once and removed only when the server acknowledges that exact value; it is sent again when the page comes back. The page shows "all changes saved", "saving…" or "N change(s) not saved". | `ComposerWrites` browser tests. Against the merged code: Generate right after typing froze the old headline (`'Saved\nheadline'`), Leave empty was overwritten by the earlier typing (`'Temporary kicker'`), a slow earlier save overwrote a later one, and a failed save still submitted the old text. With the fix all four pass, and a failed save is restored and saved after a reload. | Two tabs editing the same field: the last acknowledged save wins (not tested). |
| D2 (P1): a failed submission created a second run | The client stores the submission key before sending and keeps it until the submit itself answers (cleared only on success or by the handler's own refusals; a sign-in, proxy or portal response keeps it), and every tab of the batch uses the stored key. The server computes a fingerprint of everything frozen into the included outputs that changes them (copy, settings, images, template version, product content, instructions); the same key with the same content returns the same run, with changed content 409 `submission_changed` naming the earlier run. Preflight, the snapshot and the insert run in one write transaction. `GET /api/submissions/{key}` tells a page that comes back what its key created. | T29 and `ComposerWrites`. Against the merged code: a lost answer followed by a retry made **2 runs**; with the fix, 1. | A key is kept in one browser; a submission started in another browser is a separate intent. |
| D3 (P1): recovery re-ran a request whose answer was received | Every provider call goes through `provider_call`: recorded before sending, the result written to a fsynced checkpoint (`jobs/<id>/checkpoints/<request>.json`, SHA-256 recorded) and marked `stored` before anything is built from it. A re-run uses a valid stored result and makes no request. Recovery re-queues a job only if every request it made is `stored` with an intact checkpoint; `received`, in-flight (`unknown`) or a damaged checkpoint → **Needs review**. Retrying such an output still needs `confirm_new_paid_request`. Test-only crash points (`faults.py`) stop a real worker after the provider answered, after the checkpoint and after the output files. | T24 (six recovery scenarios with a real worker process, request counts checked in the database). In the merged code `recover()` blocked only `sending` requests, so a job whose request was `received` was re-queued and its re-run sent the request again (read from the code, not run). | This prevents resending from this application. It cannot prove what a provider billed for a request whose outcome is unknown; those stop for a person. |
| D4 (P2): creative mode ignored the reviewed copy | A text policy per output, chosen before submitting and frozen in its inputs and fingerprint: **overlay** (default; text-free artwork, then the template's own text with this output's approved copy and its shapes rendered over it by the engine as one verified transaction, PNG + SVG with live text), **in_image** (the copy is requested verbatim; raster text; approval needs a person to confirm it matches), **none** (imagery only; every copy field marked unused, shown before submitting and confirmed on Generate). Outputs frozen before policies existed keep their original no-text request. Also: the renderer pin is checked before any paid request whose result the engine must render (overlay and generated slot photos). | T18 (two outputs, two headlines, each in its own SVG and not in the other; in_image prompt and `confirm_text`; none keeps the copy out of the prompt), `T18.drift_before_paying` (0 requests). | No live image model run: whether a real model keeps the text areas calm and spells drawn text correctly is unverified. Drawn text is not checked automatically (no OCR). |

### Review of the fixes

Two independent review passes then read the fixes, one reviewer per finding, and a second agent tried to disprove
each reported defect by tracing the code. Every defect that survived was fixed and, where a test can show it,
covered by one. The container smoke run found one more (the first item). Most are further cases of the same four
problems:

| Area | Defect found | Fix | Test |
|---|---|---|---|
| D4 | Copy that does not fit, or a lock on the background, was refused by the engine only after the artwork had been paid for | The transaction is dry-run before the request, with a checkerboard stand-in for the paid image (overlay) or the product photo (generated slot photo) | `T18.overflow_before_paying`, `T18.lock_before_paying` (0 requests) |
| D1 | Generate replayed a failed choice the screen showed as not applied (a mode, a policy, bulk apply), and replayed a lost **+ Variant** (an extra output, unseen) | Only typed text is retried; a failed choice or action is reported, the batch is reloaded, and it is never replayed. Writes to one field share one key | `D1.failed_choice`, `D1.lost_variant` |
| D1 | A failure was forgotten when a later bulk apply to other rows succeeded; abandoned typed text could be replayed after **Use this draft** or a stale refusal | Keys name the rows written; `forget()` drops abandoned text; a stale refusal is not retried | — (traced) |
| D1 | **Use inherited value** could leave the abandoned text on screen; **Confirm mapping** could overtake a pending edit | The box re-syncs when its save is acknowledged; pending edits are sent before the remap | `D1.inherited` |
| D1 | Leaving through a link, Back or Forward dropped failed non-copy changes silently | The page holds the navigation, saves, and asks if something cannot be saved (react-router data router, `useBlocker`) | `D1.leave_unsaved` |
| D2 | A sign-in, proxy or captive-portal answer cleared the submission key; a second tab made a new key | The key is cleared only by the submit handler's own answers; it is read from storage at click time | `D2.proxy_error`, `D2.second_tab` |
| D2 | The fingerprint missed product content, and changed when an unused AI suggestion arrived | It covers everything frozen that changes the outputs, product content included, and nothing else | T29 |
| D3 | An output retry made a new key on every click (a lost answer → a second paid revision) | One key per retry intent, kept until answered; a second retry while one is queued is refused (`retry_in_progress`) | T23, `D3.lost_retry` |
| D3 | After an interrupted analysis or AI draft, the next click paid again without asking | The same confirmation as output retries | `D3.draft_confirmation` |
| D3 | Gateway timeouts (502, 504, 524) were treated as definite failures; request rows from before call keys were ignored | Both count as reached: unknown outcome, not resent | `D3.provider_outcomes` |
| D3 | A recovered job refused for drift claimed "no paid request"; a refused generated slot photo was dropped | A resumed attempt skips the pre-payment checks, so the refusal keeps the paid image as evidence | — (traced) |
| D4 | Revised copy on an imagery-only output was accepted and paid for, then ignored; older outputs were labelled "imagery only, chosen"; text checks dropped slots sharing a role; unused copy blocked Arabic outputs and appeared as image text in the ZIP manifest | Revised copy is refused (`copy_not_used`); older outputs say "submitted before text policies existed"; checks list each slot; unused copy is skipped by font checks and marked `used: false` | T18 |

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
| Output | import the frozen version into the job's store → `transact` → `export` (PNG, SVG + manifest, SVG round trip) |
| Renderer migration | `baseline.migrate_baseline` preview, then confirm with the preview id |

## Verification

| Check | Command | Result |
|---|---|---|
| Dashboard integration suite (real engine, real Chromium, real worker process; test-only mock providers) | `python -m unittest -v test_intake test_templates test_batches test_execution test_ui` | 51 tests, OK, none skipped (after the D1–D4 fixes; 38 before them) |
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
  migration on the template page before outputs are generated from them. Templates created after this merge are pinned
  with the fix.
- The synthetic poster fixture reaches `partial_baseline`, not `editable_close`. PIL-drawn reference text and
  Chromium text differ beyond the declared tolerance. The dashboard saves and labels it as partial, and generation
  works with that limitation shown.
- Font identity stays unknown: the scan ranks the fonts in the library. Upload the right font to improve a rebuild.
- Copy typed in the composer is saved about a second after typing stops (at once when you click Generate, Check fit
  or a choice such as Leave empty). Until the server acknowledges it, it is kept in this browser's local storage and
  sent again when the page comes back; it is not on the server yet, so another browser does not see it.
  Everything else is on the server.
- Creative text drawn by the image model is raster text, not checked automatically: approval asks a person to
  confirm it matches the approved copy. Live text over generated artwork is the default and is checked by the
  engine; the artwork itself has no preservation claim.
- The workspace has one access token, not user accounts.
