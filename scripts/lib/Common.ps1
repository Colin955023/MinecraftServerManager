<#
.SYNOPSIS
    Minecraft Server Manager 共用 PowerShell 函式庫
#>

function Get-ProjectVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [string]$RepoRoot
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
        $RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    }

    $propsPath = Join-Path $RepoRoot "Directory.Build.props"
    if (-not (Test-Path -LiteralPath $propsPath)) {
        throw "找不到版本定義檔案 Directory.Build.props ($propsPath)"
    }

    [xml]$propsXml = Get-Content -Raw -Encoding UTF8 $propsPath
    $versionNode = $propsXml.SelectSingleNode("//Version")
    if ($null -eq $versionNode -or [string]::IsNullOrWhiteSpace($versionNode.InnerText)) {
        throw "無法從 Directory.Build.props 解析 Version 節點"
    }

    return $versionNode.InnerText.Trim()
}
