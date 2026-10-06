# Installing Design DNA

## Requirements

| | Tested with | Minimum |
|---|---|---|
| Python | 3.12.10 | 3.10 |
| Packages | `requirements-lock.txt` (exact) | `requirements.txt` (minimums) |
| Renderer | Google Chrome 154.0.8037.93; Microsoft Edge 154 | any Chromium Playwright can drive; `python -m playwright install chromium` if neither browser is installed |
| OS | Windows 10 / 11 (local + GitHub Actions) | macOS / Linux: the engine runs; the acceptance suite uses the portable font set (below) |

## Option 1: Claude Code plugin

```text
/plugin marketplace add OzyAcc/design-dna
/plugin install design-dna@design-dna
```

Then install the Python packages once:

```bash
python -m pip install -r requirements.txt
```

## Option 2: Copy the skill (from a clone or the release ZIP)

Windows PowerShell:

```powershell
.\install.ps1
```

macOS / Linux / Git Bash:

```bash
./install.sh
```

The installer:

1. Copies `skills/reverse-design` to `~/.claude/skills/reverse-design`.
2. Moves any existing copy to `~/design-dna/backups/reverse-design-<timestamp>`. Nothing is deleted, and nothing
   is left inside the skills folder that Claude Code would load twice.
3. Installs `requirements.txt` and prints the capability report.

To reproduce the tested environment exactly, also run:

```bash
python -m pip install -r requirements-lock.txt
```

## Check it

```bash
python ~/.claude/skills/reverse-design/scripts/capabilities.py
```

`renderer` should name a browser and version. If it says `unavailable`, install Chrome or run
`python -m playwright install chromium`.

Restart Claude Code, then ask, for example: *"Scan poster.png and save it as 'Spring Launch'."*

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
| Skill | `~/.claude/skills/reverse-design` | |
| Working store (cache) | `~/design-dna` | `DESIGN_DNA_HOME` |
| Persistent templates | wherever you `export-template … to <folder>` | |
| Renderer channel | Chrome → Edge → bundled Chromium; pinned per template after its baseline | `DESIGN_DNA_BROWSER=chrome\|msedge\|chromium` (a pinned template still refuses a different one) |

## Uninstall

Move `~/.claude/skills/reverse-design` out of the skills folder. Templates in `~/design-dna` and any exported
bundles are untouched.
