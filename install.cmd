@echo off
setlocal
rem PowerShell 7 may pass incompatible modules through Codex/cmd.exe.
rem Clear only this child environment; Windows PowerShell rebuilds its paths.
set "PSModulePath="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
set "VCL_EXIT=%ERRORLEVEL%"
if not "%VCL_EXIT%"=="0" echo L installation a echoue. Consulte le message ci-dessus et docs\INSTALLATION.md.
if not defined VCL_NO_PAUSE pause
exit /b %VCL_EXIT%
