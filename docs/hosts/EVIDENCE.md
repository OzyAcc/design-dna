# Evidence: AI-host installation and operating-system results

Recorded 7 October 2026 in a Linux build environment (Ubuntu 24.04 container, Python 3.13, Node 22). Two kinds of
result are kept apart on purpose:

- **AI-host results** say whether a tool finds, loads and runs the skill. They depend on the tool, not the OS.
- **Operating-system results** say whether the installer and the engine work on Linux, Windows or macOS. They
  depend on the OS, not the tool.

The per-host status table is generated from the registry: [COMPATIBILITY.md](COMPATIBILITY.md#host-test-results).
Raw evidence: [evidence/2026-10-07/](evidence/2026-10-07/).

## What could and could not be tested here

The build environment had the Claude Code CLI with a working sign-in, and installed the Codex, Gemini CLI,
GitHub Copilot and OpenCode CLIs from npm without accounts. Those four CLIs can list the skills they discover
without a model, which is the discovery evidence below. Invocation, scanning, persistence and editing need a model
session: only Claude Code had one. ChatGPT, the Claude apps, Cursor, Windsurf, Cline, Roo Code, Kiro, Junie and
Goose were not available at all, so their stages beyond packaging are **untested**, which is not the same as
failing.

The environment's network policy also blocked direct reads of several vendors' documentation sites
(help.openai.com, developers.openai.com, learn.chatgpt.com, cursor.com, docs.windsurf.com, agentskills.io). Those
facts come from search-engine excerpts of the official pages and are marked as such in the registry; facts from
public documentation repositories name the commit they were read at.

## AI-host results

### Claude Code

Claude Code 2.1.292, skill installed with `python install.py install --target claude-code`. Two fresh,
non-interactive sessions (`claude -p`), each with its own template store, connected only through bundles in a
shared `./library` folder. Summary with every tool call: [claude-code-e2e.json](evidence/2026-10-07/claude-code-e2e.json).

| Stage | Result | What was observed |
|---|---|---|
| install | ✅ | `~/.claude/skills/reverse-design` with its stamp; `install.sh` over a copy left by the old installer moved it to a backup first; `claude plugin validate` passes on the repository's plugin manifest |
| discovery | ✅ | both sessions' init events list `reverse-design` in `skills` and `slash_commands` |
| invocation | ✅ | in both sessions the model's first tool call was `Skill(reverse-design)` |
| scan | ✅ | session A on a 1080×1350 poster: `capabilities.py`, `dna.py 'scan …'`, `measure.py` profile/ink/edges, `sample_colors.py --apply`, `annotate_scan.py`, `validate_model.py` → VALID; bundle exported. Asked for 5 categories, not a full 16-category scan (the engine's full scans are acceptance T01/T02) |
| persistence | ✅ | session B started with an empty store and fetched "E2E Poster" by name from `./library`; the passport records the import |
| editing | ✅ | session B: `set headline.content = "Made for\nevery day." keep everything else` → committed; changed paths: only `nodes.n-headline.content`; 0 frozen-path violations; **0 pixels changed outside the headline** against the approved baseline; requested edit verified in the render |

Session A also exposed a real defect: `annotate_scan.py` crashed on text nodes that had no measured baseline yet,
which is normal in the middle of a scan. Fixed in this change; the acceptance suite was re-run afterwards (below).

### Codex

codex-cli 0.160.1, isolated `CODEX_HOME`. Evidence: [host-discovery.json](evidence/2026-10-07/host-discovery.json).

| Route | Result | What was observed |
|---|---|---|
| skill folder `~/.agents/skills` | ✅ install, ✅ discovery | `codex debug prompt-input` (the exact input the model would get) lists `reverse-design` with its description |
| plugin, local marketplace | ✅ install, ✅ discovery | `codex plugin marketplace add` and `codex plugin add design-dna@design-dna-local` succeed; `codex plugin list` shows it installed and enabled at 2.1.0-dev; the prompt lists `design-dna:reverse-design` from the plugin cache |

Invocation, scan, persistence and editing: untested (no OpenAI sign-in).

### Gemini CLI

Gemini CLI 0.63.0.

| Route | Result | What was observed |
|---|---|---|
| skill folder `~/.gemini/skills` | ✅ install, ✅ discovery | `gemini skills list` shows `reverse-design [Enabled]` at that location |
| extension | ✅ install, ✅ discovery, ✅ uninstall | `gemini extensions validate` passes; install with `--consent` succeeds and the skill is listed from `extensions/design-dna/skills/`; `install.py uninstall --method extension` removes it |

Finding: besides `--consent`, Gemini CLI asks whether to trust a local extension folder and waits for an answer
even with no terminal attached. The installer therefore refuses to answer for the user: in a terminal you answer
it, and unattended runs need `--yes`, which sets `GEMINI_CLI_TRUST_WORKSPACE=true` for that one command.

### GitHub Copilot

GitHub Copilot CLI 1.0.92.

| Route | Result | What was observed |
|---|---|---|
| skill folder `~/.copilot/skills` | ✅ install, ✅ discovery | `copilot skill list` shows it under *Personal skills* |
| plugin (Agent Plugins 1.0) via a local marketplace | ✅ install, ✅ discovery, ✅ uninstall | `copilot plugin marketplace add` + `copilot plugin install design-dna@design-dna-local`; listed as a live plugin; its skill appears under *Plugin skills*; uninstall leaves *No plugins installed* |

Finding: installing a plugin directly from a local path works but prints a deprecation warning ("only
plugin@marketplace installs will be supported"), so the installer wraps the plugin in a local marketplace.

### OpenCode

OpenCode 1.18.35: `opencode debug skill` lists `reverse-design` at `~/.config/opencode/skills/reverse-design/SKILL.md`.
✅ install, ✅ discovery.

### ChatGPT

`design-dna-chatgpt-skill.zip` is built, holds one top-level `reverse-design/` folder, passes the Agent Skills rules
(name, folder match, description and compatibility lengths), stays far below the documented 50 MB / 500-file limits
(about 120 KB, 34 files), and carries `agents/openai.yaml` plus the hosted-sandbox notes. 🟡 install (partial:
built, not uploaded). Upload, discovery, invocation, scan, persistence and editing: untested (no ChatGPT Business,
Enterprise, Healthcare or Edu workspace).

### Claude apps

`design-dna-claude-skill.zip`: same checks as the ChatGPT package. 🟡 install (partial). The rest: untested.

### Cursor

The installer tests put the skill in `~/.cursor/skills` (the documented folder). 🟡 install (partial); the host
was not run.

### Windsurf

Installer tests: `~/.codeium/windsurf/skills` (user) and `.devin/skills` (project). 🟡 install (partial).

### Cline

Installer tests: `~/.cline/skills`. 🟡 install (partial).

### Roo Code

Installer tests: `~/.roo/skills`. 🟡 install (partial).

### Kiro

Installer tests: `~/.kiro/skills`. 🟡 install (partial).

### Junie (JetBrains)

Installer tests: `~/.junie/skills`. 🟡 install (partial).

### Goose

Installer tests: `~/.agents/skills`, the folder Goose recommends. 🟡 install (partial).

### Other Agent Skills hosts

`~/.agents/skills`: ✅ install (installer tests); 🟡 discovery: Codex discovers this folder (above); other hosts
that read it were not run.

### Instruction kit

`INSTRUCTIONS.md` is 4,511 characters (custom GPT limit 8,000), starts every answer with the instruction-only
label and forbids `measured`. 🟡 install (partial: built and checked, not pasted into a live assistant).

## Operating-system results

### Installer and packages

`python -m unittest discover -s hosts/tests -v`: every target installed in a throwaway home, dry run, project
scope, update, protection of edited and foreign folders, uninstall that keeps templates, doctor, the legacy
`install.sh`, every package's structure, and generated docs being current.

| OS | Result |
|---|---|
| Linux (Ubuntu 24.04, Python 3.13) | ✅ 15/15 tests |
| Windows, macOS | the `hosts` workflow runs the same tests on `windows-latest` and `macos-latest`; not run yet (it starts on the next push to `main` or pull request) |

### Engine

Host packaging does not change the engine, but this change carries two engine fixes: `annotate_scan.py` (found by
the Claude Code run above) and the library's tie-break between bundles exported in the same second (found when an
acceptance re-run crashed in T20 and cascaded into T21-T32). After both, the full suite on Linux with the
portable fonts: **run `20261007-005538`, 31/31 passed, 2 unverified** (T21: no second browser channel in the
container; T23: by design). Windows runs in the existing `acceptance` workflow. History:
[BUILD-REPORT](../BUILD-REPORT.md).

## Reproduce

```bash
python -m unittest discover -s hosts/tests -v                    # installer + packages (any OS)
npm install -g @openai/codex @google/gemini-cli opencode-ai @github/copilot
python hosts/tests/host_discovery.py --out host-discovery.json   # discovery in each host CLI, no sign-in needed
```

The Claude Code end-to-end check needs a signed-in Claude Code: install the skill, then run the two prompts
recorded in [claude-code-e2e.json](evidence/2026-10-07/claude-code-e2e.json) in two fresh sessions with separate
`DESIGN_DNA_HOME` folders and a shared library folder.
