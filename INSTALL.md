# Installing Design DNA

## Requirements

| | Tested with | Minimum |
|---|---|---|
| Python | 3.12.10 | 3.10 |
| Packages | `requirements-lock.txt` (exact) | `requirements.txt` (minimums) |
| Renderer | Google Chrome 154.0.8037.93; Microsoft Edge 154 | any Chromium Playwright can drive; `python -m playwright install chromium` if neither browser is installed |
| OS | Windows 10 / 11 (local + GitHub Actions); Linux (Ubuntu 24.04, portable fonts) | macOS: untested |

## Pick your AI tool

Every supported tool, its install method and its guide: [README → Choose your AI tool](README.md#choose-your-ai-tool)
and [docs/hosts/](docs/hosts/COMPATIBILITY.md). ChatGPT and the Claude apps install by uploading a zip; local agents
install with `install.py`.

## The installer (local AI tools)

```bash
git clone https://github.com/OzyAcc/design-dna && cd design-dna
python install.py list                                  # targets, how each installs, what this machine has
python install.py install --target cursor,codex         # skill folders, user scope
python install.py install --target detected             # every tool found on this machine
python install.py install --target copilot --scope project --project ~/code/my-repo   # .github/skills in that repo
python install.py install --target codex --method plugin        # through the host's own package manager
python install.py install --target gemini-cli --method extension --from github   # no trust question
python install.py install --target copilot --method plugin --from github          # plugin@marketplace from GitHub
python install.py doctor                                # Python, packages, Chromium, store, every visible copy
python install.py update                                # refresh every copy the installer put in place
python install.py uninstall --target cursor             # only unmodified copies it installed
```

| Option | Effect |
|---|---|
| `--dry-run` | prints every change; writes nothing |
| `--scope user\|project`, `--project DIR` | user folders (default) or a project's folder |
| `--method skill\|plugin\|extension` | skill folder (default), or Codex/Copilot/Claude Code plugin, Gemini CLI extension |
| `--force` | a folder the installer did not create, or a copy with local edits, is moved to `~/design-dna/backups/` and replaced; without it the installer refuses |
| `--no-deps` | skip `pip install -r requirements.txt` |
| `--from local\|github`, `--ref` | plugin and extension methods: build from this checkout (default) or install from the GitHub repository at an optional branch or tag (Gemini CLI, Copilot, Claude Code) |
| `--yes` | unattended runs: answer a host CLI's confirmation for the package it just built (Gemini CLI asks to trust the extension folder) |

Each installed copy carries `.design-dna-install.json` (version, commit, host, every file's sha256). That is how
`update` and `uninstall` know a copy is theirs and unmodified. Templates and bundles in `~/design-dna` are never
touched. The old entry points still work: `./install.sh` and `.\install.ps1` install for Claude Code by default
and accept the same options (`./install.sh --target cursor`).

## Claude Code plugin

```text
/plugin marketplace add OzyAcc/design-dna
/plugin install design-dna@design-dna
```

Then install the Python packages once: `python -m pip install -r requirements.txt`.

To reproduce the tested environment exactly, also run:

```bash
python -m pip install -r requirements-lock.txt
```

## Check it

```bash
python install.py doctor --target <your tool>
```

`Renderer` should name a browser and version. If it says `unavailable`, install Chrome or run
`python -m playwright install chromium`.

Restart your AI tool, then ask, for example: *"Scan poster.png and save it as 'Spring Launch'."*

## Run the acceptance suite (optional, ~30 minutes)

```bash
python skills/reverse-design/tests/run_acceptance.py
```

The suite runs in an isolated store (`DESIGN_DNA_ACCEPTANCE_DIR`, default `~/design-dna/acceptance/<timestamp>`)
and writes `report.md` + `report.json` with every input and output retained. A single test: `--only 15`.

Fonts: on Windows with Arial and Georgia installed the suite uses those system fonts (the verified 1.0.0 / 2.0.0
configuration). Everywhere else it uses the open-licensed fonts vendored in
[`skills/reverse-design/tests/fonts/`](skills/reverse-design/tests/fonts/README.md), so Linux and macOS need no
extra font packages. `DESIGN_DNA_FONTSET=portable` or `=windows` forces a set; the report records which one ran.
The renderer-drift test (T21) needs a second browser channel besides the pinned one (Chrome, Edge or Playwright's
Chromium); with only one installed it is reported as unverified.

## Where things live

| | Default | Override |
|---|---|---|
| Skill | the tool's skill folder: `python install.py list` | `--scope project --project DIR` |
| Working store (cache) | `~/design-dna` | `DESIGN_DNA_HOME` |
| Persistent templates | wherever you `export-template … to <folder>` | |
| Renderer channel | Chrome → Edge → bundled Chromium; pinned per template after its baseline | `DESIGN_DNA_BROWSER=chrome\|msedge\|chromium` (a pinned template still refuses a different one) |

## Uninstall

`python install.py uninstall --target <tool>` (add `--method plugin` or `--method extension` for those routes).
Uploaded skills (ChatGPT, Claude apps) are removed in that tool's settings. Templates in `~/design-dna` and any
exported bundles are untouched.
