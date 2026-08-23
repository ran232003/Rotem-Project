# Carries a previous install's private files into this freshly unzipped copy,
# then runs setup.ps1.
#
# For people who downloaded a ZIP rather than cloning. Six things never live in
# the repository, because they hold either secrets or privileged material, so a
# new download does not contain them and copying them by hand is easy to get
# wrong. Missing `state` is the expensive mistake: it records which emails have
# already been answered, and without it the agent drafts second replies to mail
# it has already dealt with.
#
# ASCII only and no Hebrew, so this parses under Windows PowerShell whether or
# not the file keeps a byte-order mark.
#
# Run it from inside the NEW folder:
#
#   powershell -ExecutionPolicy Bypass -File update.ps1 -From "C:\Users\you\Documents\old-copy"

param(
    [Parameter(Mandatory = $true)]
    [string]$From,

    # Copies nothing, just reports what it would do.
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say([string]$text) { Write-Host $text -ForegroundColor Cyan }
function Good([string]$text) { Write-Host "  $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "  $text" -ForegroundColor Yellow }
function Bad([string]$text) { Write-Host "  $text" -ForegroundColor Red }

$old = try { (Resolve-Path -LiteralPath $From).Path } catch { $null }
if (-not $old) {
    Bad "No folder at '$From'."
    exit 1
}
if ($old -eq $PSScriptRoot) {
    Bad "That is this folder. Point -From at the OLD copy."
    exit 1
}
if (-not (Test-Path (Join-Path $old "rotem_agent"))) {
    Bad "'$old' does not look like a copy of this project (no rotem_agent folder)."
    exit 1
}

Say "`nCarrying settings over from:"
Write-Host "  $old"

# Single files first, then whole folders. Only what git deliberately ignores.
$files = @(".env", "config\mailbox.yaml", "config\matters.yaml")
$folders = @("state", "clients")

$copied = 0
$skipped = 0
$absent = 0
$verb = if ($DryRun) { "would be copied" } else { "copied" }

Say "`nSettings"
foreach ($rel in $files) {
    $source = Join-Path $old $rel
    $target = Join-Path $PSScriptRoot $rel
    if (-not (Test-Path $source)) {
        Warn "$rel was not in the old copy either, skipping."
        $absent++
        continue
    }
    if (Test-Path $target) {
        # Not overwritten, so running this twice cannot undo an edit made since.
        Warn "$rel already here, left alone."
        $skipped++
        continue
    }
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Copy-Item -LiteralPath $source -Destination $target
    }
    Good "$rel $verb."
    $copied++
}

Say "`nHistory and documents"
foreach ($rel in $folders) {
    $source = Join-Path $old $rel
    if (-not (Test-Path $source)) {
        Warn "$rel was not in the old copy, skipping."
        $absent++
        continue
    }
    $items = Get-ChildItem -LiteralPath $source -Recurse -File -ErrorAction SilentlyContinue
    if (-not $items) {
        Warn "$rel was empty, nothing to carry."
        continue
    }
    foreach ($item in $items) {
        $relative = $item.FullName.Substring($source.Length).TrimStart("\")
        $target = Join-Path (Join-Path $PSScriptRoot $rel) $relative
        if (Test-Path $target) {
            $skipped++
            continue
        }
        if (-not $DryRun) {
            New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
            Copy-Item -LiteralPath $item.FullName -Destination $target
        }
        $copied++
    }
    Good "$rel done."
}

Write-Host ""
Say "$copied file(s) $verb, $skipped already present, $absent thing(s) not found."

if ($DryRun) {
    Write-Host ""
    Warn "Dry run: nothing was actually copied. Run again without -DryRun."
    exit 0
}

# The ledger is the one whose absence causes real harm, so it is called out by
# name rather than left in the totals.
if (-not (Test-Path (Join-Path $PSScriptRoot "state\ledger.json"))) {
    Write-Host ""
    Warn "No state\ledger.json came across."
    Warn "The agent will not know which emails it has already answered, and may"
    Warn "draft a second reply to each of them. Check the old folder for it"
    Warn "before turning the agent on."
}

Say "`nRunning setup"
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1")
