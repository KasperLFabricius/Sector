param(
    [string]$RepositoryRoot = (Split-Path $PSScriptRoot -Parent),
    [switch]$ReplaceGenerated
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$decisionPath = Join-Path $RepositoryRoot "docs/v093_decision_register.md"
$programmePath = Join-Path $RepositoryRoot "docs/v093_pr_programme.md"
$outputPath = Join-Path $RepositoryRoot "docs/sector_v093_decision_register.xlsx"
$previewRoot = Join-Path $RepositoryRoot "tmp/pdfs/v093-decision-workbook"
$backupRoot = Join-Path $RepositoryRoot "tmp/workbook-backups/v093-decision-register"
$buildTempRoot = Join-Path $RepositoryRoot "tmp/workbook-build/v093-decision-register"

if (-not (Test-Path -LiteralPath $decisionPath -PathType Leaf)) {
    throw "Decision register is missing: $decisionPath"
}
if (-not (Test-Path -LiteralPath $programmePath -PathType Leaf)) {
    throw "Programme is missing: $programmePath"
}
if ((Test-Path -LiteralPath $outputPath) -and -not $ReplaceGenerated) {
    throw "Generated workbook already exists; pass -ReplaceGenerated to replace it"
}

$decisionText = Get-Content -LiteralPath $decisionPath -Raw -Encoding UTF8
$programmeText = Get-Content -LiteralPath $programmePath -Raw -Encoding UTF8

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory)][string]$Text)

    $normalized = $Text.Replace("`r`n", "`n").Replace("`r", "`n")
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $algorithm.ComputeHash($encoding.GetBytes($normalized))
    }
    finally {
        $algorithm.Dispose()
    }
    return ([BitConverter]::ToString($digest)).Replace("-", "")
}

$decisionSha = Get-NormalizedTextSha256 $decisionText

function ConvertFrom-MarkdownCell {
    param([Parameter(Mandatory)][string]$Value)

    $clean = $Value.Trim()
    $clean = $clean.Replace('`', '').Replace('**', '')
    $clean = [regex]::Replace($clean, '\[([^\]]+)\]\([^\)]+\)', '$1')
    return [regex]::Replace($clean, '\s+', ' ')
}

function Get-DecisionRows {
    param([Parameter(Mandatory)][string]$Text)

    $pattern = '(?m)^\| (D093-\d{3}) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$'
    $rows = [System.Collections.Generic.List[object[]]]::new()
    foreach ($match in [regex]::Matches($Text, $pattern)) {
        $id = ConvertFrom-MarkdownCell $match.Groups[1].Value
        $rows.Add(@(
            $id,
            (ConvertFrom-MarkdownCell $match.Groups[2].Value),
            (ConvertFrom-MarkdownCell $match.Groups[3].Value),
            (ConvertFrom-MarkdownCell $match.Groups[4].Value),
            (ConvertFrom-MarkdownCell $match.Groups[5].Value),
            "Frozen",
            $(if ($id -eq "D093-013") { "Deferred" } else { "Implement" })
        ))
    }
    return $rows
}

function Get-ProgrammeRows {
    param([Parameter(Mandatory)][string]$Text)

    $pattern = '(?m)^\| (\d+) \| (PR-[^|]+?) \| ([^|]+?) \| (Merged|In progress|Planned) \|$'
    $rows = [System.Collections.Generic.List[object[]]]::new()
    foreach ($match in [regex]::Matches($Text, $pattern)) {
        $rows.Add(@(
            [int]$match.Groups[1].Value,
            (ConvertFrom-MarkdownCell $match.Groups[2].Value),
            (ConvertFrom-MarkdownCell $match.Groups[3].Value),
            (ConvertFrom-MarkdownCell $match.Groups[4].Value)
        ))
    }
    return $rows
}

function Get-MarkdownTableAfterHeading {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Heading,
        [Parameter(Mandatory)][string]$FirstHeader,
        [Parameter(Mandatory)][int]$ExpectedColumns
    )

    $headingIndex = $Text.IndexOf($Heading, [StringComparison]::Ordinal)
    if ($headingIndex -lt 0) {
        throw "Missing Markdown heading: $Heading"
    }
    $lines = $Text.Substring($headingIndex) -split "`r?`n"
    $headerIndex = -1
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index].StartsWith("| $FirstHeader |")) {
            $headerIndex = $index
            break
        }
    }
    if ($headerIndex -lt 0) {
        throw "Missing Markdown table after: $Heading"
    }

    $rows = [System.Collections.Generic.List[object[]]]::new()
    for ($index = $headerIndex + 2; $index -lt $lines.Count; $index++) {
        $line = $lines[$index]
        if (-not $line.StartsWith("|")) {
            break
        }
        $cells = @(
            $line.Split('|')[1..($line.Split('|').Count - 2)] |
                ForEach-Object { ConvertFrom-MarkdownCell $_ }
        )
        if ($cells.Count -eq $ExpectedColumns) {
            $rows.Add($cells)
        }
    }
    return $rows
}

