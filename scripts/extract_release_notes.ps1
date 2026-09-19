[CmdletBinding()]
param(
    [string]$ChangelogPath = "CHANGELOG.md",
    [string]$OutputPath = "release_notes.md",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$appInfoPath = Join-Path $repoRoot "src\MinecraftServerManager.Core\AppInfo.cs"
$content = Get-Content -Raw -Encoding UTF8 $appInfoPath
if ($content -match 'public\s+const\s+string\s+Version\s*=\s*"([^"]+)";') {
    $version = $matches[1]
} else {
    throw "無法從 AppInfo.cs 解析 Version"
}

$tag = "v$version"
Write-Host "解析到版本：$version，發行標籤：$tag"

$resolvedChangelog = if ([System.IO.Path]::IsPathRooted($ChangelogPath)) { $ChangelogPath } else { Join-Path $repoRoot $ChangelogPath }
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $repoRoot $OutputPath }

if (Test-Path $resolvedChangelog) {
    $changelog = Get-Content -Raw -Encoding UTF8 $resolvedChangelog
    $escaped = [regex]::Escape($version)
    $pattern = "(?ms)^##\s+\[?(?:v?$escaped)\]?.*?\r?\n(.*?)(?=^##\s+|\Z)"
    if ($changelog -match $pattern) {
        $notes = $matches[1].Trim()
        Set-Content -LiteralPath $resolvedOutput -Value $notes -Encoding UTF8
        Write-Host "成功提取發行說明至：$resolvedOutput"
    } else {
        if ($Strict) {
            throw "CHANGELOG.md 中找不到版本 $version 對應之章節"
        }
        Set-Content -LiteralPath $resolvedOutput -Value "Minecraft Server Manager $tag 發行說明" -Encoding UTF8
        Write-Warning "CHANGELOG.md 未找到 $version，已產出預設發行說明"
    }
} else {
    if ($Strict) {
        throw "找不到 CHANGELOG 檔案：$resolvedChangelog"
    }
    Set-Content -LiteralPath $resolvedOutput -Value "Minecraft Server Manager $tag 發行說明" -Encoding UTF8
}

if ($env:GITHUB_OUTPUT) {
    "tag_name=$tag" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
    "version=$version" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}
