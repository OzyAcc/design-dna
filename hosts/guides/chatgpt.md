ChatGPT offers three different ways in, and they are not equal. Pick by plan and by how much of the engine you need.

| You have | Use | What you get |
|---|---|---|
| ChatGPT **Business, Enterprise, Healthcare or Edu** with Skills enabled | **ChatGPT Skills**: upload `design-dna-chatgpt-skill.zip` | The native skill. Its scripts run in ChatGPT's sandbox; how much of the engine works depends on what that sandbox provides (see below) |
| A computer and a ChatGPT plan that includes Codex (OpenAI's Codex pricing page lists them) | **[Codex](codex.md)**, OpenAI's coding agent (app, CLI or IDE extension), signed in with your ChatGPT account | The full engine on your machine: measurement, rendering, verified edits, saved templates |
| ChatGPT **Free, Plus or Pro** in the browser only | **Instruction kit** in a Project or custom GPT | A clearly labelled fallback: the method and vocabulary, visual estimates only, nothing measured or verified |

Codex installs are covered in the [Codex guide](codex.md). The rest of this page covers ChatGPT itself.

<!-- after-install -->

## What runs inside ChatGPT Skills

ChatGPT Skills load `SKILL.md` and can run the bundled scripts in a hosted sandbox. OpenAI does not document that
sandbox's Python packages or browser for this use, and this package has not been run there (no access from the
build environment), so the skill checks instead of assuming. Its first step is `python scripts/capabilities.py`:

| The sandbox has | Works | Does not work |
|---|---|---|
| Pillow, numpy, scikit-image, scipy, jsonschema, fontTools | intake, measurement, colour sampling, validation, annotated scan report, bundles | anything that renders |
| …and a Chromium that Playwright can launch | everything, including font fitting, reconstruction, verification, verified edits, SVG export | — |
| neither | method guidance; the skill says so and labels estimates | measurement, rendering, verification |

The packaged `SKILL.md` carries a "Running in a hosted sandbox" section with exactly these rules, so the model
reports a missing capability instead of improvising one.

## Keeping templates between chats

A ChatGPT sandbox is discarded after the chat. The skill exports the template as a `.dnab` bundle after the scan,
the rebuild and every saved variant, and offers it as a download. Keep those files. In a later chat, attach the
bundle and ask to continue: the skill imports it before any edit.

## Admins (Enterprise and Edu)

Skills are off by default in Enterprise and Edu workspaces. An admin turns them on under Permissions & Roles in
the admin dashboard and chooses which roles can create, use, share or install skills. A skill you upload appears
under *Created by me*; sharing it with the workspace makes it appear under *Shared by your workspace* for others.

## Updating or removing

Upload the zip of the new release the same way. If the old version is still listed, remove it from the Skills
page so only one `reverse-design` remains. (OpenAI's update controls were not verified for this guide; the
help article linked below is authoritative.)

## If something goes wrong

- **No Skills tab:** the workspace is not on Business, Enterprise, Healthcare or Edu, or an admin has not enabled
  Skills. Use Codex or the instruction kit.
- **Upload rejected:** the zip must contain one top-level folder, `reverse-design/`, with `SKILL.md` inside. Do not
  re-zip the unpacked folder's contents without that folder.
- **"renderer unavailable":** expected in a sandbox without Chromium. Measurements still work; for rendering and
  verified edits, use Codex or another local agent.
- **Results look too confident:** the skill must never claim a render or a verified edit that did not run. Ask it
  to show the command output that produced the claim.
