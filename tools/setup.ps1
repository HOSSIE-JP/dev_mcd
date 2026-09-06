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
    if (Test-Path $msys) { throw 'Incomplete .deps/msys64 exists. Move it aside and rerun setup.ps1.' }
    $archive = Join-Path $deps 'msys2-base-x86_64-20260611.sfx.exe'
    $url = 'https://github.com/msys2/msys2-installer/releases/download/2026-06-11/msys2-base-x86_64-20260611.sfx.exe'
    $expected = 'c105946e64e08f099ac0e4647461ce762b95333ad211777666476a9a41451d65'
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
    Write-Stage 'Extracting the official portable MSYS2 self-extracting package.'
    # Match the upstream MSYS2 CI action. Avoid Windows tar implementations
    # which can stall on .tar.xz or interpret drive letters as remote paths.
    $unpack = Join-Path $deps 'msys2-unpack'
    New-Item -ItemType Directory -Force $unpack | Out-Null
    $extractProcess = Start-Process -FilePath $archive -ArgumentList '-y' `
        -WorkingDirectory $unpack -NoNewWindow -Wait -PassThru
    if ($extractProcess.ExitCode -ne 0) { throw 'MSYS2 extraction failed.' }
    $unpackedRoot = Join-Path $unpack 'msys64'
    if (!(Test-Path (Join-Path $unpackedRoot 'usr\bin\bash.exe'))) { throw 'MSYS2 archive layout mismatch.' }
    Move-Item -Path $unpackedRoot -Destination $msys
}
# The upstream first-start script allows key-server refresh failures, but has
# no time limit. Bound that optional network operation; retain key population,
# package signature verification, and the subsequent full package update.
$keyPost = Join-Path $msys 'etc\post-install\07-pacman-key.post'
if (Test-Path $keyPost) {
    $content = [IO.File]::ReadAllText($keyPost)
    $bounded = $content.Replace('    /usr/bin/pacman-key --refresh-keys || true',
        '    /usr/bin/timeout --kill-after=5s 60s /usr/bin/pacman-key --refresh-keys || true')
    if ($bounded -ne $content) {
        Write-Stage 'Limiting optional first-start key-server refresh to 60 seconds.'
        [IO.File]::WriteAllText($keyPost, $bounded, [Text.UTF8Encoding]::new($false))
    }
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
