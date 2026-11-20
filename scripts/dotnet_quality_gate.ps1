#Requires -Version 7.1
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
        Write-Warning "未偵測到 gitleaks 命令，請安裝 Gitleaks 以啟用隱私防護"
        return
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

    $indexPath = Join-Path $solutionDir "docs\index.html"
    if (Test-Path -LiteralPath $indexPath)
    {
        $html = [System.IO.File]::ReadAllText($indexPath)
        $versionPattern = '(?<=(?:<title>[^<]*? |>|</strong> )v)\d+\.\d+\.\d+|(?<=版本 )\d+\.\d+\.\d+'
        $mismatched = @([regex]::Matches($html, $versionPattern) | Where-Object { $_.Value -ne $version })
        if ($mismatched.Count -gt 0)
        {
            if ($isCiEnvironment)
            {
                throw "C# 門禁失敗：docs/index.html 的版本字樣 ($($mismatched[0].Value)) 與 Directory.Build.props ($version) 不一致"
            }
            Write-Host "docs/index.html 版本字樣與 $version 不一致，自動同步"
            [System.IO.File]::WriteAllText($indexPath, [regex]::Replace($html, $versionPattern, $version), $Utf8NoBom)
        }
    }
}

function Test-ScriptEncoding
{
    Write-Host "=== 腳本編碼檢查 (UTF-8 with BOM) ==="
    $scriptsDir = Join-Path $solutionDir "scripts"
    $ps1Files = Get-ChildItem -LiteralPath $scriptsDir -Filter "*.ps1" -Recurse -File
    foreach ($file in $ps1Files)
    {
        $buffer = [byte[]]::new(3); $fs = [System.IO.File]::OpenRead($file.FullName); try { $read = $fs.Read($buffer, 0, 3) } finally { $fs.Dispose() }
        if ($read -lt 3 -or $buffer[0] -ne 0xEF -or $buffer[1] -ne 0xBB -or $buffer[2] -ne 0xBF)
        {
            throw "C# 門禁失敗：腳本 $($file.Name) 未以 UTF-8 with BOM (0xEF, 0xBB, 0xBF) 格式儲存"
        }
    }
}

Test-ScriptEncoding
Test-VersionConsistency
Test-SecretsAndPrivacy
Invoke-DotnetStep "還原套件" @("restore", $solutionPath)

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

# 期望測試數量由原始碼動態計算：每個 [Fact] 與每筆 [InlineData] 各算一項，避免手動維護數字
function Get-ExpectedTestCount
{
    $testsDir = Join-Path $solutionDir "tests"
    $count = 0
    foreach ($file in Get-ChildItem -LiteralPath $testsDir -Filter "*.cs" -Recurse -File)
    {
        if ($file.FullName -match '[\\/](obj|bin)[\\/]') { continue }
        $count += @(Select-String -LiteralPath $file.FullName -Pattern '^\s*\[(?:Fact|InlineData)\b').Count
    }
    return $count
}

$minimumExpectedTests = Get-ExpectedTestCount
if ($minimumExpectedTests -le 0)
{
    throw "C# 門禁失敗：未在 tests 目錄偵測到任何 [Fact] 或 [InlineData] 測試"
}
Write-Host "預期測試數量（[Fact] + [InlineData]）：$minimumExpectedTests"
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

# 彙總 cobertura 報告的行與分支涵蓋率（僅輸出數字，不設門檻）
# 各測試專案的報告涵蓋同一份原始碼，故依「檔案＋行號」取聯集（同行取最高命中），並排除原始碼產生器輸出（obj）與測試碼
function Write-CoverageSummary
{
    param([string]$ResultsDirectory)

    $reports = @()
    if (Test-Path -LiteralPath $ResultsDirectory)
    {
        $reports = @(Get-ChildItem -LiteralPath $ResultsDirectory -Filter "*.cobertura.xml" -Recurse -File)
    }

    if ($reports.Count -eq 0)
    {
        Write-Warning "未找到涵蓋率報告（*.cobertura.xml），略過涵蓋率彙總"
        return
    }

    $lines = @{}
    $branches = @{}
    foreach ($report in $reports)
    {
        $xml = [xml](Get-Content -LiteralPath $report.FullName -Raw -Encoding UTF8)
        foreach ($class in $xml.SelectNodes("//class"))
        {
            $file = $class.GetAttribute("filename")
            if ($file -match '[\\/](obj|tests)[\\/]') { continue }
            foreach ($line in $class.SelectNodes("lines/line | methods/method/lines/line"))
            {
                $key = "$file|$($line.GetAttribute('number'))"
                $hits = [int]$line.GetAttribute("hits")
                if (-not $lines.ContainsKey($key) -or $lines[$key] -lt $hits) { $lines[$key] = $hits }
                $condition = $line.GetAttribute("condition-coverage")
                if ($condition -match '\((\d+)/(\d+)\)')
                {
                    $covered = [int]$Matches[1]; $total = [int]$Matches[2]
                    if (-not $branches.ContainsKey($key) -or $branches[$key].Covered -lt $covered) { $branches[$key] = @{ Covered = $covered; Total = $total } }
                }
            }
        }
    }

    $linesValid = $lines.Count
    $linesCovered = @($lines.Values | Where-Object { $_ -gt 0 }).Count
    $branchesValid = ($branches.Values | ForEach-Object { $_.Total } | Measure-Object -Sum).Sum
    $branchesCovered = ($branches.Values | ForEach-Object { $_.Covered } | Measure-Object -Sum).Sum
    $linePercent = if ($linesValid -gt 0) { 100.0 * $linesCovered / $linesValid } else { 0.0 }
    $branchPercent = if ($branchesValid -gt 0) { 100.0 * $branchesCovered / $branchesValid } else { 0.0 }
    Write-Host ("涵蓋率：行 {0:N1}%（{1}／{2}），分支 {3:N1}%（{4}／{5}）" -f $linePercent, $linesCovered, $linesValid, $branchPercent, $branchesCovered, $branchesValid)
}

try
{
    Invoke-DotnetStep "測試" $testArguments
    Write-CoverageSummary -ResultsDirectory $testResultsDir
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
