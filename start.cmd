@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if exist "%~dp0.venv\Scripts\python.exe" goto use_python
if defined UV_INSTALL_DIR if exist "%UV_INSTALL_DIR%\uv.exe" set "VCL_UV=%UV_INSTALL_DIR%\uv.exe"
if not defined VCL_UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "VCL_UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined VCL_UV for /f "delims=" %%U in ('where uv.exe 2^>nul') do if not defined VCL_UV set "VCL_UV=%%U"
if defined VCL_UV goto use_uv
echo Environnement introuvable. Lance install.cmd une premiere fois.
set "VCL_EXIT=1"
goto done
:use_python
"%~dp0.venv\Scripts\python.exe" "%~dp0run.py" start
set "VCL_EXIT=%ERRORLEVEL%"
goto done
:use_uv
"%VCL_UV%" run --python 3.11 "%~dp0run.py" start
set "VCL_EXIT=%ERRORLEVEL%"
:done
popd
if not "%VCL_EXIT%"=="0" echo Demarrage impossible. Consulte docs\INSTALLATION.md.
if not defined VCL_NO_PAUSE pause
exit /b %VCL_EXIT%