function Set-RangeValues {
    param(
        [Parameter(Mandatory)]$Worksheet,
        [Parameter(Mandatory)][string]$StartCell,
        [Parameter(Mandatory)][object[]]$Rows,
        [Parameter(Mandatory)][int]$Columns
    )

    $matrix = New-Object 'object[,]' $Rows.Count, $Columns
    for ($row = 0; $row -lt $Rows.Count; $row++) {
        if ($Rows[$row].Count -ne $Columns) {
            throw "Row $row has $($Rows[$row].Count) cells; expected $Columns"
        }
        for ($column = 0; $column -lt $Columns; $column++) {
            $matrix[$row, $column] = $Rows[$row][$column]
        }
    }

    $start = $Worksheet.Range($StartCell)
    $target = $start.Resize($Rows.Count, $Columns)
    $target.Value2 = $matrix
    Write-Output -NoEnumerate $target
}

function Get-OleColor {
    param([Parameter(Mandatory)][string]$Hex)

    $red = [Convert]::ToInt32($Hex.Substring(1, 2), 16)
    $green = [Convert]::ToInt32($Hex.Substring(3, 2), 16)
    $blue = [Convert]::ToInt32($Hex.Substring(5, 2), 16)
    return $red + (256 * $green) + (65536 * $blue)
}

function Set-SheetTitle {
    param(
        [Parameter(Mandatory)]$Worksheet,
        [Parameter(Mandatory)][string]$LastColumn,
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Subtitle
    )

    $titleRange = $Worksheet.Range("A1:${LastColumn}1")
    $titleRange.Merge()
    $titleRange.Value2 = $Title
    $titleRange.Interior.Color = Get-OleColor "#17365D"
    $titleRange.Font.Name = "Aptos Display"
    $titleRange.Font.Size = 20
    $titleRange.Font.Bold = $true
    $titleRange.Font.Color = Get-OleColor "#FFFFFF"
    $titleRange.HorizontalAlignment = -4131
    $titleRange.VerticalAlignment = -4108
    $titleRange.RowHeight = 34

    $subtitleRange = $Worksheet.Range("A2:${LastColumn}2")
    $subtitleRange.Merge()
    $subtitleRange.Value2 = $Subtitle
    $subtitleRange.Interior.Color = Get-OleColor "#D9EAF7"
    $subtitleRange.Font.Name = "Aptos"
    $subtitleRange.Font.Size = 10
    $subtitleRange.Font.Italic = $true
    $subtitleRange.Font.Color = Get-OleColor "#17365D"
    $subtitleRange.WrapText = $true
    $subtitleRange.VerticalAlignment = -4108
    $subtitleRange.RowHeight = 30
}

function Add-StyledTable {
    param(
        [Parameter(Mandatory)]$Worksheet,
        [Parameter(Mandatory)]$Range,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$BodyRowHeight
    )

    $table = $Worksheet.ListObjects.Add(1, $Range, $null, 1)
    $table.Name = $Name
    $table.TableStyle = "TableStyleMedium2"
    $header = $table.HeaderRowRange
    $header.Interior.Color = Get-OleColor "#1F4E78"
    $header.Font.Name = "Aptos"
    $header.Font.Size = 10
    $header.Font.Bold = $true
    $header.Font.Color = Get-OleColor "#FFFFFF"
    $header.WrapText = $true
    $header.VerticalAlignment = -4108
    $header.RowHeight = 32
    if ($null -ne $table.DataBodyRange) {
        $body = $table.DataBodyRange
        $body.Font.Name = "Aptos"
        $body.Font.Size = 9
        $body.Font.Color = Get-OleColor "#1F1F1F"
        $body.WrapText = $true
        $body.VerticalAlignment = -4160
        $body.HorizontalAlignment = -4131
        $body.RowHeight = $BodyRowHeight
    }
    return $table
}

function Set-ColumnWidths {
    param(
        [Parameter(Mandatory)]$Worksheet,
        [Parameter(Mandatory)][hashtable]$Widths
    )

    foreach ($entry in $Widths.GetEnumerator()) {
        $Worksheet.Columns.Item($entry.Key).ColumnWidth = $entry.Value
    }
}

