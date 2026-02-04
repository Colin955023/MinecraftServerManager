# Minecraft Server Manager - Portable Package Builder

# 強制 PowerShell 與主控台使用 UTF-8 輸出，避免在由 cmd 呼叫時出現亂碼/重複/跑版
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()

$Host.UI.RawUI.WindowTitle = "Minecraft 伺服器管理器 - 可攜式版本打包工具"
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

# 取得版本號：從 src/version_info.py 的 APP_VERSION 取得
[string]$version = ''

try {
    $pythonOut = & py -c "from src.version_info import APP_VERSION; print(APP_VERSION)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $pythonOut) {
        $version = "$pythonOut".Trim()
    }
} catch {
    Write-Host "[警告] 無法從 Python 讀取版本" -ForegroundColor Yellow
}

# 驗證版本格式，確保不是意外的物件
if (-not $version -or -not ($version -match '^\d+\.\d+\.\d+')) {
    $version = '1.6.2'
}

Write-Host "[資訊] 版本號: $version" -ForegroundColor Cyan

if (-not (Test-Path "dist\MinecraftServerManager")) {
    Write-Host "錯誤: 找不到 dist\MinecraftServerManager 資料夾。" -ForegroundColor Red
    Write-Host "請先執行 build_installer_nuitka.bat 來生成可攜式版本。" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Minecraft 伺服器管理器 - 可攜式版本打包" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] 準備說明與授權檔案（複製 LICENSE/README.md）..." -ForegroundColor Yellow

# 補充步驟：複製 LICENSE 或 README.md（若存在於專案根目錄）進入可攜版資料夾
if (Test-Path "LICENSE") {
    Copy-Item -Path "LICENSE" -Destination "dist\MinecraftServerManager\LICENSE" -Force
}
if (Test-Path "README.md") {
    Copy-Item -Path "README.md" -Destination "dist\MinecraftServerManager\README.md" -Force
}

# 檢查必要執行檔是否存在，避免建立空或不完整的壓縮檔
if (-not (Test-Path "dist\MinecraftServerManager\MinecraftServerManager.exe")) {
    Write-Host "[錯誤] 找不到 dist\\MinecraftServerManager\\MinecraftServerManager.exe，請先完成 Nuitka 打包。" -ForegroundColor Red
    pause
    exit 1
}

$zipFile = "MinecraftServerManager-v$version-portable.zip"
$zipPath = "dist\$zipFile"

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
Write-Host "[2/3] 建立 .portable 標記檔（供程式偵測為便攜模式）..." -ForegroundColor Yellow

# 建立 .portable 標記檔於可攜版資料夾（若已存在則覆寫）
$portablePath = "dist\MinecraftServerManager\.portable"
if (Test-Path $portablePath) {
    Remove-Item $portablePath -Force
}
New-Item -Path $portablePath -ItemType File -Force | Out-Null

Write-Host "[3/3] 建立可攜式版本壓縮檔..." -ForegroundColor Yellow
Compress-Archive -Path "dist\MinecraftServerManager" -DestinationPath $zipPath -Force

if (-not (Test-Path $zipPath)) {
    Write-Host "[錯誤] 壓縮檔建立失敗" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "[成功] 已建立 $zipFile" -ForegroundColor Green
Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  打包完成！" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "可攜式版本檔案：dist\$zipFile" -ForegroundColor White
Write-Host "SHA256 檔案由 GitHub Actions 自動產生" -ForegroundColor Yellow
Write-Host "解壓後即可在任何地方使用。" -ForegroundColor White
Write-Host ""
