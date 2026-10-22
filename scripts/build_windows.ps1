param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $IsWindows) { throw "Run this build on Windows with PowerShell 7." }

function Invoke-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
function Invoke-App([string]$Executable, [string[]]$Arguments) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
    if (-not $process.WaitForExit(180000)) {
        $process.Kill()
        throw "Application check exceeded three minutes: $Executable"
    }
    if ($process.ExitCode -ne 0) { throw "Application check failed: $Executable ($($process.ExitCode))" }
}

Invoke-Checked { & $Python -c "import struct; assert struct.calcsize('P') == 8, 'Use 64-bit Python'" }
Invoke-Checked { & $Python -m venv .venv-build-windows }
$BuildPython = (Resolve-Path ".venv-build-windows/Scripts/python.exe").Path
Invoke-Checked { & $BuildPython -m pip install -r requirements-build-windows.txt }
New-Item -ItemType Directory -Force build/windows | Out-Null
Invoke-Checked { & $BuildPython -m pytest -q --junitxml=build/windows/test-results.xml }
Invoke-Checked { & $BuildPython scripts/build_windows_icon.py }
Invoke-Checked { & $BuildPython -m PyInstaller --clean --noconfirm CantusPDFWindows.spec }
$App = (Resolve-Path "dist/CantusPDF-Windows/CantusPDF.exe").Path
Invoke-App $App @("--self-test", "build/windows/release-check.json")

$Compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Compiler)) { throw "Install Inno Setup 6 before building the installer." }
$Version = & $BuildPython -c "from preview_cleaner import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw "Could not read app version." }
Invoke-Checked { & $Compiler "/DAppVersion=$Version" packaging/windows.iss }

# Install into an isolated test directory, never over the user's normal app.
$InstallDir = Join-Path (Get-Location) "build/windows/installed"
$Installer = (Resolve-Path "dist/CantusPDF-Windows-x64-Setup.exe").Path
Invoke-App $Installer @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/TASKS=", "/BuildCheck=Smoke", "/GROUP=Cantus PDF Build Check", "/DIR=`"$InstallDir`"")
Invoke-App (Join-Path $InstallDir "CantusPDF.exe") @("--self-test", "build/windows/installed-check.json")
Invoke-App (Join-Path $InstallDir "unins000.exe") @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
if (Test-Path (Join-Path $InstallDir "CantusPDF.exe")) { throw "Uninstall left the application executable behind." }

Compress-Archive -Path dist/CantusPDF-Windows -DestinationPath dist/CantusPDF-Windows-x64.zip -Force
Invoke-Checked { & $BuildPython scripts/record_windows_release.py }
Write-Host "Built and checked: dist/CantusPDF-Windows-x64-Setup.exe"
