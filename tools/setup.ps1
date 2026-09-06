[CmdletBinding()]
param([switch]$SkipUpdate)
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
if (!(Test-Path $bash)) {
    $archive = Join-Path $deps 'msys2-base-x86_64-20260611.tar.xz'
    $url = 'https://github.com/msys2/msys2-installer/releases/download/2026-06-11/msys2-base-x86_64-20260611.tar.xz'
    $expected = 'a2d047e8ee213c3c6a49a8de427eb1069df12207c0422ff1b3cbb5c905c34221'
    if (!(Test-Path $archive)) { Invoke-WebRequest -Uri $url -OutFile $archive }
    if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'MSYS2 archive checksum mismatch. Remove the cached archive and run setup again.'
    }
    & tar.exe -xf $archive -C $deps
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $bash)) { throw 'MSYS2 extraction failed.' }
}
$oldMSYSTEM = $env:MSYSTEM
$oldChere = $env:CHERE_INVOKING
try {
    $env:MSYSTEM = 'MSYS'
    $env:CHERE_INVOKING = '1'
    & $bash --login -c 'true'
    if ($LASTEXITCODE -ne 0) { throw 'MSYS2 first-run initialization failed.' }
    if (!$SkipUpdate) {
        # Core updates may end their process; perform the full update in a fresh shell.
        & $bash --login -c 'pacman -Syu --noconfirm'
        if ($LASTEXITCODE -ne 0) { throw 'MSYS2 update failed; close its shells and rerun setup.ps1.' }
        & $bash --login -c 'pacman -Syu --noconfirm'
        if ($LASTEXITCODE -ne 0) { throw 'MSYS2 package update failed.' }
    }
    & $bash --login -c 'cd -- "$1" && bash tools/setup-msys2.sh' bash ($projectRoot.Replace('\','/'))
    if ($LASTEXITCODE -ne 0) { throw 'Cross-toolchain setup failed. See .deps/logs.' }
} finally {
    $env:MSYSTEM = $oldMSYSTEM
    $env:CHERE_INVOKING = $oldChere
}
Write-Host 'Setup complete. Run .\mcd.cmd build, then .\mcd.cmd doctor.'
