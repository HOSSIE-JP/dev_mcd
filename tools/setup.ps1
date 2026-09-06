[CmdletBinding()]
param([switch]$SkipUpdate, [switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
# Windows PowerShell's per-chunk progress rendering slows large downloads.
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path $PSScriptRoot -Parent
if ($projectRoot -match '[^\x21-\x7E]' -or $projectRoot.Contains("'")) {
    throw 'MSYS2 and GNU configure require an ASCII path without spaces, e.g. D:\homebrew\dev_mcd.'
}
$deps = Join-Path $projectRoot '.deps'
$msys = Join-Path $deps 'msys64'
$bash = Join-Path $msys 'usr\bin\bash.exe'
New-Item -ItemType Directory -Force $deps | Out-Null
$logs = Join-Path $deps 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$bootstrapLog = Join-Path $logs 'bootstrap.log'
function Write-Stage([string]$Message) {
    $line = ('{0:u} {1}' -f [DateTime]::UtcNow, $Message)
    Write-Host $line
    Add-Content -Path $bootstrapLog -Value $line -Encoding UTF8
}
if (!(Test-Path $bash)) {
    $archive = Join-Path $deps 'msys2-base-x86_64-20260611.tar.xz'
    $url = 'https://github.com/msys2/msys2-installer/releases/download/2026-06-11/msys2-base-x86_64-20260611.tar.xz'
    $expected = 'a2d047e8ee213c3c6a49a8de427eb1069df12207c0422ff1b3cbb5c905c34221'
    if (!(Test-Path $archive)) {
        Write-Stage 'Downloading portable MSYS2 (timeout: 300 seconds).'
        # Basic parsing downloads bytes without the PowerShell 5.1 HTML/script
        # confirmation prompt introduced in the December 2025 security update.
        $partial = $archive + '.part'
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 300 -Uri $url -OutFile $partial
        Move-Item -Path $partial -Destination $archive
    }
    Write-Stage 'Checking the MSYS2 archive SHA-256.'
    if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'MSYS2 archive checksum mismatch. Remove the cached archive and run setup again.'
    }
    Write-Stage 'Extracting portable MSYS2.'
    & tar.exe -xf $archive -C $deps
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $bash)) { throw 'MSYS2 extraction failed.' }
}
$oldMSYSTEM = $env:MSYSTEM
$oldChere = $env:CHERE_INVOKING
try {
    $env:MSYSTEM = 'MSYS'
    $env:CHERE_INVOKING = '1'
    Write-Stage 'Initializing the project MSYS2 shell.'
    & $bash --login -c 'true'
    if ($LASTEXITCODE -ne 0) { throw 'MSYS2 first-run initialization failed.' }
    if (!$SkipUpdate) {
        Write-Stage 'Updating MSYS2 packages.'
        # Core updates may end their process; perform the full update in a fresh shell.
        & $bash --login -c 'pacman -Syu --noconfirm'
        if ($LASTEXITCODE -ne 0) { throw 'MSYS2 update failed; close its shells and rerun setup.ps1.' }
        & $bash --login -c 'pacman -Syu --noconfirm'
        if ($LASTEXITCODE -ne 0) { throw 'MSYS2 package update failed.' }
    }
    Write-Stage 'Installing native host tools and fetching pinned dependencies.'
    if ($PrepareOnly) {
        & $bash --login -c 'cd -- "$1" && bash tools/setup-msys2.sh --prepare-only' bash ($projectRoot.Replace('\','/'))
    } else {
        & $bash --login -c 'cd -- "$1" && bash tools/setup-msys2.sh' bash ($projectRoot.Replace('\','/'))
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cross-toolchain setup failed. See .deps/logs.' }
} finally {
    $env:MSYSTEM = $oldMSYSTEM
    $env:CHERE_INVOKING = $oldChere
}
if ($PrepareOnly) {
    Write-Stage 'Host preparation complete. Cross-compiler build is a separate CI step.'
} else {
    Write-Stage 'Setup complete. Run .\mcd.cmd build, then .\mcd.cmd doctor.'
}
