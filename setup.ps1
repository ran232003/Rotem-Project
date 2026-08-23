# One-shot setup for a fresh Windows machine.
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

Say "`n5. Checking everything"

& $venvPython -m rotem_agent.cli doctor
$doctor = $LASTEXITCODE

Write-Host ""
if ($doctor -eq 0) {
    Say "Setup is complete."
    Write-Host "Try a draft against the sample email:"
    Write-Host "  .venv\Scripts\python.exe -m rotem_agent.cli draft samples\anna_reentry_visa.eml"
} else {
    Say "Setup is nearly done."
    Write-Host "Fix the FAIL lines above, then re-check with:"
    Write-Host "  .venv\Scripts\python.exe -m rotem_agent.cli doctor"
}
