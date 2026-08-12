@echo off
setlocal EnableExtensions

REM Compatibility entry point for users who expect packaging\build.bat.
REM The redistributable build is canonical at the source root as BUILD.bat.
set "SECTOR_CANONICAL_BUILD=%~dp0..\BUILD.bat"
if exist "%SECTOR_CANONICAL_BUILD%" goto :run

echo.
echo Sector portable build cannot start from an incomplete ZIP preview.
echo.
echo Windows extracted only packaging\build.bat, without the rest of Sector.
echo Return to the complete official source ZIP and choose "Extract All".
echo Then run BUILD.bat from the extracted top-level Sector folder.
echo.
echo Verified release downloads:
echo https://github.com/KasperLFabricius/Sector/releases/latest
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
