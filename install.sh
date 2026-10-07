#!/usr/bin/env bash
# Design DNA installer (macOS / Linux / Git Bash): a wrapper around install.py.
#   ./install.sh                         Claude Code (as before)
#   ./install.sh --target cursor,codex   other AI tools: python3 install.py list shows them all
#   ./install.sh --dry-run               show what would change
# Without --target it installs for Claude Code. An existing copy is moved to ~/design-dna/backups first (as before),
# so Claude Code never loads two skills with the same name; templates in ~/design-dna are never touched.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
py="$(command -v python3 || command -v python)"
args=("$@")
case " $* " in *" --target "*|*" --target="*) ;; *) args=(--target claude-code "${args[@]}") ;; esac
"$py" "$here/install.py" install --force "${args[@]}"
target=claude-code
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in --target) target="${args[$((i + 1))]}" ;; --target=*) target="${args[$i]#--target=}" ;; esac
done
"$py" "$here/install.py" doctor --target "$target" || true
echo
echo "If the renderer line says 'unavailable', install Google Chrome or run: $py -m playwright install chromium"
echo "Off Windows, the acceptance suite uses the open-licensed fonts in tests/fonts (DESIGN_DNA_FONTSET=portable)."
echo "Restart your AI tool, then ask: scan this design ..."
