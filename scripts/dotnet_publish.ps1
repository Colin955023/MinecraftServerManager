$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$projectPath = Join-Path $repoRoot "src\MinecraftServerManager.App\MinecraftServerManager.App.csproj"
$outputRoot = Join-Path $repoRoot "output"
$publishStartedAt = Get-Date

if (-not (Test-Path -LiteralPath $outputRoot)) {
    [System.IO.Directory]::CreateDirectory($outputRoot) | Out-Null
}

# 動態偵測環境 CPU 核心數並保留 1 核給系統
$maxCpuCount = [Math]::Max(1, [Environment]::ProcessorCount - 1)

function Publish-App {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$SelfContained
    )

    $tempOutput = Join-Path $outputRoot $Name
    if (Test-Path -LiteralPath $tempOutput) {
        Remove-Item -LiteralPath $tempOutput -Recurse -Force
    }

    Write-Host "=== 發布 $Name ==="
    $arguments = @(
        "publish", $projectPath,
        "-c", "Release",
        "-r", "win-x64",
        "--self-contained", $SelfContained,
        "-nodereuse:false",
        "-m:$maxCpuCount",
        "-o", $tempOutput
    )
    if ($SelfContained -eq "true") {
        $arguments += @(
            "-p:IncludeNativeLibrariesForSelfExtract=true",
            "-p:EnableCompressionInSingleFile=true"
        )
    }

    & dotnet @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "C# 發布失敗：$Name"
    }

    $sourceExe = Join-Path $tempOutput "MinecraftServerManager.App.exe"

    if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) {
        throw "發布成功但找不到預期的 EXE：$sourceExe"
    }

    $targetExe = Join-Path $outputRoot "MinecraftServerManager-$Name.exe"

    Copy-Item -LiteralPath $sourceExe -Destination $targetExe -Force

    $hash = (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash
    $targetSha = "$targetExe.sha256"

    [System.IO.File]::WriteAllText(
        $targetSha,
        "$hash  $([System.IO.Path]::GetFileName($targetExe))`n",
        [System.Text.UTF8Encoding]::new($false)
    )

    Remove-Item -LiteralPath $tempOutput -Recurse -Force
}

Write-Host "=== 還原發布套件 (win-x64) ==="
& dotnet restore $projectPath -r win-x64 -m:$maxCpuCount
if ($LASTEXITCODE -ne 0) {
    throw "C# 還原套件失敗"
}

Publish-App -Name "self-contained" -SelfContained "true"
Publish-App -Name "framework-dependent" -SelfContained "false"

$elapsed = (Get-Date) - $publishStartedAt
Write-Host "=== 雙版本發布摘要 ==="
Write-Host ("總耗時：{0}" -f $elapsed.ToString("hh\:mm\:ss\.fff"))

Get-ChildItem -LiteralPath $outputRoot -Filter "*.exe" -File | Sort-Object Name | ForEach-Object {
    Write-Host "----------------------------------------"
    Write-Host "成品名稱：$($_.Name)"
    Write-Host ("檔案大小：{0:N2} MB" -f ($_.Length / 1MB))
    $hashFile = "$($_.FullName).sha256"
    if (Test-Path -LiteralPath $hashFile) {
        $hashContent = Get-Content -LiteralPath $hashFile -Raw
        Write-Host "SHA-256 ：$($hashContent.Trim())"
    }
}
