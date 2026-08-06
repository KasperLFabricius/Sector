# Build an unsigned Sector QA package (ONEDIR) into dist/Sector.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1
#
# The result is for static QA inspection only. It must not be launched, zipped
# or distributed. A distributable Sector build requires the separately
# authorised signing workflow.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root

Write-Warning "UNSIGNED QA PACKAGE ONLY. Do not launch, zip or distribute this artifact."

$sourceRevision = [string](git rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $sourceRevision -cnotmatch '^[0-9a-f]{40}$') {
  throw "Cannot resolve an exact source revision"
}
$trackedState = @(git status --porcelain=v1 --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $trackedState.Count -ne 0) {
  throw "The tracked source tree must be clean before a controlled package build"
}
$untrackedPayload = @(git ls-files --others --exclude-standard -- app sector assets)
if ($LASTEXITCODE -ne 0 -or $untrackedPayload.Count -ne 0) {
  throw "Untracked files inside packaged source trees are not permitted"
}
$sourceDateEpoch = [string](git show -s --format=%ct $sourceRevision)
if ($LASTEXITCODE -ne 0 -or $sourceDateEpoch -cnotmatch '^(0|[1-9][0-9]*)$') {
  throw "Cannot resolve the source commit timestamp"
}
$env:SECTOR_SOURCE_REVISION = $sourceRevision
$env:SOURCE_DATE_EPOCH = $sourceDateEpoch

$runIdentity = "{0}-{1}" -f (
  Get-Date -Format "yyyyMMdd-HHmmss"
), [guid]::NewGuid().ToString("N").Substring(0, 8)
$runRoot = Join-Path (Get-Location) ("build\unsigned-package-" + $runIdentity)
$primaryDist = Join-Path $runRoot "primary"
$secondaryDist = Join-Path $runRoot "repro-check"
$primaryWork = Join-Path $runRoot "work-primary"
$secondaryWork = Join-Path $runRoot "work-repro-check"
$notices = Join-Path $runRoot "legal\THIRD_PARTY_NOTICES.txt"
$evidence = Join-Path $runRoot "package-reproducibility.json"
New-Item -ItemType Directory -Path $runRoot | Out-Null

Write-Host "Installing locked build dependencies..."
python -m pip install --quiet --require-hashes -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Locked build dependency installation failed" }

Write-Host "Generating third-party notices..."
python tools/generate_third_party_notices.py `
  --output $notices
if ($LASTEXITCODE -ne 0) { throw "Third-party notice generation failed" }

Write-Host "Building two controlled packages (this can take a few minutes)..."
python -m PyInstaller --noconfirm --clean `
  --distpath $primaryDist --workpath $primaryWork packaging/sector.spec
if ($LASTEXITCODE -ne 0) { throw "Primary package build failed" }

$primaryPackage = Join-Path $primaryDist "Sector"
python -I -S tools/canonicalize_pyinstaller_archive.py `
  --archive (Join-Path $primaryPackage "_internal\base_library.zip")
if ($LASTEXITCODE -ne 0) { throw "Primary base-library canonicalization failed" }
Copy-Item -LiteralPath LICENSE -Destination (Join-Path $primaryPackage "LICENSE.txt") -Force
Copy-Item -LiteralPath $notices `
  -Destination (Join-Path $primaryPackage "THIRD_PARTY_NOTICES.txt") -Force

python -m PyInstaller --noconfirm --clean `
  --distpath $secondaryDist --workpath $secondaryWork packaging/sector.spec
if ($LASTEXITCODE -ne 0) { throw "Reproducibility package build failed" }

$secondaryPackage = Join-Path $secondaryDist "Sector"
python -I -S tools/canonicalize_pyinstaller_archive.py `
  --archive (Join-Path $secondaryPackage "_internal\base_library.zip")
if ($LASTEXITCODE -ne 0) { throw "Reproducibility base-library canonicalization failed" }
Copy-Item -LiteralPath LICENSE -Destination (Join-Path $secondaryPackage "LICENSE.txt") -Force
Copy-Item -LiteralPath $notices `
  -Destination (Join-Path $secondaryPackage "THIRD_PARTY_NOTICES.txt") -Force

python -I -S tools/verify_windows_release.py `
  --root . --package $primaryPackage --source-revision $sourceRevision `
  --source-date-epoch $sourceDateEpoch
if ($LASTEXITCODE -ne 0) { throw "Primary package verification failed" }

python -I -S tools/verify_windows_release.py `
  --root . --package $secondaryPackage --source-revision $sourceRevision `
  --source-date-epoch $sourceDateEpoch
if ($LASTEXITCODE -ne 0) { throw "Reproducibility package verification failed" }

python -I -S tools/verify_package_reproducibility.py `
  --first $primaryPackage --second $secondaryPackage `
  --source-revision $sourceRevision --source-date-epoch $sourceDateEpoch `
  --output $evidence
if ($LASTEXITCODE -ne 0) { throw "Controlled package comparison failed" }

Write-Host "Unsigned QA build complete at $primaryPackage."
Write-Host "Reproducibility evidence: $evidence"
Write-Host "Inspection only: do not launch, zip or distribute this artifact."
