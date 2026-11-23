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
$notes = Get-ChangelogSection -Changelog $changelog -Version $version
if ($null -eq $notes)
{
    throw "CHANGELOG.md 中找不到版本 $version 對應之章節或內容空白"
}

$lfNotes = ($notes.Trim() -replace "\r\n", "`n") + "`n"
[System.IO.File]::WriteAllText($resolvedOutput, $lfNotes, $Utf8NoBom)
Write-Host "成功提取發行說明至：$resolvedOutput"

if ($env:GITHUB_OUTPUT)
{
    if ($version -match '[\r\n]')
    {
        throw "版本字串含換行字元，拒絕寫入 GITHUB_OUTPUT"
    }
    "tag_name=$tag" | Out-File -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Append
    "version=$version" | Out-File -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}
