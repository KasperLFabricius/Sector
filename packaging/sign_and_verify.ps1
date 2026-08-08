param(
  [Parameter(Mandatory = $true)][string]$PackageDirectory,
  [Parameter(Mandatory = $true)][string]$SourceRevision,
  [Parameter(Mandatory = $true)][string]$PfxBase64,
  [Parameter(Mandatory = $true)][string]$PfxPassword,
  [Parameter(Mandatory = $true)][string]$ExpectedThumbprint,
  [Parameter(Mandatory = $true)][string]$ExpectedSubject
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-ExactString {
  param(
    [Parameter(Mandatory = $true)][string]$Actual,
    [Parameter(Mandatory = $true)][string]$Expected,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if (-not [string]::Equals($Actual, $Expected, [System.StringComparison]::Ordinal)) {
    throw "Unexpected $Label"
  }
}

function Assert-EnhancedKeyUsage {
  param(
    [Parameter(Mandatory = $true)]$Certificate,
    [Parameter(Mandatory = $true)][string]$RequiredOid,
    [Parameter(Mandatory = $true)][string]$Label
  )
  $extension = @($Certificate.Extensions | Where-Object {
    $_.Oid.Value -eq "2.5.29.37"
  }) | Select-Object -First 1
  if ($null -eq $extension) {
    throw "$Label has no enhanced-key-usage extension"
  }
  $enhanced = [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]$extension
  $oids = @($enhanced.EnhancedKeyUsages | ForEach-Object { $_.Value })
  if ($RequiredOid -notin $oids) {
    throw "$Label lacks required EKU $RequiredOid"
  }
}

function Assert-OnlineChain {
  param(
    [Parameter(Mandatory = $true)]$Certificate,
    [Parameter(Mandatory = $true)][string]$Label
  )
  $chain = [System.Security.Cryptography.X509Certificates.X509Chain]::new()
  try {
    $chain.ChainPolicy.RevocationMode = [System.Security.Cryptography.X509Certificates.X509RevocationMode]::Online
    $chain.ChainPolicy.RevocationFlag = [System.Security.Cryptography.X509Certificates.X509RevocationFlag]::EntireChain
    $chain.ChainPolicy.VerificationFlags = [System.Security.Cryptography.X509Certificates.X509VerificationFlags]::NoFlag
    $chain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(30)
    if (-not $chain.Build($Certificate)) {
      $statuses = @($chain.ChainStatus | ForEach-Object {
        "$($_.Status):$($_.StatusInformation.Trim())"
      }) -join "; "
      throw "$Label chain validation failed: $statuses"
    }
  }
  finally {
    $chain.Dispose()
  }
}

function Find-X64SignTool {
  $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
  if (-not (Test-Path -LiteralPath $kitsRoot -PathType Container)) {
    throw "Windows SDK signing tools are unavailable"
  }

  $candidates = @()
  foreach ($directory in @(Get-ChildItem -LiteralPath $kitsRoot -Directory)) {
    $version = $null
    if ([version]::TryParse($directory.Name, [ref]$version)) {
      $candidate = Join-Path $directory.FullName "x64\signtool.exe"
      if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $candidates += [pscustomobject]@{ Version = $version; Path = $candidate }
      }
    }
  }
  $legacy = Join-Path $kitsRoot "x64\signtool.exe"
  if (Test-Path -LiteralPath $legacy -PathType Leaf) {
    $candidates += [pscustomobject]@{ Version = [version]"0.0"; Path = $legacy }
  }

  $selected = $candidates | Sort-Object Version -Descending | Select-Object -First 1
  if ($null -eq $selected) {
    throw "No concrete x64 signtool.exe was found"
  }
  if ((Split-Path -Leaf (Split-Path -Parent $selected.Path)) -cne "x64") {
    throw "The selected signing tool is not the x64 binary"
  }
  return [string]$selected.Path
}

if ($SourceRevision -cnotmatch '^[0-9a-f]{40}$') {
  throw "SourceRevision must be an exact lowercase 40-hex commit"
}
if ($ExpectedThumbprint -cnotmatch '^[0-9A-Fa-f]{40}$') {
  throw "ExpectedThumbprint must be an exact SHA-1 certificate thumbprint"
}
if ([string]::IsNullOrWhiteSpace($ExpectedSubject)) {
  throw "ExpectedSubject must be nonblank"
}
if ([string]::IsNullOrWhiteSpace($PfxBase64) -or [string]::IsNullOrEmpty($PfxPassword)) {
  throw "Signing credentials are incomplete"
}

$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$executable = Join-Path $package "Sector.exe"
$manifestPath = Join-Path $package "_internal\sector\sector_build_info.json"
$licensePath = Join-Path $package "LICENSE.txt"
$noticesPath = Join-Path $package "THIRD_PARTY_NOTICES.txt"
foreach ($requiredPath in ($executable, $manifestPath, $licensePath, $noticesPath)) {
  if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
    throw "Required release file is missing: $requiredPath"
  }
}

