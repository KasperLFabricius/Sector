[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDirectory,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$SourceRevision
)

$ErrorActionPreference = "Stop"

function Assert-ExactValue {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]$Actual -cne [string]$Expected) {
        throw "Unexpected $Label"
    }
}

function Assert-CertificateUsage {
    param(
        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate,
        [Parameter(Mandatory = $true)][string]$RequiredOid,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $extension = $Certificate.Extensions |
        Where-Object { $_.Oid.Value -eq "2.5.29.37" } |
        Select-Object -First 1
    if ($null -eq $extension) {
        throw "$Label certificate has no enhanced-key-usage extension"
    }
    $enhanced = [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new()
    $enhanced.CopyFrom($extension)
    $usageOids = @($enhanced.EnhancedKeyUsages | ForEach-Object { $_.Value })
    if ($RequiredOid -notin $usageOids) {
        throw "$Label certificate lacks required EKU $RequiredOid"
    }
}

function Assert-CertificateChain {
    param(
        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $chain = [System.Security.Cryptography.X509Certificates.X509Chain]::new()
    try {
        $chain.ChainPolicy.RevocationMode = [System.Security.Cryptography.X509Certificates.X509RevocationMode]::Online
        $chain.ChainPolicy.RevocationFlag = [System.Security.Cryptography.X509Certificates.X509RevocationFlag]::EntireChain
        $chain.ChainPolicy.VerificationFlags = [System.Security.Cryptography.X509Certificates.X509VerificationFlags]::NoFlag
        if (-not $chain.Build($Certificate)) {
            $statuses = ($chain.ChainStatus | ForEach-Object { $_.Status }) -join ", "
            throw "$Label certificate chain is invalid: $statuses"
        }
    }
    finally {
        $chain.Dispose()
    }
}

$requiredSecrets = @(
    "SECTOR_SIGNING_CERTIFICATE_BASE64",
    "SECTOR_SIGNING_CERTIFICATE_PASSWORD",
    "SECTOR_SIGNING_CERTIFICATE_THUMBPRINT",
    "SECTOR_SIGNING_CERTIFICATE_SUBJECT"
)
foreach ($name in $requiredSecrets) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Missing protected signing secret $name"
    }
}

$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$executable = (Resolve-Path -LiteralPath (Join-Path $package "Sector.exe")).Path
$manifestPath = (Resolve-Path -LiteralPath (
    Join-Path $package "_internal/sector/sector_build_info.json"
)).Path
$licensePath = Join-Path $package "LICENSE.txt"
$noticesPath = Join-Path $package "THIRD_PARTY_NOTICES.txt"
if (-not (Test-Path -LiteralPath $licensePath -PathType Leaf)) {
    throw "Sector proprietary notice is missing"
}
if (-not (Test-Path -LiteralPath $noticesPath -PathType Leaf)) {
    throw "Third-party notice bundle is missing"
}

$kitRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits/10/bin"
$signTool = Get-ChildItem -LiteralPath $kitRoot -Filter signtool.exe -Recurse -File |
    Where-Object { $_.Directory.Name -ceq "x64" } |
    Sort-Object -Property FullName -Descending |
    Select-Object -First 1
if ($null -eq $signTool) {
    throw "The x64 Windows SDK signtool.exe is unavailable"
}

$runnerTemp = [Environment]::GetEnvironmentVariable("RUNNER_TEMP")
if ([string]::IsNullOrWhiteSpace($runnerTemp)) {
    throw "RUNNER_TEMP is unavailable"
}
$pfxPath = Join-Path $runnerTemp ("sector-signing-{0}.pfx" -f [Guid]::NewGuid())
$expectedThumbprint = $env:SECTOR_SIGNING_CERTIFICATE_THUMBPRINT -replace "\s", ""

try {
    [IO.File]::WriteAllBytes(
        $pfxPath,
        [Convert]::FromBase64String($env:SECTOR_SIGNING_CERTIFICATE_BASE64)
    )

    & $signTool.FullName sign /fd SHA256 /td SHA256 `
        /tr "https://timestamp.digicert.com" `
        /f $pfxPath `
        /p $env:SECTOR_SIGNING_CERTIFICATE_PASSWORD `
        /sha1 $expectedThumbprint `
        $executable
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed"
    }

    & $signTool.FullName verify /pa /all /v $executable
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode verification failed"
    }

    $signature = Get-AuthenticodeSignature -FilePath $executable
    Assert-ExactValue $signature.Status "Valid" "Authenticode status"
    Assert-ExactValue $signature.SignatureType "Authenticode" "signature type"
    if ($null -eq $signature.SignerCertificate) {
        throw "Signer certificate is unavailable"
    }
    $actualThumbprint = $signature.SignerCertificate.Thumbprint -replace "\s", ""
    Assert-ExactValue $actualThumbprint $expectedThumbprint "signer thumbprint"
    Assert-ExactValue $signature.SignerCertificate.Subject `
        $env:SECTOR_SIGNING_CERTIFICATE_SUBJECT "signer subject"
    Assert-CertificateUsage $signature.SignerCertificate `
        "1.3.6.1.5.5.7.3.3" "Code-signing"
    Assert-CertificateChain $signature.SignerCertificate "Code-signing"

    if ($null -eq $signature.TimeStamperCertificate) {
        throw "RFC3161 timestamp certificate is unavailable"
    }
    Assert-CertificateUsage $signature.TimeStamperCertificate `
        "1.3.6.1.5.5.7.3.8" "Timestamp"
    Assert-CertificateChain $signature.TimeStamperCertificate "Timestamp"

    $versionInfo = (Get-Item -LiteralPath $executable).VersionInfo
    $expectedVersionInfo = [ordered]@{
        ProductName = "Sector"
        FileDescription = "Structural-analysis and design calculation tool"
        FileVersion = "0.91.0.0"
        ProductVersion = "0.91.0.0"
        OriginalFilename = "Sector.exe"
        LegalCopyright = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
    }
    foreach ($field in $expectedVersionInfo.Keys) {
        Assert-ExactValue $versionInfo.$field $expectedVersionInfo[$field] `
            "Windows identity field $field"
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$versionInfo.CompanyName)) {
        throw "Sector.exe must not advertise a company or publisher identity"
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $expectedManifest = [ordered]@{
        product_name = "Sector"
        description = "Structural-analysis and design calculation tool"
        sector_version = "0.91"
        source_revision = $SourceRevision
        author = "Kasper Lindskov Fabricius"
        licensee = "Sweco Danmark A/S"
        copyright = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
    }
    foreach ($field in $expectedManifest.Keys) {
        Assert-ExactValue $manifest.$field $expectedManifest[$field] `
            "package manifest field $field"
    }
}
finally {
    if (Test-Path -LiteralPath $pfxPath) {
        Remove-Item -LiteralPath $pfxPath -Force
    }
}
