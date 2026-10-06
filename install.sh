#!/usr/bin/env bash
# Design DNA installer (macOS / Linux / Git Bash)
# Copies the skill into ~/.claude/skills/reverse-design, installs Python dependencies, and checks the renderer.
# An existing installation is moved to <store>/backups/reverse-design-<timestamp>; nothing is deleted.
# (Backups go outside ~/.claude/skills so Claude Code never loads two skills with the same name.)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="$HOME/.claude/skills/reverse-design"
store="${DESIGN_DNA_HOME:-$HOME/design-dna}"
mkdir -p "$HOME/.claude/skills"
if [ -e "$dest" ]; then
  mkdir -p "$store/backups"
  bak="$store/backups/reverse-design-$(date +%Y%m%d-%H%M%S)"
  mv "$dest" "$bak"
  echo "Existing skill moved to $bak"
fi
cp -R "$here/skills/reverse-design" "$dest"
find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "Skill installed -> $dest"

python3 -m pip install -r "$dest/requirements.txt"
python3 "$dest/scripts/capabilities.py" || true
echo
echo "If the renderer line says 'unavailable', install Google Chrome or run: python3 -m playwright install chromium"
echo "Note: the acceptance suite uses Windows system fonts (Arial, Georgia, ...); the engine itself is cross-platform."
echo "Restart Claude Code, then ask: scan this design ..."
