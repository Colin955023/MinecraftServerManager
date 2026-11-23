#Requires -Version 7.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$commonScript = Join-Path $PSScriptRoot "lib\Common.ps1"
if (-not (Test-Path -LiteralPath $commonScript))
{
    throw "C# 門禁失敗：找不到共用函式庫 $commonScript"
}
. $commonScript
Initialize-ScriptEnvironment

$solutionDir = Get-RepoRoot
$solutionPath = Join-Path $solutionDir "MinecraftServerManager.slnx"

$isCiEnvironment = Test-CiEnvironment

function Invoke-DotnetStep
{
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Host "=== $Name ==="
    & dotnet @Arguments
    if ($LASTEXITCODE -ne 0)
    {
        throw "C# 門禁失敗：$Name"
    }
}

function Test-SecretsAndPrivacy
{
    Write-Host "=== 隱私與機密資訊檢查 (Gitleaks) ==="

    # CI 環境由 gitleaks/gitleaks-action 負責機密掃描，腳本不重複執行
    if ($isCiEnvironment)
    {
        Write-Host "偵測到 CI 環境，Gitleaks 檢查已由 GitHub Action 步驟負責，腳本跳過"
        return
    }

    $gitleaksCmd = Get-Command gitleaks -ErrorAction SilentlyContinue
    if ($null -eq $gitleaksCmd)
    {
        throw "C# 門禁失敗：未偵測到 gitleaks 命令，請先安裝 Gitleaks（例如 winget install Gitleaks.Gitleaks）以啟用隱私防護"
    }

    Write-Host "偵測到 Gitleaks："
    & gitleaks version
    & gitleaks dir $solutionDir --redact --verbose
    if ($LASTEXITCODE -ne 0)
    {
        throw "C# 門禁失敗：Gitleaks 偵測到敏感機密或私鑰外洩"
    }
}

function Test-VersionConsistency
{
    Write-Host "=== 版本定義單一事實來源檢查 (Directory.Build.props) ==="
    $version = Get-ProjectVersion -RepoRoot $solutionDir
    Write-Host "專案版本 (Directory.Build.props): $version"

    foreach ($project in Get-ChildItem -LiteralPath $solutionDir -Filter "*.csproj" -Recurse -File)
    {
        [xml]$projectXml = Get-Content -LiteralPath $project.FullName -Raw -Encoding UTF8
        if ($null -ne $projectXml.SelectSingleNode("//Version"))
        {
            throw "C# 門禁失敗：$($project.Name) 不得定義 <Version>，版本統一由 Directory.Build.props 管理"
        }
    }

    $changelogPath = Join-Path $solutionDir "CHANGELOG.md"
    $changelog = Get-Content -LiteralPath $changelogPath -Raw -Encoding UTF8
    if ($null -eq (Get-ChangelogSection -Changelog $changelog -Version $version))
    {
        throw "C# 門禁失敗：CHANGELOG.md 缺少版本 $version 的章節或內容空白"
    }

    # 網頁版本字樣以 data-app-version 標記，每個標記內文須恰含一個與專案版本相同的版本號
    $indexPath = Join-Path $solutionDir "docs\index.html"
    $html = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8
    $markers = @([regex]::Matches($html, '<\w+\b[^>]*\bdata-app-version\b[^>]*>([^<]*)'))
    if ($markers.Count -eq 0)
    {
        throw "C# 門禁失敗：docs/index.html 找不到 data-app-version 版本標記"
    }
    foreach ($marker in $markers)
    {
        $text = $marker.Groups[1].Value
        $found = @([regex]::Matches($text, '\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?'))
        if ($found.Count -ne 1 -or $found[0].Value -ne $version)
        {
            throw "C# 門禁失敗：docs/index.html 版本標記「$($text.Trim())」與 Directory.Build.props ($version) 不一致"
        }
    }
    Write-Host "docs/index.html 版本標記 $($markers.Count) 處一致"
}

function Test-ScriptEncoding
{
    Write-Host "=== 腳本編碼檢查 (UTF-8 with BOM) ==="
    $scriptsDir = Join-Path $solutionDir "scripts"
    $ps1Files = Get-ChildItem -LiteralPath $scriptsDir -Filter "*.ps1" -Recurse -File
    foreach ($file in $ps1Files)
    {
        if (-not (Test-Utf8Bom -Path $file.FullName))
        {
            throw "C# 門禁失敗：腳本 $($file.Name) 未以 UTF-8 with BOM (0xEF, 0xBB, 0xBF) 格式儲存"
        }
    }
}

