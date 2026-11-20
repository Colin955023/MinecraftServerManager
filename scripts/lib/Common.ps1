#Requires -Version 7.1
<#
.SYNOPSIS
    Minecraft Server Manager 共用 PowerShell 函式庫
#>
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# 共用 UTF-8 無 BOM 編碼
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Get-RepoRoot
{
    <#
    .SYNOPSIS
        取得儲存庫根目錄完整路徑。
    #>
    [CmdletBinding()]
    param()

    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}

function Initialize-ScriptEnvironment
{
    <#
    .SYNOPSIS
        統一設定 UTF-8 主控台編碼並停用 MSBuild 節點重用。
    #>
    [CmdletBinding()]
    param()

    $env:DOTNET_CLI_FORCE_UTF8_ENCODING = "1"
    $env:MSBUILDDISABLENODEREUSE = "1"

    [Console]::InputEncoding = $Utf8NoBom
    [Console]::OutputEncoding = $Utf8NoBom
    Set-Variable -Name OutputEncoding -Value $Utf8NoBom -Scope 1
}

function Test-CiEnvironment
{
    <#
    .SYNOPSIS
        是否於 CI（含 GitHub Actions）執行。
    #>
    [CmdletBinding()]
    param()

    return ($env:CI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true')
}

function Get-ProjectVersion
{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [string]$RepoRoot
    )

    if ([string]::IsNullOrWhiteSpace($RepoRoot))
    {
        $RepoRoot = Get-RepoRoot
    }

    $propsPath = Join-Path $RepoRoot "Directory.Build.props"
    if (-not (Test-Path -LiteralPath $propsPath))
    {
        throw "找不到版本定義檔案 Directory.Build.props ($propsPath)"
    }

    [xml]$propsXml = Get-Content -LiteralPath $propsPath -Raw -Encoding UTF8
    $versionNode = $propsXml.SelectSingleNode("//Version")
    if ($null -eq $versionNode -or [string]::IsNullOrWhiteSpace($versionNode.InnerText))
    {
        throw "無法從 Directory.Build.props 解析 Version 節點"
    }

    return $versionNode.InnerText.Trim()
}

function Write-Sha256File
{
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
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf))
    {
        throw "找不到要計算雜湊的檔案：$fullPath"
    }

    $hash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaPath = "$fullPath.sha256"
    [System.IO.File]::WriteAllText(
        $shaPath,
        "$hash  $([System.IO.Path]::GetFileName($fullPath))`n",
        $Utf8NoBom
    )
    return $shaPath
}

function Invoke-SmokeTest
{
    <#
    .SYNOPSIS
        以暫存的 MSM_USER_DATA_DIR 執行主程式 --smoke-test，逾時即終止並於失敗時擲出例外；結束後清理暫存。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExePath,

        [int]$TimeoutSeconds = 30
    )

    $fullExePath = [System.IO.Path]::GetFullPath($ExePath)
    if (-not (Test-Path -LiteralPath $fullExePath -PathType Leaf))
    {
        throw "找不到煙霧測試的執行檔：$fullExePath"
    }

    $smokeDataDir = Join-Path ([System.IO.Path]::GetTempPath()) ("msm_smoke_" + [Guid]::NewGuid().ToString("N"))
    $null = [System.IO.Directory]::CreateDirectory($smokeDataDir)
    # 預寫設定：伺服器目錄指向暫存、停用自動更新（避免連網）
    $settingsJson = [ordered]@{
        servers_root        = Join-Path $smokeDataDir "servers"
        auto_update_enabled = $false
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $smokeDataDir "user_settings.json"), $settingsJson, $Utf8NoBom)

    $psi = [System.Diagnostics.ProcessStartInfo]::new($fullExePath, "--smoke-test")
    $psi.EnvironmentVariables["MSM_USER_DATA_DIR"] = $smokeDataDir
    $psi.UseShellExecute = $false
    $proc = $null
    try
    {
        $proc = [System.Diagnostics.Process]::Start($psi)
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000))
        {
            $proc.Kill($true)
            throw "煙霧測試逾時（$TimeoutSeconds 秒）"
        }
        if ($proc.ExitCode -ne 0)
        {
            throw "煙霧測試失敗，結束代碼：$($proc.ExitCode)"
        }
    }
    finally
    {
        ${proc}?.Dispose()
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

function Get-ReleaseAssetNames
{
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

function Invoke-WithRetry
{
    <#
    .SYNOPSIS
        執行動作，擲出例外或原生指令結束代碼非 0 時重試（等待秒數遞增），全部失敗則擲出例外。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,

        [Parameter(Mandatory = $true)]
        [string]$Description,

        [int]$MaxAttempts = 3
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++)
    {
        $global:LASTEXITCODE = 0
        try
        {
            & $Action
            if ($LASTEXITCODE -eq 0)
            {
                return
            }
            Write-Warning "${Description}失敗（第 $attempt 次，結束代碼 $LASTEXITCODE）"
        }
        catch
        {
            Write-Warning "${Description}失敗（第 $attempt 次）：$($_.Exception.Message)"
        }

        if ($attempt -lt $MaxAttempts)
        {
            Start-Sleep -Seconds ($attempt * 2)
        }
    }

    throw "${Description}失敗"
}

function Get-TagCommit
{
    <#
    .SYNOPSIS
        取得 tag 指向的 commit SHA（含 annotated tag）；tag 不存在則回傳 $null。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )

    $commit = git rev-parse -q --verify "refs/tags/$Tag^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit))
    {
        # tag 不存在屬預期結果；清除退出碼，避免 CI 步驟結尾沿用 git 的非 0 值而失敗
        $global:LASTEXITCODE = 0
        return $null
    }
    return ([string]$commit).Trim()
}

function Assert-ReleaseAssets
{
    <#
    .SYNOPSIS
        確認目錄內含所有必要的 Release 資產，缺少即擲出例外。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Directory
    )

    $actualNames = @(Get-ChildItem -LiteralPath $Directory -File | Select-Object -ExpandProperty Name)
    $missing = @(Get-ReleaseAssetNames | Where-Object { $_ -notin $actualNames })
    if ($missing.Count -gt 0)
    {
        throw "缺少必要的 Release 資產：$($missing -join ', ')"
    }
}

function Assert-Sha256File
{
    <#
    .SYNOPSIS
        依 sha256sum 格式的雜湊檔驗證同目錄的目標檔案，不符即擲出例外。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ShaPath
    )

    $content = (Get-Content -LiteralPath $ShaPath -Raw).Trim()
    if ($content -notmatch '^([0-9a-fA-F]{64})\s+[\*]?(.*)$')
    {
        throw "無法解析雜湊檔：$ShaPath"
    }

    $expected = $Matches[1]
    $targetName = $Matches[2].Trim()
    $target = Join-Path ([System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($ShaPath))) $targetName
    if (-not (Test-Path -LiteralPath $target -PathType Leaf))
    {
        throw "雜湊檔指定的檔案不存在：$targetName"
    }

    $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    if ($actual -ne $expected)
    {
        throw "雜湊不符：$targetName 預期 $expected，實際 $actual"
    }
    Write-Host " [SHA256 驗證通過] $targetName"
}