function Set-PrintLayout {
    param(
        [Parameter(Mandatory)]$Excel,
        [Parameter(Mandatory)]$Worksheet,
        [Parameter(Mandatory)][ValidateSet("A4", "A3")][string]$Paper,
        [Parameter(Mandatory)][int]$PagesWide
    )

    $Worksheet.Activate()
    $Excel.ActiveWindow.DisplayGridlines = $false
    $Excel.ActiveWindow.SplitRow = 4
    $Excel.ActiveWindow.SplitColumn = 0
    $Excel.ActiveWindow.FreezePanes = $true

    $setup = $Worksheet.PageSetup
    $setup.Orientation = 2
    $setup.PaperSize = $(if ($Paper -eq "A3") { 8 } else { 9 })
    $setup.Zoom = $false
    $setup.FitToPagesWide = $PagesWide
    $setup.FitToPagesTall = $false
    $setup.LeftMargin = $Excel.InchesToPoints(0.3)
    $setup.RightMargin = $Excel.InchesToPoints(0.3)
    $setup.TopMargin = $Excel.InchesToPoints(0.45)
    $setup.BottomMargin = $Excel.InchesToPoints(0.45)
    $setup.HeaderMargin = $Excel.InchesToPoints(0.15)
    $setup.FooterMargin = $Excel.InchesToPoints(0.2)
    $setup.CenterHeader = "&B" + $Worksheet.Name
    $setup.LeftFooter = "Sector v0.93 decision register"
    $setup.RightFooter = "Page &P of &N"
    $setup.PrintTitleRows = '$1:$4'
    $setup.PrintArea = $Worksheet.UsedRange.Address()
}

function Read-ZipXmlDocument {
    param(
        [Parameter(Mandatory)]$Archive,
        [Parameter(Mandatory)][string]$EntryName
    )

    $entry = $Archive.GetEntry($EntryName)
    if ($null -eq $entry) {
        throw "Workbook package is missing $EntryName"
    }
    $document = New-Object System.Xml.XmlDocument
    $document.PreserveWhitespace = $true
    $stream = $entry.Open()
    try {
        $document.Load($stream)
    }
    finally {
        $stream.Dispose()
    }
    Write-Output -NoEnumerate $document
}

function Write-ZipXmlDocument {
    param(
        [Parameter(Mandatory)]$Archive,
        [Parameter(Mandatory)][string]$EntryName,
        [Parameter(Mandatory)]$Document
    )

    $existing = $Archive.GetEntry($EntryName)
    if ($null -eq $existing) {
        throw "Workbook package is missing $EntryName"
    }
    $existing.Delete()
    $entry = $Archive.CreateEntry(
        $EntryName,
        [IO.Compression.CompressionLevel]::Optimal
    )
    $settings = New-Object System.Xml.XmlWriterSettings
    $settings.Encoding = New-Object System.Text.UTF8Encoding($false)
    $settings.Indent = $false
    $settings.OmitXmlDeclaration = $false
    $stream = $entry.Open()
    $writer = [Xml.XmlWriter]::Create($stream, $settings)
    try {
        $Document.Save($writer)
    }
    finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}