$expectedIdentity = [ordered]@{
  ProductName = "Sector"
  FileDescription = "Structural-analysis and design calculation tool"
  FileVersion = "0.92.0.0"
  ProductVersion = "0.92.0.0"
  OriginalFilename = "Sector.exe"
  LegalCopyright = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
}
$versionInfo = (Get-Item -LiteralPath $executable).VersionInfo
foreach ($field in $expectedIdentity.Keys) {
  Assert-ExactString -Actual ([string]$versionInfo.$field) -Expected ([string]$expectedIdentity[$field]) -Label "Windows identity field $field"
}
if (-not [string]::IsNullOrWhiteSpace([string]$versionInfo.CompanyName)) {
  throw "Sector.exe must not advertise a company or publisher identity"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$expectedManifest = [ordered]@{
  product_name = "Sector"
  description = "Structural-analysis and design calculation tool"
  sector_version = "0.92"
  source_revision = $SourceRevision
  author = "Kasper Lindskov Fabricius"
  licensee = "Sweco Danmark A/S"
  copyright = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
}
foreach ($field in $expectedManifest.Keys) {
  Assert-ExactString -Actual ([string]$manifest.$field) -Expected ([string]$expectedManifest[$field]) -Label "manifest field $field"
}

$thumbprint = $ExpectedThumbprint.ToUpperInvariant()
$pfxPath = Join-Path ([System.IO.Path]::GetTempPath()) ("Sector-sign-{0}.pfx" -f [guid]::NewGuid().ToString("N"))
$certificate = $null
try {
  $pfxBytes = [Convert]::FromBase64String($PfxBase64)
  if ($pfxBytes.Length -eq 0) {
    throw "The signing PFX is empty"
  }
  [System.IO.File]::WriteAllBytes($pfxPath, $pfxBytes)
  $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
    $pfxPath,
    $PfxPassword,
    [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
  )
  if ($null -eq $certificate -or -not $certificate.HasPrivateKey) {
    throw "The signing PFX has no usable private key"
  }
  Assert-ExactString -Actual $certificate.Thumbprint.ToUpperInvariant() -Expected $thumbprint -Label "PFX signer thumbprint"
  Assert-ExactString -Actual $certificate.Subject -Expected $ExpectedSubject -Label "PFX signer subject"
  Assert-EnhancedKeyUsage -Certificate $certificate -RequiredOid "1.3.6.1.5.5.7.3.3" -Label "Signing certificate"

  $signTool = Find-X64SignTool
  & $signTool sign /fd SHA256 /f $pfxPath /p $PfxPassword /tr "http://timestamp.digicert.com" /td SHA256 /d "Sector" $executable
  if ($LASTEXITCODE -ne 0) {
    throw "signtool signing failed"
  }
  & $signTool verify /pa /all /v $executable
  if ($LASTEXITCODE -ne 0) {
    throw "signtool verification failed"
  }

  $signature = Get-AuthenticodeSignature -LiteralPath $executable
  if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Authenticode verification failed: $($signature.Status)"
  }
  if ($null -eq $signature.SignerCertificate) {
    throw "Authenticode signer certificate is unavailable"
  }
  Assert-ExactString -Actual $signature.SignerCertificate.Thumbprint.ToUpperInvariant() -Expected $thumbprint -Label "Authenticode signer thumbprint"
  Assert-ExactString -Actual $signature.SignerCertificate.Subject -Expected $ExpectedSubject -Label "Authenticode signer subject"
  Assert-EnhancedKeyUsage -Certificate $signature.SignerCertificate -RequiredOid "1.3.6.1.5.5.7.3.3" -Label "Authenticode signer"
  Assert-OnlineChain -Certificate $signature.SignerCertificate -Label "Authenticode signer"

  if ($null -eq $signature.TimeStamperCertificate) {
    throw "RFC3161 timestamp certificate is unavailable"
  }
  Assert-EnhancedKeyUsage -Certificate $signature.TimeStamperCertificate -RequiredOid "1.3.6.1.5.5.7.3.8" -Label "Timestamp certificate"
  Assert-OnlineChain -Certificate $signature.TimeStamperCertificate -Label "Timestamp certificate"
}
finally {
  if ($null -ne $certificate) {
    $certificate.Dispose()
  }
  if (Test-Path -LiteralPath $pfxPath) {
    Remove-Item -LiteralPath $pfxPath -Force
  }
}

Write-Host "Sector signed package passed identity, provenance, Authenticode and online-chain verification."
