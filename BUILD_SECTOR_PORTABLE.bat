@echo off
setlocal EnableExtensions

REM Backward-compatible alias for the canonical root BUILD.bat entry point.
set "SECTOR_CANONICAL_BUILD=%~dp0BUILD.bat"
if exist "%SECTOR_CANONICAL_BUILD%" goto :run

echo.
echo Sector portable build cannot start from an incomplete ZIP preview.
echo Choose "Extract All", then run BUILD.bat from the extracted top-level
echo Sector folder.
set "SECTOR_BUILD_RC=2"
goto :finish

:run
call "%SECTOR_CANONICAL_BUILD%"
set "SECTOR_BUILD_RC=%ERRORLEVEL%"

:finish
if not "%SECTOR_PORTABLE_NONINTERACTIVE%"=="1" goto :pause_for_user
if /I "%CI%"=="true" goto :finished
if "%CI%"=="1" goto :finished

:pause_for_user
if not exist "%SECTOR_CANONICAL_BUILD%" pause

:finished
exit /b %SECTOR_BUILD_RC%
