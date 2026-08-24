# One-shot setup for a fresh Windows machine.
#
# Save this file as UTF-8 *with* a byte-order mark. It contains Hebrew, and
# Windows PowerShell 5.1 reads a BOM-less script as ANSI, which turns those
# characters into mojibake and the script into a parse error.
#
# Safe to run more than once: it skips anything already done and never
# overwrites a config file that has been filled in.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say([string]$text) { Write-Host $text -ForegroundColor Cyan }
function Good([string]$text) { Write-Host "  $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "  $text" -ForegroundColor Yellow }

Say "`n1. Looking for Python"

$python = $null
foreach ($candidate in @("py -3.11", "py -3", "python")) {
    $parts = $candidate.Split(" ")
    $exe = Get-Command $parts[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    try {
        $version = & $parts[0] $parts[1..($parts.Length - 1)] --version 2>&1
    } catch { continue }
    if ($version -match "Python (\d+)\.(\d+)") {
        if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)) {
            $python = $candidate
            Good "$version  ($candidate)"
            break
        }
    }
}

if (-not $python) {
    Warn "No Python 3.11 or later found."
    Warn "Install it from https://www.python.org/downloads/ and tick"
    Warn "'Add python.exe to PATH' on the first screen, then run this again."
    exit 1
}

Say "`n2. Creating the virtual environment"

if (Test-Path ".venv\Scripts\python.exe") {
    Good "Already exists, reusing it."
} else {
    $parts = $python.Split(" ")
    & $parts[0] $parts[1..($parts.Length - 1)] -m venv .venv
    Good "Created .venv"
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Say "`n3. Installing the packages (this takes a couple of minutes)"

& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Warn "Installation failed. The output above says why."
    exit 1
}
Good "Installed."

Say "`n4. Creating the settings files"

if (Test-Path ".env") {
    Good ".env already exists, left alone."
} else {
    Copy-Item ".env.example" ".env"
    Warn "Created .env - you must open it and paste the Gemini API key after GEMINI_API_KEY="
}

foreach ($pair in @(
    @{ Example = "config\mailbox.example.yaml"; Real = "config\mailbox.yaml" },
    @{ Example = "config\matters.example.yaml"; Real = "config\matters.yaml" }
)) {
    if (Test-Path $pair.Real) {
        Good "$($pair.Real) already exists, left alone."
    } else {
        Copy-Item $pair.Example $pair.Real
        Warn "Created $($pair.Real) - open it and replace the example values."
    }
}

Say "`n5. Putting the icons on the desktop"

$icon = Join-Path $PSScriptRoot "assets\agent.ico"
$stopIcon = Join-Path $PSScriptRoot "assets\stop.ico"
if (-not (Test-Path $icon) -or -not (Test-Path $stopIcon)) {
    & $venvPython (Join-Path $PSScriptRoot "tools\make_icon.py") | Out-Null
}

$desktop = [Environment]::GetFolderPath("Desktop")

function New-DesktopIcon {
    param(
        [string]$AsciiName,
        [string]$HebrewName,
        [string]$Target,
        [string]$Arguments,
        [string]$Description,
        [string]$Icon
    )

    # WScript.Shell saves through an ANSI interface, so a Hebrew path arrives as
    # question marks and the save fails outright. Write it under an ASCII name
    # and rename with the .NET file API, which is Unicode all the way down.
    $ascii = Join-Path $desktop "$AsciiName.lnk"
    $hebrew = Join-Path $desktop "$HebrewName.lnk"

    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($ascii)
        $shortcut.TargetPath = $Target
        if ($Arguments) { $shortcut.Arguments = $Arguments }
        $shortcut.WorkingDirectory = $PSScriptRoot
        $shortcut.Description = $Description
        if (Test-Path $Icon) { $shortcut.IconLocation = $Icon }
        # Minimised: any console window is only the host process, and having it
        # open in her face invites closing it and wondering what broke.
        $shortcut.WindowStyle = 7
        $shortcut.Save()

        try {
            if ([System.IO.File]::Exists($hebrew)) { [System.IO.File]::Delete($hebrew) }
            [System.IO.File]::Move($ascii, $hebrew)
            Good "Created the '$HebrewName' icon."
        } catch {
            Good "Created the icon (named $AsciiName)."
        }
        return $true
    } catch {
        Warn "Could not create the '$HebrewName' icon: $($_.Exception.Message)"
        return $false
    }
}

$made = New-DesktopIcon -AsciiName "rotem-agent" -HebrewName "סוכן הטיוטות" `
    -Target (Join-Path $PSScriptRoot "dashboard.bat") `
    -Description "Opens the draft agent dashboard" -Icon $icon
if (-not $made) {
    Warn "You can still start it by double-clicking dashboard.bat in this folder."
}

# Points at the interpreter rather than at stop.bat, so nothing flashes on screen
# and the answer arrives as a message box. pythonw has no console at all, which
# is also why the Hebrew in it is readable.
$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
$stopTarget = if (Test-Path $pythonw) { $pythonw } else { Join-Path $PSScriptRoot "stop.bat" }
$stopArgs = if (Test-Path $pythonw) { "-m rotem_agent.cli stop --dialog" } else { "" }

$made = New-DesktopIcon -AsciiName "rotem-agent-stop" -HebrewName "כיבוי הסוכן" `
    -Target $stopTarget -Arguments $stopArgs `
    -Description "Stops the draft agent" -Icon $stopIcon
if (-not $made) {
    Warn "You can still stop it by double-clicking stop.bat in this folder."
}

Say "`n6. Checking everything"

& $venvPython -m rotem_agent.cli doctor
$doctor = $LASTEXITCODE

Write-Host ""
if ($doctor -eq 0) {
    Say "Setup is complete."
    Write-Host "Double-click 'סוכן הטיוטות' on the desktop to open the dashboard,"
    Write-Host "or 'כיבוי הסוכן' to turn the agent off without it."
    Write-Host "Or try a draft against the sample email first:"
    Write-Host "  .venv\Scripts\python.exe -m rotem_agent.cli draft samples\anna_reentry_visa.eml"
} else {
    Say "Setup is nearly done."
    Write-Host "Fix the FAIL lines above, then re-check with:"
    Write-Host "  .venv\Scripts\python.exe -m rotem_agent.cli doctor"
}
