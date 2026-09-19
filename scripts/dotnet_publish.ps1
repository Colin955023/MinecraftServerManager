[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [string]$OutputRoot = "output",
    [switch]$NoRestore
)

$env:DOTNET_CLI_FORCE_UTF8_ENCODING = "1"
$env:MSBUILDDISABLENODEREUSE = "1"
$env:DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER = "1"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$iconPath = Join-Path $repoRoot "assets\icon.ico"
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "找不到應用程式圖示資產：$iconPath"
}
$projectPath = Join-Path $repoRoot "src\MinecraftServerManager.App\MinecraftServerManager.App.csproj"
$outputRootPath = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputRoot))
}
$publishStartedAt = Get-Date

function Invoke-PublishVariant {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$SelfContained
    )

    $variantOutput = Join-Path $outputRootPath $Name
    if (Test-Path -LiteralPath $variantOutput) {
        Get-ChildItem -LiteralPath $variantOutput -Force | Remove-Item -Recurse -Force
    } else {
        [System.IO.Directory]::CreateDirectory($variantOutput) | Out-Null
    }

    $arguments = @(
        "publish", $projectPath,
        "-c", $Configuration,
        "-r", $Runtime,
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
        "-o", $variantOutput
    )
    if ($SelfContained -eq "true") {
        $arguments += "-p:EnableCompressionInSingleFile=true"
    }
    if ($NoRestore) {
        $arguments += "--no-restore"
    }

    Write-Host "=== 發布 $Name ==="
    & dotnet @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "C# 發布失敗：$Name"
    }

    Get-ChildItem -LiteralPath $variantOutput -Filter "*.xml" -File -Recurse | Remove-Item -Force

    # 將輸出 EXE 重新命名為使用者指定的簡潔標準名稱
    $targetExeName = "MinecraftServerManager-$Name.exe"
    $defaultExe = Join-Path $variantOutput "MinecraftServerManager.App.exe"
    if (Test-Path -LiteralPath $defaultExe) {
        Rename-Item -LiteralPath $defaultExe -NewName $targetExeName -Force
    }
}

function Format-ByteSize {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) {
        return "{0:N2} GB" -f ($Bytes / 1GB)
    }
    if ($Bytes -ge 1MB) {
        return "{0:N2} MB" -f ($Bytes / 1MB)
    }
    if ($Bytes -ge 1KB) {
        return "{0:N2} KB" -f ($Bytes / 1KB)
    }
    return "{0} B" -f $Bytes
}

$variants = @(
    @{ Name = "self-contained"; SelfContained = "true" },
    @{ Name = "framework-dependent"; SelfContained = "false" }
)

foreach ($variant in $variants) {
    Invoke-PublishVariant -Name $variant.Name -SelfContained $variant.SelfContained
}

$publishedDirectories = @(
    (Join-Path $outputRootPath "self-contained"),
    (Join-Path $outputRootPath "framework-dependent")
)

foreach ($directory in $publishedDirectories) {
    $exe = Get-ChildItem -LiteralPath $directory -Filter "*.exe" -File -Recurse | Select-Object -First 1
    if ($null -ne $exe) {
        $hashResult = Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256
        $destExe = Join-Path $outputRootPath $exe.Name
        $destHashFile = "$destExe.sha256"

        # 將成品移動至 output 根目錄
        Move-Item -LiteralPath $exe.FullName -Destination $destExe -Force
        Set-Content -LiteralPath $destHashFile -Value "$($hashResult.Hash)  $($exe.Name)" -Encoding UTF8
    }

    # 移除暫存發布子目錄以維持 output 根目錄簡潔純淨
    if (Test-Path -LiteralPath $directory) {
        Remove-Item -LiteralPath $directory -Recurse -Force
    }
}

$elapsed = (Get-Date) - $publishStartedAt
Write-Host "=== 雙版本發布摘要 ==="
Write-Host ("總耗時：{0}" -f $elapsed.ToString("hh\:mm\:ss\.fff"))
Write-Host "圖示資產：已綁定 $iconPath"
Write-Host "發布目錄：$outputRootPath"

$finalExes = Get-ChildItem -LiteralPath $outputRootPath -Filter "*.exe" -File | Sort-Object Name
foreach ($exe in $finalExes) {
    Write-Host "----------------------------------------"
    Write-Host "成品名稱：$($exe.Name)"
    Write-Host ("檔案大小：{0}" -f (Format-ByteSize $exe.Length))
    $hashFile = "$($exe.FullName).sha256"
    if (Test-Path -LiteralPath $hashFile) {
        $hashContent = Get-Content -LiteralPath $hashFile -Raw
        Write-Host "SHA-256 ：$($hashContent.Trim())"
    }
}


