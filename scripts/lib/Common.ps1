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

function Test-Utf8Bom
{
    <#
    .SYNOPSIS
        檢查檔案是否以 UTF-8 with BOM（0xEF 0xBB 0xBF）開頭。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $buffer = [byte[]]::new(3)
    $fs = [System.IO.File]::OpenRead($Path)
    try { $read = $fs.Read($buffer, 0, 3) } finally { $fs.Dispose() }
    return ($read -eq 3 -and $buffer[0] -eq 0xEF -and $buffer[1] -eq 0xBB -and $buffer[2] -eq 0xBF)
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

    try
    {
        [Console]::InputEncoding = $Utf8NoBom
        [Console]::OutputEncoding = $Utf8NoBom
    }
    catch [System.IO.IOException]
    {
        # 無主控台（如輸出重新導向的背景程序）時無法設定，不影響後續執行
        Write-Verbose "略過主控台編碼設定：$($_.Exception.Message)"
    }
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

function Get-ChangelogSection
{
    <#
    .SYNOPSIS
        取得 CHANGELOG 中指定版本章節的內文；找不到或內文空白回傳 $null。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Changelog,

        [Parameter(Mandatory = $true)]
        [string]$Version
    )

    $escaped = [regex]::Escape($Version)
    # 版本號後須為非版本字元，避免 2.2.1 誤配 2.2.10 或 2.3.0 誤配 2.3.0-beta
    $pattern = "(?ms)^##\s+\[?v?$escaped(?![\w.\-])\]?[^\r\n]*\r?\n(.*?)(?=^##\s+|\Z)"
    if ($Changelog -notmatch $pattern)
    {
        return $null
    }

    $body = $Matches[1].Trim()
    return [string]::IsNullOrWhiteSpace($body) ? $null : $body
}

function Get-Sha256Hex
{
    <#
    .SYNOPSIS
        計算指定檔案的 SHA-256 十六進位雜湊字串（預設小寫）。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,

        [switch]$UpperCase
    )

    $fullPath = [System.IO.Path]::GetFullPath($LiteralPath)
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf))
    {
        throw "找不到要計算雜湊的檔案：$fullPath"
    }

    $hash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
    if ($UpperCase) { return $hash }
    return $hash.ToLowerInvariant()
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
    $hash = Get-Sha256Hex -LiteralPath $fullPath
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
            # 等待行程樹結束釋放檔案鎖，避免清理暫存目錄失敗
            $null = $proc.WaitForExit(5000)
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

        [ValidateRange(1, 10)]
        [int]$MaxAttempts = 3
    )

    $lastError = $null
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
            $lastError = "結束代碼 $LASTEXITCODE"
        }
        catch
        {
            $lastError = $_.Exception.Message
        }
        Write-Warning "${Description}失敗（第 $attempt 次）：$lastError"

        if ($attempt -lt $MaxAttempts)
        {
            Start-Sleep -Seconds ($attempt * 2)
        }
    }

    throw "${Description}失敗（已嘗試 $MaxAttempts 次）：$lastError"
}

function Sync-RemoteTags
{
    <#
    .SYNOPSIS
        強制同步遠端標籤，失敗即擲出例外。
    #>
    [CmdletBinding()]
    param()

    # 輸出導向主控台，避免混入呼叫端的回傳值
    git fetch --tags --force | Out-Host
    if ($LASTEXITCODE -ne 0)
    {
        throw "取得遠端標籤失敗（結束代碼 $LASTEXITCODE）"
    }
}

function Get-HeadCommit
{
    <#
    .SYNOPSIS
        取得目前 HEAD 的 commit SHA，失敗即擲出例外。
    #>
    [CmdletBinding()]
    param()

    $commit = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit))
    {
        throw "無法取得目前 HEAD commit"
    }
    return ([string]$commit).Trim()
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

function Test-ReleaseTagAtHead
{
    <#
    .SYNOPSIS
        同步遠端標籤後檢查發行標籤：已指向 HEAD 回傳 $true、尚未建立回傳 $false、指向其他 commit 擲出例外。
        正常結果一律將 $LASTEXITCODE 設為 0，避免 CI 步驟結尾沿用原生指令的結束代碼而失敗。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )

    $null = Sync-RemoteTags
    $headCommit = Get-HeadCommit
    $tagCommit = Get-TagCommit -Tag $Tag
    if ($null -ne $tagCommit -and $tagCommit -ne $headCommit)
    {
        throw "Tag $Tag 已存在且指向不同 commit [$tagCommit]，請更新版本號"
    }

    $global:LASTEXITCODE = 0
    return ($null -ne $tagCommit)
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

    $content = (Get-Content -LiteralPath $ShaPath -Raw -Encoding UTF8).Trim()
    if ($content -notmatch '^([0-9a-fA-F]{64})\s+[\*]?(.*)$')
    {
        throw "無法解析雜湊檔：$ShaPath"
    }

    $expected = $Matches[1]
    $targetName = $Matches[2].Trim()
    # 僅接受同目錄的純檔名，阻擋路徑穿越
    if ([string]::IsNullOrEmpty($targetName) -or $targetName -match '[\\/:]' -or $targetName -in '.', '..')
    {
        throw "雜湊檔的目標檔名不合法：$targetName"
    }
    $target = Join-Path ([System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($ShaPath))) $targetName
    if (-not (Test-Path -LiteralPath $target -PathType Leaf))
    {
        throw "雜湊檔指定的檔案不存在：$targetName"
    }

    $actual = Get-Sha256Hex -LiteralPath $target
    if ($actual -ne $expected.ToLowerInvariant())
    {
        throw "雜湊不符：$targetName 預期 $expected，實際 $actual"
    }
    Write-Host " [SHA256 驗證通過] $targetName"
}
