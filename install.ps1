# Design DNA installer (Windows PowerShell 5.1+ / PowerShell 7): a wrapper around install.py.
#   .\install.ps1                          Claude Code (as before)
#   .\install.ps1 --target cursor,codex    other AI tools: python install.py list shows them all
#   .\install.ps1 --dry-run                show what would change
# Without --target it installs for Claude Code. An existing copy is moved to ~\design-dna\backups first (as before),
# so Claude Code never loads two skills with the same name; templates in ~\design-dna are never touched.
$ErrorActionPreference = "Stop"
$installer = Join-Path $PSScriptRoot "install.py"
$passed = @($args)
if (-not ($passed | Where-Object { $_ -like "--target*" })) { $passed = @("--target", "claude-code") + $passed }

python $installer install --force @passed
if ($LASTEXITCODE -ne 0) { throw "install failed (exit $LASTEXITCODE)" }
$target = "claude-code"
for ($i = 0; $i -lt $passed.Count; $i++) {
    if ($passed[$i] -eq "--target" -and $i + 1 -lt $passed.Count) { $target = $passed[$i + 1] }
    elseif ($passed[$i] -like "--target=*") { $target = $passed[$i].Substring(9) }
}
python $installer doctor --target $target
Write-Host ""
Write-Host "If the renderer line says 'unavailable', install Google Chrome or run: python -m playwright install chromium"
Write-Host "Restart your AI tool, then ask: scan this design ..."
