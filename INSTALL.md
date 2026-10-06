# Installing Design DNA

## Requirements

| | Tested with | Minimum |
|---|---|---|
| Python | 3.12.10 | 3.10 |
| Packages | `requirements-lock.txt` (exact) | `requirements.txt` (minimums) |
| Renderer | Google Chrome 154.0.8037.93; Microsoft Edge 154 | any Chromium Playwright can drive; `python -m playwright install chromium` if neither browser is installed |
| OS | Windows 10 / 11 (local + GitHub Actions) | macOS / Linux run the engine; the acceptance fixtures need Windows system fonts |

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

## Run the acceptance suite (optional, ~30 minutes on Windows)

```bash
python skills/reverse-design/tests/run_acceptance.py
```

The suite runs in an isolated store (`DESIGN_DNA_ACCEPTANCE_DIR`, default `~/design-dna/acceptance/<timestamp>`)
and writes `report.md` + `report.json` with every input and output retained. A single test: `--only 15`.

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
