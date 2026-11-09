[CmdletBinding()]
param(
    # 略過啟動煙霧測試（僅在執行環境無法開啟桌面視窗時使用）
    [switch]$SkipSmokeTest
)

$commonScript = Join-Path $PSScriptRoot "lib\Common.ps1"
if (-not (Test-Path -LiteralPath $commonScript))
{
    throw "找不到共用函式庫：$commonScript"
}
. $commonScript
Initialize-ScriptEnvironment

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$projectPath = Join-Path $repoRoot "src\MinecraftServerManager.App\MinecraftServerManager.App.csproj"
$outputRoot = Join-Path $repoRoot "output"
$publishStartedAt = Get-Date

if (Test-Path -LiteralPath $outputRoot)
{
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
}
[System.IO.Directory]::CreateDirectory($outputRoot) | Out-Null

Write-Host "=== 發布單一自包含執行檔 (WinUI 3) ==="

& dotnet publish $projectPath -o $outputRoot
if ($LASTEXITCODE -ne 0)
{
    throw "C# 發布建置失敗 (ExitCode: $LASTEXITCODE)"
}

# 發布後斷言：輸出目錄只有單一 MinecraftServerManager.exe，不得有 .dll、.pdb、.pri 或子資料夾
$outputItems = @(Get-ChildItem -LiteralPath $outputRoot)
$extraneousItems = @($outputItems | Where-Object { $_.Name -ne "MinecraftServerManager.exe" })
if ($extraneousItems.Count -gt 0)
{
    $itemNames = ($extraneousItems | Select-Object -ExpandProperty Name) -join ", "
    throw "發布目錄存在非預期的額外檔案或子目錄（單檔模式斷言失敗）：$itemNames"
}

$targetExe = Join-Path $outputRoot "MinecraftServerManager.exe"
if (-not (Test-Path -LiteralPath $targetExe -PathType Leaf))
{
    throw "發布成功但找不到預期的 EXE：$targetExe"
}

# 啟動煙霧測試：於雜湊產生前執行，確保 EXE 旁零新檔案的斷言不受 .sha256 影響
if ($SkipSmokeTest)
{
    Write-Warning "已指定 -SkipSmokeTest，略過啟動煙霧測試"
}
else
{
    Write-Host "=== 執行啟動煙霧測試 (--smoke-test) ==="
    $smokeDataDir = Join-Path ([System.IO.Path]::GetTempPath()) ("msm_smoke_" + [Guid]::NewGuid().ToString("N"))
    [System.IO.Directory]::CreateDirectory($smokeDataDir) | Out-Null
    $smokeProc = $null
    try
    {
        $smokePsi = [System.Diagnostics.ProcessStartInfo]::new($targetExe, "--smoke-test")
        $smokePsi.EnvironmentVariables["MSM_USER_DATA_DIR"] = $smokeDataDir
        $smokePsi.UseShellExecute = $false
        $smokeProc = [System.Diagnostics.Process]::Start($smokePsi)
        if (-not $smokeProc.WaitForExit(30000))
        {
            $smokeProc.Kill($true)
            throw "煙霧測試逾時（30 秒未正常結束）"
        }
        if ($smokeProc.ExitCode -ne 0)
        {
            throw "煙霧測試失敗，結束代碼：$($smokeProc.ExitCode)"
        }
        $afterItems = @(Get-ChildItem -LiteralPath $outputRoot | Select-Object -ExpandProperty Name)
        $newItems = @($afterItems | Where-Object { $_ -ne "MinecraftServerManager.exe" })
        if ($newItems.Count -gt 0)
        {
            throw "煙霧測試後 EXE 旁出現新檔案或資料夾：$($newItems -join ', ')"
        }
        Write-Host "煙霧測試通過：30 秒內正常以結束代碼 0 離開，且 EXE 旁零新檔案。" -ForegroundColor Green
    }
    finally
    {
        if ($null -ne $smokeProc)
        {
            $smokeProc.Dispose()
        }
        if (Test-Path -LiteralPath $smokeDataDir)
        {
            try
            {
                Remove-Item -LiteralPath $smokeDataDir -Recurse -Force
            }
            catch
            {
                Write-Warning "無法清理煙霧測試暫存目錄 ${smokeDataDir}：$($_.Exception.Message)"
            }
        }
    }
}

$targetSha = Write-Sha256File -LiteralPath $targetExe

$elapsed = (Get-Date) - $publishStartedAt
Write-Host "=== 發布摘要 ==="
Write-Host ("總耗時：{0}" -f $elapsed.ToString("hh\:mm\:ss\.fff"))
Write-Host "----------------------------------------"
Write-Host "成品名稱：$([System.IO.Path]::GetFileName($targetExe))"
Write-Host ("檔案大小：{0:N2} MB" -f ((Get-Item -LiteralPath $targetExe).Length / 1MB))
Write-Host "SHA-256 ：$((Get-Content -LiteralPath $targetSha -Raw).Trim())"
