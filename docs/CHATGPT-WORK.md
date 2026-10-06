# Reviewing and adapting Design DNA for ChatGPT Work

Design DNA was built and tested as a **Claude Code** skill. This note is for anyone reviewing the package for
ChatGPT Work (or a similar agent host) or adapting it to one. Each point is marked **portable**,
**needs the host** or **unverified**. Nothing here was tested inside ChatGPT Work.

## What the package is

| Part | Where | Portable? |
|---|---|---|
| Instructions | `skills/reverse-design/SKILL.md` (YAML frontmatter `name` + `description`, then Markdown) | **portable**: plain Markdown. The frontmatter follows the Claude Code skill format; other hosts may want a different header. |
| Contracts | `references/*.md` | **portable**: loaded on demand; no host-specific syntax |
| Data formats | `schemas/*.json` (JSON Schema 2020-12) | **portable** |
| Engine | `scripts/*.py` (Python 3.10+) | **needs the host** to run Python with the packages in `requirements-lock.txt` |
| Renderer | Playwright driving Chrome / Edge / bundled Chromium | **needs the host** to launch a headless Chromium. Without it, nothing can be rendered or verified, and the capability report says so |
| Tests | `tests/run_acceptance.py` | **needs the host** plus the Windows system fonts the fixtures use |

## Requirements for the host

1. A Python 3.10+ sandbox that can install packages: `pip install -r requirements-lock.txt`.
2. A Chromium the sandbox can launch, either installed or via `python -m playwright install chromium`. Run
   `python scripts/capabilities.py` first: if `renderer` says `unavailable`, the engine can still scan and measure,
   but it cannot reconstruct, verify or export.
3. Fonts. Templates pin font files by sha256. A sandbox without the reference's fonts must receive them as files;
   a bundle exported with `fonts=embed` carries them, so check the licences before sharing.
4. A writable working folder for the store: set `DESIGN_DNA_HOME`.

## Persistence (the important part)

The working store is a **cache**. A sandbox that is wiped between sessions loses it. Persistence is the
`.dnab` bundle (`references/storage.md`):

- **Tested.** A host persistent folder that the sandbox sees as a normal directory works through
  `FilesystemBackend`. Export with `export-template "<Name>" to <persistent folder>` and retrieve with
  `fetch "<Name>" from <persistent folder>`. Acceptance T20 deletes the working folder, then imports and re-renders
  the template to identical pixels.
- **Unverified.** A host file store reachable only through an API needs an adapter implementing
  `bundle.StorageBackend`: `put(name, bytes)`, `get(name) -> bytes`, `list() -> [names]`. No such adapter is
  included or tested; acceptance entry 23 records this as UNVERIFIED.

Workflow for any host: export a bundle after a scan, after a reconstruct, and after each saved variant. At the
start of a session, `fetch` the template you need into the empty working store.

## Renderer pinning across sessions

A template's approved baseline pins its renderer: channel, version, flags, DPR, colour policy and font hashes.
If the host's Chromium differs from the pinned one (which is likely across hosts), every render stops with
`renderer_drift`. Do not delete the pin to make this go away. Run `migrate-baseline "<Name>"`, review the reported
pixel differences, and then `migrate-baseline "<Name>" confirm`. The old baseline stays on disk and the migration
is recorded in the passport.

## Adapting the instructions

- Tool names in `SKILL.md` are shell commands (`python scripts/dna.py '<command>'`). A host that runs code
  through a different tool can call the same commands there.
- The skill relies on the model's vision to propose element boundaries, transcribe text and read communication.
  The tools measure what the model proposes. Any capable multimodal model can do this. The quality of the
  proposals is the model's, and the acceptance suite does not measure it.
- Keep the non-negotiables (five claims kept apart, unknown ≠ pass, a candidate font is not identity, no
  reference-bitmap shortcuts). The code enforces them, but only when the instructions route through the code.

## Reviewing the claims

Start with `CAPABILITIES.md` (implemented / tested / partial / unsupported, with test ids and a SKILL.md claims
audit). Then read `samples/acceptance/report.md`, the actual run, results grouped by kind. Finally see
`docs/AUDIT-RESPONSE.md` for the independent audit and its regressions.