Test-ScriptEncoding
Test-VersionConsistency
Test-SecretsAndPrivacy
Invoke-DotnetStep "還原套件（鎖定模式）" @("restore", $solutionPath, "--locked-mode")

if ($isCiEnvironment)
{
    Invoke-DotnetStep "格式檢查" @("format", $solutionPath, "--verify-no-changes", "--no-restore")
}
else
{
    Invoke-DotnetStep "格式檢查與自動修復" @("format", $solutionPath, "--no-restore")
}

Invoke-DotnetStep "Release 建置（品質與未使用定義檢驗）" @(
    "build", $solutionPath, "-c", "Release", "--no-restore"
)

$minimumLineCoveragePercent = 80.0
$minimumBranchCoveragePercent = 70.0

# 結合「原始碼靜態下限」與「xUnit 預先列舉展開數」計算期望測試總數，避免低估 [MemberData]/[ClassData]
function Get-ExpectedTestCount
{
    $testsDir = Join-Path $solutionDir "tests"
    $staticCount = 0
    $dynamicMethods = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)

    foreach ($file in Get-ChildItem -LiteralPath $testsDir -Filter "*.cs" -Recurse -File)
    {
        if ($file.FullName -match '[\\/](obj|bin)[\\/]') { continue }
        $theorySkipped = $false
        $hasDynamicData = $false
        foreach ($line in [System.IO.File]::ReadAllLines($file.FullName))
        {
            $t = $line.Trim()
            if ($t -match '^\[Theory\b') { $theorySkipped = ($t -match '\bSkip\s*=') }
            elseif ($t -match '^\[Fact\b') { $theorySkipped = $false; $hasDynamicData = $false; if ($t -notmatch '\bSkip\s*=') { $staticCount++ } }
            elseif ($t -match '^\[InlineData\b') { if (-not $theorySkipped -and $t -notmatch '\bSkip\s*=') { $staticCount++ } }
            elseif ($t -match '^\[(?:MemberData|ClassData)\b') { if (-not $theorySkipped -and $t -notmatch '\bSkip\s*=') { $staticCount++; $hasDynamicData = $true } }
            elseif ($t -match '^(?:public|internal)\b.*\b([A-Za-z_][A-Za-z0-9_]*)\s*\(')
            {
                if ($hasDynamicData) { $null = $dynamicMethods.Add($Matches[1]) }
                $theorySkipped = $false
                $hasDynamicData = $false
            }
        }
    }

    $enumerated = @(
        foreach ($exe in Get-ChildItem -LiteralPath $testsDir -Filter "*Tests.exe" -Recurse -File | Where-Object { $_.FullName -match '[\\/]bin[\\/]Release[\\/]' })
        {
            $out = & $exe.FullName -preEnumerateTheories -list tests/json
            if ($LASTEXITCODE -ne 0) { throw "C# 門禁失敗：預先列舉測試失敗（$($exe.Name)）" }
            $json = @($out) | Where-Object { $_ -match '^\s*\[' } | Select-Object -Last 1
            if ([string]::IsNullOrWhiteSpace($json)) { throw "C# 門禁失敗：無法解析預先列舉輸出（$($exe.Name)）" }
            $json | ConvertFrom-Json
        }
    )

    if ($staticCount -le 0 -or $enumerated.Count -lt $staticCount)
    {
        throw "C# 門禁失敗：預期測試數異常（靜態下限 $staticCount、預先列舉 $($enumerated.Count)）"
    }
    foreach ($method in $dynamicMethods)
    {
        $pattern = "\.$([regex]::Escape($method))(?:\(|$)"
        if (@($enumerated | Where-Object { $_ -match $pattern }).Count -eq 0)
        {
            throw "C# 門禁失敗：動態測試方法 $method 未展開任何案例"
        }
    }

    Write-Host "預期測試數量（預先列舉 $($enumerated.Count) 項，靜態下限 $staticCount 項）：$($enumerated.Count)"
    return $enumerated.Count
}

$minimumExpectedTests = Get-ExpectedTestCount
$testResultsDir = Join-Path $solutionDir "TestResults"
$testArguments = @(
    "test", $solutionPath, "-c", "Release", "--no-build",
    "--minimum-expected-tests", $minimumExpectedTests,
    "--results-directory", $testResultsDir,
    "--", "--coverage", "--coverage-output-format", "cobertura"
)
if ($isCiEnvironment)
{
    $testArguments += "--report-trx"
}

