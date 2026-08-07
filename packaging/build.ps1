# Build an unsigned Sector QA package from one exact commit export.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1 `
#     -SourceRevision <exact-lowercase-40-hex> -OutputDirectory <new-path>
#
# Every run uses a new evidence directory. The result is for static inspection
# only and must not be launched, zipped, or distributed.

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
    $SourceRevision = [string](git --no-replace-objects -C $repoRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot resolve the exact source revision"
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
    $OutputDirectory = Join-Path $repoRoot (
        "qa-artifacts/windows-build-{0}-{1}" -f $stamp, $token
    )
}

Write-Warning "UNSIGNED QA PACKAGE ONLY. Do not launch, zip or distribute it."
Write-Host "Exporting exact source and building in a new isolated run root..."

python -I -S (Join-Path $repoRoot "tools/build_exact_commit.py") `
    --root $repoRoot `
    --source-revision $SourceRevision `
    --output $OutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Exact-source build failed with exit code $LASTEXITCODE"
}

Write-Host "Unsigned QA build evidence preserved at $OutputDirectory"
Write-Host "Inspection only: do not launch, zip or distribute this artifact."
