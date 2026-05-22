$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Write-Host "Installing build dependencies..."
& $Python -m pip install -r (Join-Path $ProjectRoot "requirements.txt") pyinstaller

Write-Host "Building MacroRecorder.exe..."
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name MacroRecorder `
    (Join-Path $ProjectRoot "macro_recorder.py")

Write-Host ""
Write-Host "Done. EXE path:"
Write-Host (Join-Path $ProjectRoot "dist\MacroRecorder.exe")
