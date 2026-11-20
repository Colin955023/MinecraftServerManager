#Requires -Version 7.1
[CmdletBinding()]
param(
    [string]$ChangelogPath = "CHANGELOG.md",
    [string]$OutputPath = "release_notes.md"
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$commonScript = Join-Path $PSScriptRoot "lib\Common.ps1"
if (-not (Test-Path -LiteralPath $commonScript))
{
    throw "找不到共用函式庫：$commonScript"
}
. $commonScript
Initialize-ScriptEnvironment

$repoRoot = Get-RepoRoot
$version = Get-ProjectVersion -RepoRoot $repoRoot

$tag = "v$version"
Write-Host "解析到版本：$version，發行標籤：$tag"

$resolvedChangelog = if ([System.IO.Path]::IsPathRooted($ChangelogPath)) { $ChangelogPath } else { Join-Path $repoRoot $ChangelogPath }
$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $repoRoot $OutputPath }

if (-not (Test-Path -LiteralPath $resolvedChangelog))
{
    throw "找不到 CHANGELOG 檔案：$resolvedChangelog"
}

$changelog = Get-Content -LiteralPath $resolvedChangelog -Raw -Encoding UTF8
$escaped = [regex]::Escape($version)
# 版本號後須為非版本字元，避免 2.2.1 誤配 2.2.10 或 2.3.0 誤配 2.3.0-beta
$pattern = "(?ms)^##\s+\[?v?$escaped(?![\w.\-])\]?[^\r\n]*\r?\n(.*?)(?=^##\s+|\Z)"
if ($changelog -notmatch $pattern)
{
    throw "CHANGELOG.md 中找不到版本 $version 對應之章節"
}

Set-Content -LiteralPath $resolvedOutput -Value $matches[1].Trim() -Encoding UTF8
Write-Host "成功提取發行說明至：$resolvedOutput"

if ($env:GITHUB_OUTPUT)
{
    "tag_name=$tag" | Out-File -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Append
    "version=$version" | Out-File -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}
