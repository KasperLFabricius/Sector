# Build an unsigned Sector QA package from authenticated exact source.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1 `
#     -SourceRevision <exact-lowercase-40-hex> -OutputDirectory <new-path>
#
# The input may be a Git checkout or an official provenance-bearing Sector
# source release. Every run uses a new evidence directory outside that input.
# The result is for static inspection only and must not be launched, zipped, or
# distributed.

param(
    [string]$SourceRevision = $env:SECTOR_SOURCE_REVISION,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent

# Repository-selection controls are not allowed to influence default identity.
Get-ChildItem Env: | Where-Object { $_.Name -like "GIT_*" } | ForEach-Object {
    Remove-Item -LiteralPath ("Env:" + $_.Name)
}

if ([string]::IsNullOrWhiteSpace($SourceRevision)) {
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $gitCommand) {
        $candidate = [string](& $gitCommand.Source --no-replace-objects `
            -C $repoRoot rev-parse HEAD 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $SourceRevision = $candidate.Trim()
        }
    }
    if ([string]::IsNullOrWhiteSpace($SourceRevision)) {
        $manifestPath = Join-Path $repoRoot "sector/sector_build_info.json"
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            try {
                $releaseManifest = Get-Content -LiteralPath $manifestPath -Raw |
                    ConvertFrom-Json
                $SourceRevision = [string]$releaseManifest.source_revision
            }
            catch {
                throw "Cannot read the source-release provenance manifest"
            }
        }
    }
    if ([string]::IsNullOrWhiteSpace($SourceRevision)) {
        throw "Cannot resolve an exact Git or source-release revision"
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
    $artifactRoot = Join-Path (Split-Path $repoRoot -Parent) (
        "{0}-qa-artifacts" -f (Split-Path $repoRoot -Leaf)
    )
    $OutputDirectory = Join-Path $artifactRoot (
        "windows-build-{0}-{1}" -f $stamp, $token
    )
}

Write-Warning "UNSIGNED QA PACKAGE ONLY. Do not launch, zip or distribute it."
Write-Host "Authenticating exact source and building in a new isolated run root..."

python -B -I -S (Join-Path $repoRoot "tools/build_exact_commit.py") `
    --root $repoRoot `
    --source-revision $SourceRevision `
    --output $OutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Exact-source build failed with exit code $LASTEXITCODE"
}

Write-Host "Unsigned QA build evidence preserved at $OutputDirectory"
Write-Host "Inspection only: do not launch, zip or distribute this artifact."
