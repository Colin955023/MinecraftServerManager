$env:DOTNET_CLI_FORCE_UTF8_ENCODING = "1"
$env:MSBUILDDISABLENODEREUSE = "1"
$env:DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER = "1"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$solutionPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\MinecraftServerManager.sln"))
$solutionDir = Split-Path -Parent $solutionPath

$isCiEnvironment = ($env:CI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true')

# 動態偵測環境 CPU 核心數並保留 1 核給系統
$maxCpuCount = [Math]::Max(1, [Environment]::ProcessorCount - 1)

function Invoke-DotnetStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Host "=== $Name ==="
    $extraArgs = @()
    if ($Arguments.Count -gt 0 -and $Arguments[0] -in @("restore", "build")) {
        $extraArgs += @("-m:$maxCpuCount", "-p:UseSharedCompilation=false", "-nodereuse:false")
    }
    & dotnet @Arguments @extraArgs
    if ($LASTEXITCODE -ne 0) {
        throw "C# 門禁失敗：$Name"
    }
}

function Test-SecretsAndPrivacy {
    Write-Host "=== 隱私與機密資訊檢查 (Gitleaks) ==="

    # CI 環境由 gitleaks/gitleaks-action 負責機密掃描，腳本不重複執行
    if ($isCiEnvironment) {
        Write-Host "CI 環境偵測到，Gitleaks 檢查已由 GitHub Action 步驟負責，腳本跳過"
        return
    }

    $gitleaksCmd = Get-Command gitleaks -ErrorAction SilentlyContinue
    if ($null -eq $gitleaksCmd) {
        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue

        if ($null -eq $wingetCmd) {
            Write-Warning "未偵測到 winget 套件管理器，無法自動安裝 Gitleaks，請手動安裝以啟用隱私防護"
            return
        }

        $shouldInstall = $false
        if ([Environment]::UserInteractive) {
            $choice = Read-Host "未偵測到 gitleaks 命令，是否透過 winget 安裝 Gitleaks？(Y/N)"
            if ($choice -match '^[Yy]') {
                $shouldInstall = $true
            }
        }

        if ($shouldInstall) {
            Write-Host "正在透過 winget 安裝 Gitleaks..."
            & winget install --id Gitleaks.Gitleaks -e --accept-source-agreements --accept-package-agreements
        } else {
            Write-Warning "已跳過 Gitleaks 安裝，無法執行機密與隱私安全檢查"
            return
        }

        # 重新整理環境變數 Path 並重新偵測
        $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path = "$machinePath;$userPath"
        $gitleaksCmd = Get-Command gitleaks -ErrorAction SilentlyContinue
        if ($null -eq $gitleaksCmd) {
            Write-Warning "安裝完成但目前工作階段仍未找到 gitleaks 命令，請確認 Path 設定"
            return
        }
    }

    Write-Host "偵測到 Gitleaks："
    & gitleaks version
    & gitleaks detect --no-git --source $solutionDir --verbose
    if ($LASTEXITCODE -ne 0) {
        throw "C# 門禁失敗：Gitleaks 偵測到敏感機密或私鑰外洩"
    }
}

$commonScript = Join-Path $PSScriptRoot "lib\Common.ps1"
if (-not (Test-Path -LiteralPath $commonScript)) {
    throw "C# 門禁失敗：找不到共用函式庫 $commonScript"
}
. $commonScript

function Test-VersionConsistency {
    Write-Host "=== 版本定義單一事實來源檢查 (Directory.Build.props) ==="
    $version = Get-ProjectVersion -RepoRoot $solutionDir
    Write-Host "專案版本 (Directory.Build.props): $version"

    $appProjectPath = Join-Path $solutionDir "src\MinecraftServerManager.App\MinecraftServerManager.App.csproj"
    if (Test-Path -LiteralPath $appProjectPath) {
        [xml]$appProject = Get-Content -Raw -Encoding UTF8 $appProjectPath
        $versionNode = $appProject.SelectSingleNode("//Version")
        if ($null -ne $versionNode) {
            throw "C# 門禁失敗：App.csproj 不得硬編碼重複定義 <Version>，版本應統一由 Directory.Build.props 管理"
        }
    }
}

function Test-ScriptEncoding {
    Write-Host "=== 腳本編碼檢查 (UTF-8 with BOM) ==="
    $scriptsDir = Join-Path $solutionDir "scripts"
    $ps1Files = Get-ChildItem -LiteralPath $scriptsDir -Filter "*.ps1" -Recurse -File
    foreach ($file in $ps1Files) {
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
            throw "C# 門禁失敗：腳本 $($file.Name) 未以 UTF-8 with BOM (0xEF, 0xBB, 0xBF) 格式儲存"
        }
    }
}

# 0. 腳本編碼檢查（UTF-8 with BOM）
Test-ScriptEncoding

# 1. 版本定義一致性檢查（AppInfo.cs vs App.csproj）
Test-VersionConsistency

# 2. 隱私與機密安全檢查（Gitleaks）
Test-SecretsAndPrivacy

# 3. 還原套件
Invoke-DotnetStep "還原套件" @("restore", $solutionPath)

# 4. 程式碼排版與格式檢查（本機單次自動修復並檢驗，CI 強制無變更檢驗）
if ($isCiEnvironment) {
    Invoke-DotnetStep "格式檢查" @("format", $solutionPath, "--verify-no-changes", "--no-restore")
} else {
    Invoke-DotnetStep "格式檢查與自動修復" @("format", $solutionPath, "--no-restore")
}

# 5. Release 建置（包含 Roslyn Analyzers、未使用定義檢驗、程式碼品質強制檢查，前置已完整還原故免重複評估套件）
Invoke-DotnetStep "Release 建置（品質與未使用定義檢驗）" @("build", $solutionPath, "-c", "Release", "--no-restore")

# 6. 單元測試與整合測試
$minimumExpectedTests = 515
$testArguments = @(
    "test", $solutionPath, "-c", "Release", "--no-build",
    "--minimum-expected-tests", $minimumExpectedTests
)
if ($isCiEnvironment) {
    $testArguments += @(
        "--results-directory", (Join-Path $solutionDir "TestResults"),
        "--", "--report-trx"
    )
}

try {
    Invoke-DotnetStep "測試" $testArguments
}
finally {
    # 7. 清理測試產生的暫存目錄
    $testResultsDir = Join-Path $solutionDir "TestResults"
    if (-not $isCiEnvironment -and (Test-Path $testResultsDir)) {
        Remove-Item -Path $testResultsDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "=== C# 門禁通過 ==="
