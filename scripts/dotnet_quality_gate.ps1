$commonScript = Join-Path $PSScriptRoot "lib\Common.ps1"
if (-not (Test-Path -LiteralPath $commonScript))
{
    throw "C# 門禁失敗：找不到共用函式庫 $commonScript"
}
. $commonScript
Initialize-ScriptEnvironment

$solutionPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\MinecraftServerManager.slnx"))
$solutionDir = Split-Path -Parent $solutionPath

$isCiEnvironment = ($env:CI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true')

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
        Write-Host "CI 環境偵測到，Gitleaks 檢查已由 GitHub Action 步驟負責，腳本跳過"
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

    $appProjectPath = Join-Path $solutionDir "src\MinecraftServerManager.App\MinecraftServerManager.App.csproj"
    if (Test-Path -LiteralPath $appProjectPath)
    {
        [xml]$appProject = Get-Content -Raw -Encoding UTF8 $appProjectPath
        $versionNode = $appProject.SelectSingleNode("//Version")
        if ($null -ne $versionNode)
        {
            throw "C# 門禁失敗：App.csproj 不得硬編碼重複定義 <Version>，版本應統一由 Directory.Build.props 管理"
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
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF)
        {
            throw "C# 門禁失敗：腳本 $($file.Name) 未以 UTF-8 with BOM (0xEF, 0xBB, 0xBF) 格式儲存"
        }
    }
}

# 0. 腳本編碼檢查（UTF-8 with BOM）
Test-ScriptEncoding

# 1. 版本定義一致性檢查（Directory.Build.props）
Test-VersionConsistency

# 2. 隱私與機密安全檢查（Gitleaks）
Test-SecretsAndPrivacy

# 3. 還原套件
Invoke-DotnetStep "還原套件" @("restore", $solutionPath)

# 4. 程式碼排版與格式檢查（本機單次自動修復並檢驗，CI 強制無變更檢驗）
if ($isCiEnvironment)
{
    Invoke-DotnetStep "格式檢查" @("format", $solutionPath, "--verify-no-changes", "--no-restore")
}
else
{
    Invoke-DotnetStep "格式檢查與自動修復" @("format", $solutionPath, "--no-restore")
}

# 5. Release 建置（品質與未使用定義檢驗）
Invoke-DotnetStep "Release 建置（品質與未使用定義檢驗）" @(
    "build", $solutionPath, "-c", "Release", "--no-restore"
)

# 6. 單元測試與整合測試（以 Release 組態執行全量測試）
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
$testArguments = @(
    "test", $solutionPath, "-c", "Release", "--no-build",
    "--minimum-expected-tests", $minimumExpectedTests
)
if ($isCiEnvironment)
{
    $testArguments += @(
        "--results-directory", (Join-Path $solutionDir "TestResults"),
        "--", "--report-trx"
    )
}

try
{
    Invoke-DotnetStep "測試" $testArguments
}
finally
{
    # 7. 清理測試產生的暫存目錄
    $testResultsDir = Join-Path $solutionDir "TestResults"
    if (-not $isCiEnvironment -and (Test-Path $testResultsDir))
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
