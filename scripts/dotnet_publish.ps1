#Requires -Version 7.1
[CmdletBinding()]
param(
    # 發布後啟動主程式驗證可正常初始化（預設不啟用）
    [switch]$SmokeTest
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "lib\Common.ps1")
Initialize-ScriptEnvironment

$repoRoot = Get-RepoRoot
$projectPath = Join-Path $repoRoot "src\MinecraftServerManager.App\MinecraftServerManager.App.csproj"
$outputRoot = Join-Path $repoRoot "output"
$exeName = "MinecraftServerManager.exe"
$targetExe = Join-Path $outputRoot $exeName

function Assert-SingleExecutable([string]$Stage)
{
    $names = @(Get-ChildItem -LiteralPath $outputRoot | Select-Object -ExpandProperty Name)
    if ($names.Count -ne 1 -or $names[0] -ne $exeName)
    {
        throw "${Stage}輸出目錄應只有 ${exeName}，實際內容：$($names -join ', ')"
    }
}

if (Test-Path -LiteralPath $outputRoot)
{
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
}

Write-Host "=== 發布單一自包含執行檔 ==="
& dotnet publish $projectPath -o $outputRoot
if ($LASTEXITCODE -ne 0)
{
    throw "發布建置失敗 (ExitCode: $LASTEXITCODE)"
}
Assert-SingleExecutable "發布後"

if ($SmokeTest)
{
    Write-Host "=== 執行啟動煙霧測試 ==="
    Invoke-SmokeTest -ExePath $targetExe
}

if (Test-CiEnvironment)
{
    $null = Write-Sha256File -LiteralPath $targetExe
}

Write-Host ("檔案大小：{0:N2} MB" -f ((Get-Item -LiteralPath $targetExe).Length / 1MB))
$hash = (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "SHA-256 ：$hash  $exeName"
