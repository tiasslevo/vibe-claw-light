@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
set "VCL_EXIT=%ERRORLEVEL%"
if not "%VCL_EXIT%"=="0" echo L installation a echoue. Consulte le message ci-dessus et docs\INSTALLATION.md.
if not defined VCL_NO_PAUSE pause
exit /b %VCL_EXIT%
