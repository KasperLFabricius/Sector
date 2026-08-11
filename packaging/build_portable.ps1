# Build a complete unsigned Sector portable Windows distribution.
#
# The supported user action is double-clicking BUILD_SECTOR_PORTABLE.bat in an
# extracted official Sector source ZIP. This internal script is also callable
# by the exact-head CI acceptance job. It never launches Sector.exe, requests
# elevation, signs code, installs software, or overwrites an existing output.

param(
    [string]$SourceRevision = $env:SECTOR_SOURCE_REVISION,
    [string]$OutputDirectory = $env:SECTOR_PORTABLE_OUTPUT
)

$ErrorActionPreference = "Stop"
$sourceRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))

function Test-SectorPortablePython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    $probe = @'
import json, platform, struct, sys
print(json.dumps({"bits": struct.calcsize("P") * 8, "implementation": platform.python_implementation(), "version": list(sys.version_info[:3])}, sort_keys=True))
'@
    $probeArguments = @($PrefixArguments) + @("-I", "-S", "-c", $probe)
    try {
        $probeText = [string](& $Executable @probeArguments 2>$null)
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($probeText)) {
            return $null
        }
        $identity = $probeText | ConvertFrom-Json
    }
    catch {
        return $null
    }
    if (
        [string]$identity.implementation -cne "CPython" -or
        [int]$identity.bits -ne 64 -or
        $identity.version.Count -ne 3 -or
        [int]$identity.version[0] -ne 3 -or
        [int]$identity.version[1] -ne 13 -or
        [int]$identity.version[2] -ne 0
    ) {
        return $null
    }
    return [PSCustomObject]@{
        Executable = $Executable
        PrefixArguments = @($PrefixArguments)
    }
}

function Resolve-SectorPortablePython {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:SECTOR_PORTABLE_PYTHON)) {
        $candidates += [PSCustomObject]@{
            Executable = $env:SECTOR_PORTABLE_PYTHON
            PrefixArguments = @()
        }
    }
    $pythonCommand = Get-Command python.exe -CommandType Application `
        -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        $candidates += [PSCustomObject]@{
            Executable = $pythonCommand.Source
            PrefixArguments = @()
        }
    }
    $launcherCommand = Get-Command py.exe -CommandType Application `
        -ErrorAction SilentlyContinue
    if ($null -ne $launcherCommand) {
        $candidates += [PSCustomObject]@{
            Executable = $launcherCommand.Source
            PrefixArguments = @("-3.13-64")
        }
    }
    foreach ($candidate in $candidates) {
        $accepted = Test-SectorPortablePython `
            -Executable $candidate.Executable `
            -PrefixArguments $candidate.PrefixArguments
        if ($null -ne $accepted) {
            return $accepted
        }
    }
    throw (
        "Sector portable builds require exact CPython 3.13.0 (64-bit). " +
        "Install that interpreter and make python.exe available on PATH."
    )
}

# Interpreter identity is checked before resolving or creating any output.
$python = Resolve-SectorPortablePython

# Repository-selection controls cannot change the default source identity.
Get-ChildItem Env: | Where-Object { $_.Name -like "GIT_*" } | ForEach-Object {
    Remove-Item -LiteralPath ("Env:" + $_.Name)
}

if ([string]::IsNullOrWhiteSpace($SourceRevision)) {
    $manifestPath = Join-Path $sourceRoot "sector/sector_build_info.json"
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw |
                ConvertFrom-Json
            $SourceRevision = [string]$manifest.source_revision
        }
        catch {
            throw "Cannot read the source-release provenance manifest"
        }
    }
    else {
        # Git searches parent directories. Invoke it only when this source root
        # itself carries a checkout/worktree marker, never merely because an
        # extracted source release happens to sit below an unrelated checkout.
        $gitMarker = Join-Path $sourceRoot ".git"
        $gitCommand = Get-Command git.exe -CommandType Application `
            -ErrorAction SilentlyContinue
        if ((Test-Path -LiteralPath $gitMarker) -and $null -ne $gitCommand) {
            $candidate = [string](& $gitCommand.Source --no-replace-objects `
                -C $sourceRoot rev-parse HEAD 2>$null)
            if ($LASTEXITCODE -eq 0) {
                $SourceRevision = $candidate.Trim()
            }
        }
    }
}
if ($SourceRevision -cnotmatch '^[0-9a-f]{40}$') {
    throw "SourceRevision must be an exact lowercase 40-hex commit"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $stamp = [DateTime]::UtcNow.ToString(
        "yyyyMMddTHHmmssfffffffZ",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $token = [Guid]::NewGuid().ToString("N")
    $artifactRoot = Join-Path (Split-Path $sourceRoot -Parent) (
        "{0}-portable-artifacts" -f (Split-Path $sourceRoot -Leaf)
    )
    $OutputDirectory = Join-Path $artifactRoot (
        "windows-portable-{0}-{1}" -f $stamp, $token
    )
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$sourceBoundary = $sourceRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
if (
    $OutputDirectory.Equals(
        $sourceBoundary,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    $OutputDirectory.StartsWith(
        $sourceBoundary + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "Portable output must be outside the authenticated source directory"
}
if ([IO.File]::Exists($OutputDirectory) -or [IO.Directory]::Exists($OutputDirectory)) {
    throw "Portable output already exists: $OutputDirectory"
}

Write-Host "Sector unsigned portable Windows build"
Write-Warning (
    "This output is unsigned. Windows SmartScreen or corporate policy may " +
    "warn or block it; it claims no trusted publisher or reputation."
)
Write-Host "Authenticated source: $sourceRoot"
Write-Host "Exact source revision: $SourceRevision"
Write-Host "New output directory: $OutputDirectory"
Write-Host "Building the complete portable folder and ZIP. This may take several minutes."

$driver = Join-Path $sourceRoot "tools/build_portable_windows.py"
$driverArguments = @($python.PrefixArguments) + @(
    "-I",
    "-S",
    $driver,
    "--root",
    $sourceRoot,
    "--source-revision",
    $SourceRevision,
    "--output",
    $OutputDirectory
)
& $python.Executable @driverArguments
if ($LASTEXITCODE -ne 0) {
    throw "Portable build failed with exit code $LASTEXITCODE"
}

$portableFolders = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Directory |
        Where-Object { $_.Name -like "Sector-v*-windows-portable-unsigned" }
)
if ($portableFolders.Count -ne 1) {
    throw "Portable build did not publish exactly one complete distribution folder"
}
$portableFolder = $portableFolders[0].FullName
$portableArchive = $portableFolder + ".zip"
$portableArchiveHash = $portableArchive + ".sha256"
$portableReceipt = $portableFolder + ".portable-distribution.json"
foreach ($path in @(
    $portableFolder,
    $portableArchive,
    $portableArchiveHash,
    $portableReceipt
)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Portable build is missing expected output: $path"
    }
}

Write-Host ""
Write-Host "Portable build complete. Distribute the whole folder or ZIP, never Sector.exe alone."
Write-Host "Folder: $portableFolder"
Write-Host "ZIP: $portableArchive"
Write-Host "ZIP SHA-256: $portableArchiveHash"
Write-Host "Verification receipt: $portableReceipt"
Write-Warning "The package is unsigned and remains subject to the Sector licence."