# 彙總 cobertura 報告的行與分支涵蓋率並強制門檻驗證
# 各測試專案的報告涵蓋同一份原始碼，故依「檔案＋行號」取聯集（同行取最高命中），並排除原始碼產生器輸出（obj）與測試碼
function Assert-CoverageThreshold
{
    param(
        [string]$ResultsDirectory,
        [double]$MinimumLinePercent,
        [double]$MinimumBranchPercent
    )

    $reports = @()
    if (Test-Path -LiteralPath $ResultsDirectory)
    {
        $reports = @(Get-ChildItem -LiteralPath $ResultsDirectory -Filter "*.cobertura.xml" -Recurse -File)
    }

    if ($reports.Count -eq 0)
    {
        throw "C# 門禁失敗：未找到涵蓋率報告（*.cobertura.xml），無法驗證涵蓋率門檻"
    }

    $lines = @{}
    $branches = @{}
    foreach ($report in $reports)
    {
        $xml = [xml](Get-Content -LiteralPath $report.FullName -Raw -Encoding UTF8)
        foreach ($class in $xml.SelectNodes("//class"))
        {
            $file = $class.GetAttribute("filename")
            if ([System.IO.Path]::IsPathRooted($file))
            {
                $file = [System.IO.Path]::GetRelativePath($solutionDir, $file)
            }
            if ($file -match '^tests[\\/]|(^|[\\/])obj[\\/]') { continue }
            foreach ($line in $class.SelectNodes("lines/line"))
            {
                $key = "$file|$($line.GetAttribute('number'))"
                $hits = [int]$line.GetAttribute("hits")
                if (-not $lines.ContainsKey($key) -or $lines[$key] -lt $hits) { $lines[$key] = $hits }
                $condition = $line.GetAttribute("condition-coverage")
                if ($condition -match '\((\d+)/(\d+)\)')
                {
                    $covered = [int]$Matches[1]; $total = [int]$Matches[2]
                    if (-not $branches.ContainsKey($key))
                    {
                        $branches[$key] = @{ Covered = $covered; Total = $total }
                    }
                    else
                    {
                        if ($covered -gt $branches[$key].Covered) { $branches[$key].Covered = $covered }
                        if ($total -gt $branches[$key].Total) { $branches[$key].Total = $total }
                    }
                }
            }
        }
    }

    $linesValid = $lines.Count
    $linesCovered = @($lines.Values | Where-Object { $_ -gt 0 }).Count
    $branchesValid = [long]($branches.Values | ForEach-Object { $_.Total } | Measure-Object -Sum).Sum
    $branchesCovered = [long]($branches.Values | ForEach-Object { $_.Covered } | Measure-Object -Sum).Sum
    $linePercent = if ($linesValid -gt 0) { 100.0 * $linesCovered / $linesValid } else { 0.0 }
    $branchPercent = if ($branchesValid -gt 0) { 100.0 * $branchesCovered / $branchesValid } else { 0.0 }
    Write-Host ("涵蓋率：行 {0:N1}%（{1}／{2}，門檻 {3:N1}%），分支 {4:N1}%（{5}／{6}，門檻 {7:N1}%）" -f $linePercent, $linesCovered, $linesValid, $MinimumLinePercent, $branchPercent, $branchesCovered, $branchesValid, $MinimumBranchPercent)

    if ($linePercent -lt $MinimumLinePercent)
    {
        throw ("C# 門禁失敗：行涵蓋率 {0:N1}% 低於門檻 {1:N1}%" -f $linePercent, $MinimumLinePercent)
    }
    if ($branchPercent -lt $MinimumBranchPercent)
    {
        throw ("C# 門禁失敗：分支涵蓋率 {0:N1}% 低於門檻 {1:N1}%" -f $branchPercent, $MinimumBranchPercent)
    }
}

try
{
    Invoke-DotnetStep "測試" $testArguments
    Assert-CoverageThreshold -ResultsDirectory $testResultsDir -MinimumLinePercent $minimumLineCoveragePercent -MinimumBranchPercent $minimumBranchCoveragePercent
}
finally
{
    if (-not $isCiEnvironment -and (Test-Path -LiteralPath $testResultsDir))
    {
        try
        {
            Remove-Item -LiteralPath $testResultsDir -Recurse -Force
        }
        catch
        {
            Write-Warning "無法清理測試結果目錄 ${testResultsDir}：$($_.Exception.Message)"
        }
    }
}

Write-Host "=== C# 門禁通過 ==="
