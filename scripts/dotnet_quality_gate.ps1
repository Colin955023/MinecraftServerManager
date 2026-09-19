$env:DOTNET_CLI_FORCE_UTF8_ENCODING = "1"
$env:MSBUILDDISABLENODEREUSE = "1"
$env:DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER = "1"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$solutionPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\MinecraftServerManager.sln"))
$solutionDir = Split-Path -Parent $solutionPath

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
        $extraArgs += @("-m:1", "-p:UseSharedCompilation=false", "-nodereuse:false")
    }
    & dotnet @Arguments @extraArgs
    if ($LASTEXITCODE -ne 0) {
        throw "C# 門禁失敗：$Name"
    }
}

function Test-SecretsAndPrivacy {
    Write-Host "=== 隱私與機密資訊檢查 (Gitleaks) ==="

    # CI 環境由 gitleaks/gitleaks-action 負責機密掃描，腳本不重複執行
    $isCi = ($env:CI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true')
    if ($isCi) {
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
            Write-Warning "安裝完成但當前 Session 仍未找到 gitleaks 命令，請確認 Path 設定"
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

# 1. 隱私與機密安全檢查（Gitleaks）
Test-SecretsAndPrivacy

# 2. 還原套件
Invoke-DotnetStep "還原套件" @("restore", $solutionPath)

# 3. 程式碼排版與格式檢查（原生 dotnet format，本機自動修復，CI 強制無變更驗證）
$isCiEnvironment = ($env:CI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true')
if (-not $isCiEnvironment) {
    Write-Host "本機環境：自動修復程式碼風格、空白字元與可修正之分析器規則..."
    & dotnet format $solutionPath --no-restore
}
Invoke-DotnetStep "格式檢查" @("format", $solutionPath, "--verify-no-changes", "--no-restore")

# 4. Release 建置（包含 Roslyn Analyzers、未使用定義檢驗、程式碼品質強制檢查）
Invoke-DotnetStep "Release 建置（品質與未使用定義檢驗）" @("build", $solutionPath, "-c", "Release")

# 5. 單元測試與整合測試
Invoke-DotnetStep "測試" @("test", $solutionPath, "-c", "Release", "--no-build")

Write-Host "=== C# 門禁通過 ==="
