<#
.SYNOPSIS
    Minecraft Server Manager 共用 PowerShell 函式庫
#>

function Initialize-ScriptEnvironment {
    <#
    .SYNOPSIS
        統一設定 UTF-8 主控台編碼、停用 MSBuild 節點重用，並將錯誤偏好設為 Stop（作用於呼叫端腳本範圍）。
    #>
    [CmdletBinding()]
    param()

    $env:DOTNET_CLI_FORCE_UTF8_ENCODING = "1"
    $env:MSBUILDDISABLENODEREUSE = "1"

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    Set-Variable -Name OutputEncoding -Value $utf8NoBom -Scope 1
    Set-Variable -Name ErrorActionPreference -Value "Stop" -Scope 1
}

function Get-ProjectVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [string]$RepoRoot
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
        $RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
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

function Write-Sha256File {
    <#
    .SYNOPSIS
        產生 sha256sum 相容格式（小寫雜湊、兩個空白、檔名、LF 結尾、UTF-8 無 BOM）的 <檔名>.sha256。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath
    )

    $fullPath = [System.IO.Path]::GetFullPath($LiteralPath)
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "找不到要計算雜湊的檔案：$fullPath"
    }

    $hash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaPath = "$fullPath.sha256"
    [System.IO.File]::WriteAllText(
        $shaPath,
        "$hash  $([System.IO.Path]::GetFileName($fullPath))`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    return $shaPath
}

function Get-ReleaseAssetNames {
    <#
    .SYNOPSIS
        GitHub Release 必要資產清單（發布與發布後驗證共用的單一事實來源）。
    #>
    [CmdletBinding()]
    param()

    return @(
        'MinecraftServerManager.exe',
        'MinecraftServerManager.exe.sha256',
        'MinecraftServerManager.exe.intoto.jsonl',
        'MinecraftServerManager.spdx.json',
        'MinecraftServerManager.spdx.json.sha256'
    )
}