function Remove-WorkbookEnvironmentMetadata {
    param(
        [Parameter(Mandatory)][string]$SourcePath,
        [Parameter(Mandatory)][string]$DestinationPath
    )

    if (Test-Path -LiteralPath $DestinationPath) {
        throw "Sanitized workbook destination already exists: $DestinationPath"
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath
    $archive = [IO.Compression.ZipFile]::Open(
        $DestinationPath,
        [IO.Compression.ZipArchiveMode]::Update
    )
    try {
        $customProperties = $archive.GetEntry("docProps/custom.xml")
        if ($null -ne $customProperties) {
            $customProperties.Delete()
        }
        foreach ($entry in @($archive.Entries | Where-Object {
            $_.FullName.StartsWith("xl/printerSettings/", [StringComparison]::OrdinalIgnoreCase)
        })) {
            $entry.Delete()
        }

        $contentTypes = Read-ZipXmlDocument $archive "[Content_Types].xml"
        foreach ($node in @($contentTypes.SelectNodes(
            "/*[local-name()='Types']/*[local-name()='Override'][@PartName='/docProps/custom.xml']"
        ))) {
            $null = $node.ParentNode.RemoveChild($node)
        }
        foreach ($node in @($contentTypes.SelectNodes(
            "/*[local-name()='Types']/*[local-name()='Default'][@Extension='bin' and contains(@ContentType, 'printerSettings')]"
        ))) {
            $null = $node.ParentNode.RemoveChild($node)
        }
        Write-ZipXmlDocument $archive "[Content_Types].xml" $contentTypes

        $rootRelationships = Read-ZipXmlDocument $archive "_rels/.rels"
        foreach ($node in @($rootRelationships.SelectNodes(
            "/*[local-name()='Relationships']/*[local-name()='Relationship'][@Target='docProps/custom.xml' or contains(@Type, '/custom-properties')]"
        ))) {
            $null = $node.ParentNode.RemoveChild($node)
        }
        Write-ZipXmlDocument $archive "_rels/.rels" $rootRelationships

        $workbookXml = Read-ZipXmlDocument $archive "xl/workbook.xml"
        foreach ($node in @($workbookXml.SelectNodes(
            "//*[local-name()='AlternateContent'][descendant::*[local-name()='absPath']]"
        ))) {
            $null = $node.ParentNode.RemoveChild($node)
        }
        Write-ZipXmlDocument $archive "xl/workbook.xml" $workbookXml

        for ($sheetNumber = 1; $sheetNumber -le 5; $sheetNumber++) {
            $relationshipName = "xl/worksheets/_rels/sheet$sheetNumber.xml.rels"
            $relationships = Read-ZipXmlDocument $archive $relationshipName
            foreach ($node in @($relationships.SelectNodes(
                "/*[local-name()='Relationships']/*[local-name()='Relationship'][contains(@Type, '/printerSettings')]"
            ))) {
                $null = $node.ParentNode.RemoveChild($node)
            }
            Write-ZipXmlDocument $archive $relationshipName $relationships

            $worksheetName = "xl/worksheets/sheet$sheetNumber.xml"
            $worksheetXml = Read-ZipXmlDocument $archive $worksheetName
            foreach ($attribute in @($worksheetXml.SelectNodes(
                "//*[local-name()='pageSetup']/@*[local-name()='id' and namespace-uri()='http://schemas.openxmlformats.org/officeDocument/2006/relationships']"
            ))) {
                $null = $attribute.OwnerElement.RemoveAttributeNode($attribute)
            }
            Write-ZipXmlDocument $archive $worksheetName $worksheetXml
        }

        $coreProperties = Read-ZipXmlDocument $archive "docProps/core.xml"
        $creators = @($coreProperties.SelectNodes("//*[local-name()='creator']"))
        $modifiers = @($coreProperties.SelectNodes("//*[local-name()='lastModifiedBy']"))
        if ($creators.Count -ne 1 -or $modifiers.Count -ne 1) {
            throw "Workbook core author metadata is incomplete"
        }
        $creators[0].InnerText = "Kasper Lindskov Fabricius"
        $modifiers[0].InnerText = "Kasper Lindskov Fabricius"
        Write-ZipXmlDocument $archive "docProps/core.xml" $coreProperties
    }
    finally {
        $archive.Dispose()
    }
}

function Assert-WorkbookPackageIsPublicationClean {
    param([Parameter(Mandatory)][string]$Path)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $entryNames = @($archive.Entries | ForEach-Object { $_.FullName })
        foreach ($entryName in $entryNames) {
            $lowerName = $entryName.ToLowerInvariant()
            foreach ($forbiddenPart in @(
                "activex", "customxml", "embeddings", "externallinks",
                "oleobject", "vbaproject", "_xmlsignatures", "printersettings"
            )) {
                if ($lowerName.Contains($forbiddenPart)) {
                    throw "Workbook contains forbidden active part: $entryName"
                }
            }
        }
        if ($entryNames -contains "docProps/custom.xml") {
            throw "Workbook contains environment-specific custom properties"
        }

        $packageText = New-Object Text.StringBuilder
        foreach ($entry in $archive.Entries) {
            if (-not ($entry.FullName.EndsWith(".xml") -or $entry.FullName.EndsWith(".rels"))) {
                continue
            }
            $reader = New-Object IO.StreamReader($entry.Open())
            try {
                $entryText = $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }
            $null = $packageText.AppendLine($entryText)
            if ($entry.FullName.EndsWith(".rels")) {
                $relationshipXml = New-Object System.Xml.XmlDocument
                $relationshipXml.LoadXml($entryText)
                foreach ($relationship in @($relationshipXml.SelectNodes(
                    "//*[local-name()='Relationship']"
                ))) {
                    if ([string]$relationship.GetAttribute("TargetMode") -eq "External") {
                        throw "Workbook contains an external relationship in $($entry.FullName)"
                    }
                }
            }
        }
        $allText = $packageText.ToString()
        foreach ($forbiddenText in @(
            "x15ac:absPath",
            "sharepoint.com",
            "onedrive",
            "MSIP_Label_",
            "docProps/custom.xml",
            "/custom-properties",
            "file:",
            "/Users/",
            "/home/"
        )) {
            if ($allText.IndexOf($forbiddenText, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                throw "Workbook contains forbidden environment metadata: $forbiddenText"
            }
        }
        if ($allText -match '(?i)(^|[^a-z0-9])[a-z]:[\\/]') {
            throw "Workbook contains a local drive path"
        }
        if ($allText -match '(?i)(^|[^\\])\\\\[^\\/\s<>]+[\\/]') {
            throw "Workbook contains a UNC path"
        }

        $coreProperties = Read-ZipXmlDocument $archive "docProps/core.xml"
        $creator = @($coreProperties.SelectNodes("//*[local-name()='creator']"))
        $modifier = @($coreProperties.SelectNodes("//*[local-name()='lastModifiedBy']"))
        if (
            $creator.Count -ne 1 -or
            $modifier.Count -ne 1 -or
            $creator[0].InnerText -ne "Kasper Lindskov Fabricius" -or
            $modifier[0].InnerText -ne "Kasper Lindskov Fabricius"
        ) {
            throw "Workbook author metadata does not match the Sector identity"
        }
    }
    finally {
        $archive.Dispose()
    }
}

$decisionRows = @(Get-DecisionRows $decisionText)
$programmeRows = @(Get-ProgrammeRows $programmeText)
$standardsRows = @(
    Get-MarkdownTableAfterHeading `
        -Text $decisionText `
        -Heading "## Standards status frozen for implementation" `
        -FirstHeader "Family" `
        -ExpectedColumns 4
)
$manualRows = @(
    Get-MarkdownTableAfterHeading `
        -Text $programmeText `
        -Heading "### 2.8 Manual review and target information architecture" `
        -FirstHeader "Current page" `
        -ExpectedColumns 3
)
$reportRows = @(
    Get-MarkdownTableAfterHeading `
        -Text $programmeText `
        -Heading "### 2.9 Report review and target profiles" `
        -FirstHeader "Current page" `
        -ExpectedColumns 3
)

if ($decisionRows.Count -ne 27) {
    throw "Expected 27 decision rows; found $($decisionRows.Count)"
}
if ($programmeRows.Count -ne 10) {
    throw "Expected 10 programme rows; found $($programmeRows.Count)"
}
if ($standardsRows.Count -ne 4) {
    throw "Expected 4 standards rows; found $($standardsRows.Count)"
}

$publicationRows = [System.Collections.Generic.List[object[]]]::new()
foreach ($row in $manualRows) {
    $publicationRows.Add(@("Manual", $row[0], $row[1], $row[2]))
}
foreach ($row in $reportRows) {
    $publicationRows.Add(@("Report", $row[0], $row[1], $row[2]))
}

$excel = $null
$workbook = $null
New-Item -ItemType Directory -Path $buildTempRoot -Force | Out-Null
$runId = [guid]::NewGuid().ToString("N")
$temporaryOutput = Join-Path $buildTempRoot "sector-v093-$runId.excel.xlsx"
$sanitizedOutput = Join-Path $buildTempRoot "sector-v093-$runId.clean.xlsx"

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false
    $excel.EnableEvents = $false

    $workbook = $excel.Workbooks.Add()
    while ($workbook.Worksheets.Count -lt 5) {
        $null = $workbook.Worksheets.Add()
    }
    while ($workbook.Worksheets.Count -gt 5) {
        $workbook.Worksheets.Item($workbook.Worksheets.Count).Delete()
    }

    $readMe = $workbook.Worksheets.Item(1)
    $decisions = $workbook.Worksheets.Item(2)
    $programme = $workbook.Worksheets.Item(3)
    $standards = $workbook.Worksheets.Item(4)
    $publication = $workbook.Worksheets.Item(5)
    $readMe.Name = "Read Me"
    $decisions.Name = "Decisions"
    $programme.Name = "PR Programme"
    $standards.Name = "Standards"
    $publication.Name = "Publication QA"

    Set-SheetTitle $readMe "G" "Sector v0.93 Decision Register" "Owner decisions and programme controls - frozen 2026-08-08"
    $metadataRows = @(
        @("Record", "Value"),
        @("Target release", "Sector 0.93"),
        @("Programme baseline", "decd1232abb0a082639de90726c125dc988e1078"),
        @("Baseline tree", "f09bf8cb500f2ae02c2c30a8f085c67153fe619a"),
        @("Baseline release", "v0.92-source.1"),
        @("Decision freeze date", "2026-08-08"),
        @("Canonical record", "docs/v093_decision_register.md"),
        @("Canonical record LF-normalized SHA-256", $decisionSha),
        @("Governing identity", "docs/product_identity.md")
    )
    $metadataRange = Set-RangeValues $readMe "A4" $metadataRows 2
    $null = Add-StyledTable $readMe $metadataRange "RegisterMetadata" 25

    $summaryRows = @(
        @("Live summary", "Count"),
        @("Frozen decisions", $null),
        @("Implementation decisions", $null),
        @("Deferred decisions", $null),
        @("Planned PR slices", $null),
        @("PR slices in progress", $null)
    )
    $summaryRange = Set-RangeValues $readMe "D4" $summaryRows 2
    $readMe.Range("D4:E4").Interior.Color = Get-OleColor "#1F4E78"
    $readMe.Range("D4:E4").Font.Name = "Aptos"
    $readMe.Range("D4:E4").Font.Size = 10
    $readMe.Range("D4:E4").Font.Bold = $true
    $readMe.Range("D4:E4").Font.Color = Get-OleColor "#FFFFFF"
    $readMe.Range("D4:E4").HorizontalAlignment = -4108
    $readMe.Range("D4:E4").VerticalAlignment = -4108
    $readMe.Range("D4:E4").RowHeight = 32
    $readMe.Range("D5:E9").Font.Name = "Aptos"
    $readMe.Range("D5:E9").Font.Size = 9
    $readMe.Range("D5:E9").VerticalAlignment = -4108
    $readMe.Range("D5:E9").RowHeight = 25
    $summaryRange.Borders.LineStyle = 1
    $summaryRange.Borders.Color = Get-OleColor "#B4C6E7"
    $readMe.Range("E5:E9").Interior.Color = Get-OleColor "#EEF5FA"
    $readMe.Range("E5:E9").Font.Bold = $true
    $readMe.Range("E5:E9").Font.Color = Get-OleColor "#17365D"
    $readMe.Range("E5:E9").Font.Size = 12
    $readMe.Range("E5:E9").HorizontalAlignment = -4108

    $authority = $readMe.Range("A15:G18")
    $authority.Merge()
    $authority.Value2 = "Authority and use: this workbook is a formatted snapshot of the accepted Markdown decision register. The accepted Git revision is authoritative if a discrepancy is found. Sector remains a transparent structural calculation tool, not an engineering certification or global compliance system. A qualified engineer remains responsible for applicability, inputs, modelling, independent verification and acceptance."
    $authority.Interior.Color = Get-OleColor "#FFF2CC"
    $authority.Font.Name = "Aptos"
    $authority.Font.Size = 10
    $authority.Font.Color = Get-OleColor "#1F1F1F"
    $authority.WrapText = $true
    $authority.VerticalAlignment = -4108
    $authority.Borders.LineStyle = 1
    $authority.Borders.Color = Get-OleColor "#BF9000"
    Set-ColumnWidths $readMe @{ 1 = 27; 2 = 76; 3 = 3; 4 = 28; 5 = 14; 6 = 3; 7 = 3 }

    Set-SheetTitle $decisions "G" "Frozen owner decisions" "Filter by PR, status or disposition. Complete wording is retained from the canonical register."
    $decisionTableRows = [System.Collections.Generic.List[object[]]]::new()
    $decisionTableRows.Add(@("Decision ID", "Frozen decision", "Reason and boundary", "Acceptance evidence", "Owning PR", "Status", "Disposition"))
    foreach ($row in $decisionRows) { $decisionTableRows.Add($row) }
    $decisionRange = Set-RangeValues $decisions "A4" $decisionTableRows.ToArray() 7
    $null = Add-StyledTable $decisions $decisionRange "V093Decisions" 72
    $decisions.Range("A5:A31").Interior.Color = Get-OleColor "#EEF5FA"
    $decisions.Range("A5:A31").Font.Bold = $true
    $decisions.Range("A5:A31").Font.Color = Get-OleColor "#17365D"
    $decisions.Range("A5:A31").HorizontalAlignment = -4108
    $decisions.Range("F5:F31").Interior.Color = Get-OleColor "#D9EAF7"
    $decisions.Range("F5:F31").Font.Bold = $true
    $decisions.Range("F5:F31").HorizontalAlignment = -4108
    for ($rowNumber = 5; $rowNumber -le 31; $rowNumber++) {
        $cell = $decisions.Range("G$rowNumber")
        $cell.Interior.Color = Get-OleColor $(
            if ($cell.Value2 -eq "Deferred") { "#FFF2CC" } else { "#E2F0D9" }
        )
        $cell.Font.Bold = $true
        $cell.HorizontalAlignment = -4108
    }
    Set-ColumnWidths $decisions @{ 1 = 15; 2 = 48; 3 = 66; 4 = 48; 5 = 18; 6 = 14; 7 = 14 }
    for ($rowNumber = 5; $rowNumber -le 31; $rowNumber++) {
        $null = $decisions.Rows.Item($rowNumber).EntireRow.AutoFit()
        if ([double]$decisions.Rows.Item($rowNumber).RowHeight -lt 54) {
            $decisions.Rows.Item($rowNumber).RowHeight = 54
        }
    }

    Set-SheetTitle $programme "D" "Pull-request programme" "Statuses change only after objective evidence exists; dependencies are execution gates."
    $programmeTableRows = [System.Collections.Generic.List[object[]]]::new()
    $programmeTableRows.Add(@("Order", "Slice", "Depends on", "Status"))
    foreach ($row in $programmeRows) { $programmeTableRows.Add($row) }
    $programmeRange = Set-RangeValues $programme "A4" $programmeTableRows.ToArray() 4
    $null = Add-StyledTable $programme $programmeRange "V093Programme" 34
    $programme.Range("A5:A14").Interior.Color = Get-OleColor "#EEF5FA"
    $programme.Range("A5:A14").Font.Bold = $true
    $programme.Range("A5:A14").Font.Color = Get-OleColor "#17365D"
    $programme.Range("A5:A14").HorizontalAlignment = -4108
    for ($rowNumber = 5; $rowNumber -le 14; $rowNumber++) {
        $cell = $programme.Range("D$rowNumber")
        $cell.Interior.Color = Get-OleColor $(
            if ($cell.Value2 -eq "Merged") { "#E2F0D9" }
            elseif ($cell.Value2 -eq "In progress") { "#FFF2CC" }
            else { "#E7E6E6" }
        )
        $cell.Font.Bold = $true
        $cell.HorizontalAlignment = -4108
    }
    Set-ColumnWidths $programme @{ 1 = 10; 2 = 62; 3 = 32; 4 = 18 }

    Set-SheetTitle $standards "D" "Standards status and implementation boundary" "Licensed standards remain the equation and clause authority; this sheet records routing and disclosure decisions."
    $standardTableRows = [System.Collections.Generic.List[object[]]]::new()
    $standardTableRows.Add(@("Family", "Sector label and scope", "Status disclosure", "v0.93 boundary"))
    foreach ($row in $standardsRows) { $standardTableRows.Add($row) }
    $standardsRange = Set-RangeValues $standards "A4" $standardTableRows.ToArray() 4
    $null = Add-StyledTable $standards $standardsRange "V093Standards" 88
    Set-ColumnWidths $standards @{ 1 = 34; 2 = 57; 3 = 56; 4 = 64 }

    Set-SheetTitle $publication "D" "Manual and report visual evidence" "Concrete v0.92 findings are paired with measurable v0.93 treatments; crack spacing is one example, not the scope boundary."
    $publicationTableRows = [System.Collections.Generic.List[object[]]]::new()
    $publicationTableRows.Add(@("Surface", "Current page", "Observed issue", "Required treatment"))
    foreach ($row in $publicationRows) { $publicationTableRows.Add($row) }
    $publicationRange = Set-RangeValues $publication "A4" $publicationTableRows.ToArray() 4
    $null = Add-StyledTable $publication $publicationRange "V093PublicationQA" 70
    $lastPublicationRow = 4 + $publicationRows.Count
    $publication.Range("A5:A$lastPublicationRow").Interior.Color = Get-OleColor "#EEF5FA"
    $publication.Range("A5:A$lastPublicationRow").Font.Bold = $true
    $publication.Range("A5:A$lastPublicationRow").Font.Color = Get-OleColor "#17365D"
    $publication.Range("A5:A$lastPublicationRow").HorizontalAlignment = -4108
    Set-ColumnWidths $publication @{ 1 = 14; 2 = 18; 3 = 65; 4 = 70 }

    $readMe.Range("E5").Formula = "=COUNTA('Decisions'!A5:A31)"
    $readMe.Range("E6").Formula = '=COUNTIF(''Decisions''!G5:G31,"Implement")'
    $readMe.Range("E7").Formula = '=COUNTIF(''Decisions''!G5:G31,"Deferred")'
    $readMe.Range("E8").Formula = '=COUNTIF(''PR Programme''!D5:D14,"Planned")'
    $readMe.Range("E9").Formula = '=COUNTIF(''PR Programme''!D5:D14,"In progress")'
    $readMe.Calculate()
    $expectedPlanned = @($programmeRows | Where-Object { $_[3] -eq "Planned" }).Count
    $expectedInProgress = @($programmeRows | Where-Object { $_[3] -eq "In progress" }).Count
    if ([int]$readMe.Range("E5").Value2 -ne 27) { throw "Decision count formula is incorrect: $($readMe.Range('E5').Value2)" }
    if ([int]$readMe.Range("E6").Value2 -ne 26) { throw "Implementation count formula is incorrect: $($readMe.Range('E6').Value2)" }
    if ([int]$readMe.Range("E7").Value2 -ne 1) { throw "Deferred count formula is incorrect: $($readMe.Range('E7').Value2)" }
    if ([int]$readMe.Range("E8").Value2 -ne $expectedPlanned) { throw "Planned PR count formula is incorrect: $($readMe.Range('E8').Value2)" }
    if ([int]$readMe.Range("E9").Value2 -ne $expectedInProgress) { throw "In-progress PR count formula is incorrect: $($readMe.Range('E9').Value2)" }

    foreach ($sheet in @($readMe, $decisions, $programme, $standards, $publication)) {
        foreach ($cell in $sheet.UsedRange.Cells) {
            if ($cell.HasFormula -and ([string]$cell.Text).StartsWith("#")) {
                throw "Formula error in $($sheet.Name)!$($cell.Address()): $($cell.Text)"
            }
        }
    }

    Set-PrintLayout $excel $readMe "A4" 1
    Set-PrintLayout $excel $decisions "A3" 1
    $decisions.ResetAllPageBreaks()
    $null = $decisions.HPageBreaks.Add($decisions.Range("A14"))
    $null = $decisions.HPageBreaks.Add($decisions.Range("A23"))
    Set-PrintLayout $excel $programme "A4" 1
    $programme.PageSetup.FitToPagesTall = 1
    Set-PrintLayout $excel $standards "A3" 1
    Set-PrintLayout $excel $publication "A3" 1
    $readMe.Activate()

    $workbook.SaveAs($temporaryOutput, 51)
    $workbook.Save()

    New-Item -ItemType Directory -Path $previewRoot -Force | Out-Null
    foreach ($sheet in @($readMe, $decisions, $programme, $standards, $publication)) {
        $safeName = $sheet.Name.ToLowerInvariant().Replace(" ", "-")
        $pdfPath = Join-Path $previewRoot "$safeName.pdf"
        if (Test-Path -LiteralPath $pdfPath) {
            Remove-Item -LiteralPath $pdfPath
        }
        $sheet.ExportAsFixedFormat(0, $pdfPath, 0, $true, $false)
    }

    $readMe.Activate()
    $workbook.Save()
    $workbook.Close($false)
    $workbook = $null
    $excel.Quit()
    $excel = $null

    Remove-WorkbookEnvironmentMetadata $temporaryOutput $sanitizedOutput
    Assert-WorkbookPackageIsPublicationClean $sanitizedOutput
    Remove-Item -LiteralPath $temporaryOutput

    if (Test-Path -LiteralPath $outputPath) {
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        $backupPath = Join-Path $backupRoot (
            "sector_v093_decision_register-$(Get-Date -Format 'yyyyMMddTHHmmssfff').xlsx"
        )
        Move-Item -LiteralPath $outputPath -Destination $backupPath
        Write-Host "Previous generated workbook preserved at $backupPath"
    }
    Move-Item -LiteralPath $sanitizedOutput -Destination $outputPath

    $workbookHash = (
        Get-FileHash -LiteralPath $outputPath -Algorithm SHA256
    ).Hash.ToUpperInvariant()
    Write-Host "Workbook: $outputPath"
    Write-Host "Workbook SHA-256: $workbookHash"
    Write-Host "Canonical LF-normalized Markdown SHA-256: $decisionSha"
    Write-Host "PDF previews: $previewRoot"
}
finally {
    if ($null -ne $workbook) {
        try { $workbook.Close($false) } catch { }
    }
    if ($null -ne $excel) {
        try { $excel.Quit() } catch { }
    }
    foreach ($partialPath in @($temporaryOutput, $sanitizedOutput)) {
        if (Test-Path -LiteralPath $partialPath) {
            try { Remove-Item -LiteralPath $partialPath } catch { }
        }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
