@echo off
setlocal
set "MCD_ROOT=%~dp0"
set "MSYSTEM=MSYS"
set "CHERE_INVOKING=1"
if not exist "%MCD_ROOT%.deps\msys64\usr\bin\bash.exe" (
  echo Run powershell -ExecutionPolicy Bypass -File tools\setup.ps1 first.
  exit /b 1
)
"%MCD_ROOT%.deps\msys64\usr\bin\bash.exe" --login "%MCD_ROOT%tools\mcd.sh" %*
exit /b %ERRORLEVEL%
