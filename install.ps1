# Design DNA installer (Windows PowerShell 5.1+ / PowerShell 7)
# Copies the skill into ~/.claude/skills/reverse-design, installs Python dependencies, and checks the renderer.
# An existing installation is moved aside to reverse-design.bak-<timestamp>; nothing is deleted.
$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "skills\reverse-design"
$skills = Join-Path $HOME ".claude\skills"
$dest = Join-Path $skills "reverse-design"

New-Item -ItemType Directory -Force $skills | Out-Null
if (Test-Path $dest) {
    $bak = "$dest.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Move-Item $dest $bak
    Write-Host "Existing skill moved to $bak"
}
Copy-Item $src $dest -Recurse
Get-ChildItem $dest -Recurse -Directory -Filter __pycache__ | ForEach-Object { Remove-Item $_.FullName -Recurse -Force }
Write-Host "Skill installed -> $dest"

python -m pip install -r (Join-Path $dest "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

python (Join-Path $dest "scripts\capabilities.py")
Write-Host ""
Write-Host "If the renderer line says 'unavailable', install Google Chrome or run: python -m playwright install chromium"
Write-Host "Restart Claude Code, then ask: scan this design ..."
