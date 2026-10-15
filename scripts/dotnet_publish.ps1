$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$projectPath = Join-Path $repoRoot "src\MinecraftServerManager.App\MinecraftServerManager.App.csproj"
$iconPath = Join-Path $repoRoot "assets\icon.ico"
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "找不到應用程式圖示資產：$iconPath"
}
$outputRoot = Join-Path $repoRoot "output"
$publishStartedAt = Get-Date

if (-not (Test-Path -LiteralPath $outputRoot)) {
    [System.IO.Directory]::CreateDirectory($outputRoot) | Out-Null
}

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
        "-p:PublishSingleFile=true",
        "-p:IncludeNativeLibrariesForSelfExtract=true",
        "-p:ApplicationIcon=$iconPath",
        "-p:DebugType=None",
        "-p:DebugSymbols=false",
        "-p:PublishDocumentationFiles=false",
        "-p:AllowedReferenceRelatedFileExtensions=none",
        "-p:DebuggerSupport=false",
        "-p:EventSourceSupport=false",
        "-p:MetadataUpdaterSupport=false",
        "-p:UseSystemResourceKeys=true",
        "-p:UseSharedCompilation=false",
        "-nodereuse:false",
        "-m:1",
        "-o", $tempOutput
    )
    if ($SelfContained -eq "true") {
        $arguments += "-p:EnableCompressionInSingleFile=true"
    }

    & dotnet @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "C# 發布失敗：$Name"
    }

    $sourceExe = Join-Path $tempOutput "MinecraftServerManager.App.exe"
    if (Test-Path -LiteralPath $sourceExe) {
        $targetExe = Join-Path $outputRoot "MinecraftServerManager-$Name.exe"
        $targetSha = "$targetExe.sha256"
        $hash = (Get-FileHash -LiteralPath $sourceExe -Algorithm SHA256).Hash
        Move-Item -LiteralPath $sourceExe -Destination $targetExe -Force
        Set-Content -LiteralPath $targetSha -Value "$hash  MinecraftServerManager-$Name.exe" -Encoding UTF8
    }

    Remove-Item -LiteralPath $tempOutput -Recurse -Force
}

Publish-App -Name "self-contained" -SelfContained "true"
Publish-App -Name "framework-dependent" -SelfContained "false"

$elapsed = (Get-Date) - $publishStartedAt
Write-Host "=== 雙版本發布摘要 ==="
Write-Host ("總耗時：{0}" -f $elapsed.ToString("hh\:mm\:ss\.fff"))
Write-Host "圖示資產：已綁定 $iconPath"
Write-Host "發布目錄：$outputRoot"

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
