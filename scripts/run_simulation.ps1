# Runs the full ANSYS analysis with the GUI visible and captures screenshots of each step.
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\run_simulation.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_simulation.ps1 -AnsysRoot "C:\Program Files\ANSYS Inc\v261"
param([string]$AnsysRoot = "C:\Program Files\ANSYS Inc\ANSYS Student\v261")

$repo = Split-Path -Parent $PSScriptRoot
$runwb2 = Join-Path $AnsysRoot "Framework\bin\Win64\RunWB2.exe"
if (-not (Test-Path $runwb2)) { throw "RunWB2.exe not found at $runwb2 - pass -AnsysRoot" }

$shots = Join-Path $repo "data\screenshots_raw"
Remove-Item "$shots\ALL_DONE.flag" -ErrorAction SilentlyContinue
$env:TENSILE_REPO = $repo

Start-Process powershell -WindowStyle Hidden -ArgumentList @(
  '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'screenshot_watcher.ps1'), '-ShotsDir', $shots)
Start-Process -FilePath $runwb2 -ArgumentList @('-I', '-R', "`"$(Join-Path $PSScriptRoot 'workbench_journal.py')`"")

Write-Host "ANSYS is running (about 10 minutes). Do not use the mouse or keyboard on the ANSYS window."
Write-Host "When it finishes, run:  python scripts\postprocess.py"
