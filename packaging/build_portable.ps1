# Build one ordinary internal-use Sector portable Windows package.

param(
    [string]$SourceRevision = $env:SECTOR_SOURCE_REVISION,
    [string]$OutputDirectory = $env:SECTOR_PORTABLE_OUTPUT
)

$ErrorActionPreference = "Stop"
$sourceRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))

function Test-SectorPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    $probe = @'
import platform, struct, sys
print(platform.python_implementation() + '|' + str(sys.version_info[0]) + '|' + str(sys.version_info[1]) + '|' + str(struct.calcsize('P') * 8) + '|' + sys.executable)
'@
    try {
        $identity = [string](& $Executable @PrefixArguments -I -S -c $probe 2>$null)
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
    }
    catch {
        return $null
    }
    $parts = @($identity.Trim() -split '\|', 5)
    if (
        $parts.Count -ne 5 -or
        $parts[0] -cne "CPython" -or
        $parts[1] -cne "3" -or
        $parts[2] -cne "13" -or
        $parts[3] -cne "64" -or
        -not (Test-Path -LiteralPath $parts[4] -PathType Leaf)
    ) {
        return $null
    }
    return [PSCustomObject]@{
        Executable = [IO.Path]::GetFullPath($parts[4])
        PrefixArguments = @()
    }
}

function Resolve-SectorPython {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:SECTOR_PORTABLE_PYTHON)) {
        $candidates += [PSCustomObject]@{
            Executable = [string]$env:SECTOR_PORTABLE_PYTHON
            PrefixArguments = @()
        }
    }
    foreach ($command in @(Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$command.Source)) {
            $candidates += [PSCustomObject]@{
                Executable = [string]$command.Source
                PrefixArguments = @()
            }
        }
    }
    foreach ($command in @(Get-Command py.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$command.Source)) {
            $candidates += [PSCustomObject]@{
                Executable = [string]$command.Source
                PrefixArguments = @("-3.13-64")
            }
        }
    }
    foreach ($candidate in $candidates) {
        $accepted = Test-SectorPython `
            -Executable $candidate.Executable `
            -PrefixArguments $candidate.PrefixArguments
        if ($null -ne $accepted) {
            return $accepted
        }
    }
    throw (
        "Sector builds require 64-bit CPython 3.13. " +
        "Install Python 3.13 from python.org and run BUILD.bat again."
    )
}

$python = Resolve-SectorPython

if ([string]::IsNullOrWhiteSpace($SourceRevision)) {
    $SourceRevision = "unavailable"
}
if ($SourceRevision -cne "unavailable" -and $SourceRevision -cnotmatch '^[0-9a-f]{40}$') {
    throw "SourceRevision must be lowercase 40-hex or unavailable"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $userFolder = [Environment]::GetFolderPath("UserProfile")
    if ([string]::IsNullOrWhiteSpace($userFolder)) {
        $userFolder = [IO.Path]::GetTempPath()
    }
    $token = [Guid]::NewGuid().ToString("N").Substring(0, 10)
    $OutputDirectory = Join-Path $userFolder ("SectorBuilds\build-{0}" -f $token)
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $OutputDirectory) {
    throw "Build output already exists: $OutputDirectory"
}

$driver = Join-Path $sourceRoot "tools/build_portable_windows.py"
if (-not (Test-Path -LiteralPath $driver -PathType Leaf)) {
    throw "The extracted Sector source is incomplete: tools/build_portable_windows.py is missing"
}

Write-Host "Sector v0.93 portable Windows build"
Write-Host "Source: $sourceRoot"
Write-Host "Output: $OutputDirectory"
Write-Warning "This internal package is unsigned; Windows may show a SmartScreen warning."
Write-Host "Building once, then starting Sector and executing its first page..."

$arguments = @(
    "-I",
    "-S",
    $driver,
    "--root",
    $sourceRoot,
    "--output",
    $OutputDirectory,
    "--python",
    $python.Executable,
    "--source-revision",
    $SourceRevision
)
& $python.Executable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Sector portable build failed with exit code $LASTEXITCODE"
}

$folders = @(Get-ChildItem -LiteralPath $OutputDirectory -Directory |
    Where-Object { $_.Name -like "Sector-v*-windows-portable" })
$archives = @(Get-ChildItem -LiteralPath $OutputDirectory -File -Filter "*.zip")
$checksums = @(Get-ChildItem -LiteralPath $OutputDirectory -File -Filter "*.zip.sha256")
if ($folders.Count -ne 1 -or $archives.Count -ne 1 -or $checksums.Count -ne 1) {
    throw "Build output is incomplete"
}

Write-Host ""
Write-Host "Build PASSED, including packaged first-page execution."
Write-Host "Folder: $($folders[0].FullName)"
Write-Host "ZIP: $($archives[0].FullName)"
Write-Host "SHA-256: $($checksums[0].FullName)"
Write-Host "Distribute the complete folder or ZIP, not Sector.exe by itself."
