[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "lib\Common.ps1")
Initialize-ScriptEnvironment

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
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

# CI 執行環境無互動桌面，不執行啟動煙霧測試
if ($env:GITHUB_ACTIONS -ne "true")
{
    Write-Host "=== 執行啟動煙霧測試 ==="
    $smokeDataDir = Join-Path ([System.IO.Path]::GetTempPath()) ("msm_smoke_" + [Guid]::NewGuid().ToString("N"))
    $psi = [System.Diagnostics.ProcessStartInfo]::new($targetExe, "--smoke-test")
    $psi.EnvironmentVariables["MSM_USER_DATA_DIR"] = $smokeDataDir
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    try
    {
        if (-not $proc.WaitForExit(30000))
        {
            $proc.Kill($true)
            throw "煙霧測試逾時（30 秒）"
        }
        if ($proc.ExitCode -ne 0)
        {
            throw "煙霧測試失敗，結束代碼：$($proc.ExitCode)"
        }
        Assert-SingleExecutable "煙霧測試後"
    }
    finally
    {
        $proc.Dispose()
        Remove-Item -LiteralPath $smokeDataDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$targetSha = Write-Sha256File -LiteralPath $targetExe
Write-Host ("檔案大小：{0:N2} MB" -f ((Get-Item -LiteralPath $targetExe).Length / 1MB))
Write-Host "SHA-256 ：$((Get-Content -LiteralPath $targetSha -Raw).Trim())"
