@echo off
REM ===========================================================================
REM Build an unsigned Sector QA package from authenticated exact source.
REM
REM This internal inspection wrapper is deliberately named build_qa.bat so it
REM cannot be confused with the user-facing redistributable BUILD.bat at the
REM source root. The output is for static QA inspection only. Never launch, zip
REM or distribute it; signed releases use the authorised signing path.
REM ===========================================================================

setlocal
echo WARNING: UNSIGNED QA PACKAGE ONLY.
echo Do not launch, zip or distribute the generated artifact.
echo.
echo Building Sector.exe for static QA inspection.
echo This can take a few minutes...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo QA build FAILED with exit code %RC%.
) else (
    echo Unsigned QA build complete in the unique path printed above.
    echo Do not launch, zip or distribute this artifact.
)
echo.
pause
exit /b %RC%
