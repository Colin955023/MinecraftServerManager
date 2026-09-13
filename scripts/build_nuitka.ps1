[CmdletBinding()]
param(
    [switch]$KeepCSource,
    [ValidateSet('disable', 'attach')]
    [string]$ConsoleMode = 'disable'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..'))
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$reportPath = Join-Path $projectRoot 'report\nuitka-compilation-report.xml'
$pendingReportPath = Join-Path $projectRoot "report\nuitka-compilation-report.$PID.pending.xml"

Push-Location $projectRoot
try {
    Write-Host '========================================================'
    Write-Host 'Nuitka Build'
    Write-Host '========================================================'
    Write-Host '[1/3] Synchronizing build environment...'
    & uv sync --group build --locked --no-default-groups
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed. ExitCode=$LASTEXITCODE"
    }

    Write-Host '[2/3] Loading application information...'
    $metadataCode = @'
import json
from src.utils.runtime_utils.app_info import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
)

print(json.dumps({
    'APP_DESCRIPTION': APP_DESCRIPTION,
    'APP_NAME': APP_NAME,
    'APP_VERSION': APP_VERSION,
    'GITHUB_OWNER': GITHUB_OWNER,
    'GITHUB_REPO': GITHUB_REPO,
}))
'@

    $metadataJson = & $venvPython -c $metadataCode
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to load application information. ExitCode=$LASTEXITCODE"
    }
    $appInfo = $metadataJson | ConvertFrom-Json
    $executablePath = Join-Path $projectRoot "dist\$($appInfo.GITHUB_REPO).exe"

    $exportsCode = @'
from src.core import _EXPORTS as core_exports
from src.models import _EXPORTS as model_exports
from src.ui import _EXPORTS as ui_exports
from src.utils import _EXPORTS as utility_exports

modules = sorted(
    {
        f'{package}{module}' if module.startswith('.') else module
        for package, exports in (
            ('src.core', core_exports),
            ('src.models', model_exports),
            ('src.ui', ui_exports),
            ('src.utils', utility_exports),
        )
        for module, _ in exports.values()
    }
)
print(chr(10).join(modules))
'@
    $exportModulesJson = & $venvPython -c $exportsCode
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to load facade export modules. ExitCode=$LASTEXITCODE"
    }
    $exportModules = @($exportModulesJson)

    Write-Host "Checking whether the build output executable is running..."
    $runningOutputProcesses = @(Get-Process -Name "$($appInfo.GITHUB_REPO)" -ErrorAction SilentlyContinue | ForEach-Object {
        $process = $_
        try {
            $processPath = [System.IO.Path]::GetFullPath($process.Path)
            if ([string]::Equals($processPath, $executablePath, [System.StringComparison]::OrdinalIgnoreCase)) {
                $process
            }
        }
        catch {
            throw "無法確認同名程序的執行檔路徑，為避免覆寫執行中的程序而停止建置。PID=$($process.Id)"
        }
    })
    if ($runningOutputProcesses.Count -gt 0) {
        $pids = ($runningOutputProcesses | ForEach-Object Id) -join ', '
        throw "輸出執行檔仍在執行中，請先正常關閉後再建置。PID=$pids"
    }

    $qtUnusedModules = @(
        'PySide6.QtNetwork'
    )

    $pythonUnusedModules = @(
        'asyncio',
        'anyio',
        'httpcore._backends.anyio',
        'httpcore._backends.trio',
        'zstandard',
        'bz2',
        'compression.bz2',
        'gzip',
        'compression.gzip',
        'lzma',
        'compression.lzma',
        'compression.zstd',
        '_zstd',
        'tarfile',
        'httpx._main',
        'concurrent.futures.process',
        'concurrent.futures.interpreter',
        'psutil._pslinux',
        'psutil._psbsd',
        'psutil._psosx',
        'psutil._pssunos',
        'psutil._psaix',
        'defusedxml.cElementTree',
        'defusedxml.minidom',
        'defusedxml.pulldom',
        'defusedxml.sax',
        'defusedxml.expatbuilder',
        'defusedxml.expatreader',
        'defusedxml.xmlrpc',
        '_pyrepl',
        '_aix_support',
        '_android_support',
        '_apple_support',
        '_osx_support',
        'win32evtlog',
        'win32evtlogutil',
        'typing_extensions',
        'ftplib',
        'imaplib',
        'poplib',
        'smtplib',
        'socketserver',
        'graphlib',
        'filecmp',
        'fileinput',
        'sched',
        'colorsys',
        'configparser',
        'html.parser',
        'pprint',
        'pstats',
        'timeit',
        'trace',
        'pyclbr',
        'dis',
        'modulefinder',
        'code',
        'symtable',
        'rlcompleter',
        'cmd',
        'quopri',
        'httpcore._sync.http2',
        'httpcore._sync.socks_proxy',
        '__hello__',
        '__phello__',
        'pickletools',
        'fractions',
        'statistics'
    )

    $numJobs = [Math]::Max(1, [System.Environment]::ProcessorCount - 1)

    Write-Host "[3/3] Building executable with Nuitka (console mode: $ConsoleMode)..."
    $nuitkaArgs = @(
        '-m',
        'nuitka',
        '--mode=onefile',
        '--onefile-tempdir-spec={CACHE_DIR}/Programs/MinecraftServerManager/{VERSION}',
        '--enable-plugin=pyside6',
        '--assume-yes-for-downloads',
        '--output-dir=dist',
        "--output-filename=$($appInfo.GITHUB_REPO).exe",
        '--include-data-files=LICENSE=LICENSE',
        "--report=$pendingReportPath",
        '--python-flag=no_docstrings',
        '--python-flag=no_asserts',
        '--python-flag=isolated',
        '--python-flag=safe_path',
        '--include-windows-runtime-dlls=yes',
        "--windows-console-mode=$ConsoleMode",
        '--noinclude-qt-translations',
        '--noinclude-qt-plugins=tls',
        '--noinclude-qt-plugins=imageformats',
        '--noinclude-unittest-mode=nofollow',
        '--noinclude-pydoc-mode=nofollow',
        '--noinclude-setuptools-mode=nofollow',
        '--noinclude-pytest-mode=nofollow',
        '--noinclude-IPython-mode=nofollow',
        '--windows-icon-from-ico=assets/icon.ico',
        "--file-version=$($appInfo.APP_VERSION)",
        "--product-version=$($appInfo.APP_VERSION)",
        "--file-description=$($appInfo.APP_DESCRIPTION)",
        "--product-name=$($appInfo.APP_NAME)",
        "--company-name=$($appInfo.GITHUB_OWNER)",
        "--copyright=$($appInfo.GITHUB_OWNER)",
        '--msvc=latest',
        '--lto=yes',
        "--jobs=$numJobs"
    )

    foreach ($module in $exportModules) {
        $nuitkaArgs += "--include-module=$module"
    }

    if (-not $KeepCSource) {
        $nuitkaArgs += '--remove-output'
    }

    foreach ($module in $qtUnusedModules) {
        $nuitkaArgs += "--nofollow-import-to=$module"
    }

    foreach ($module in $pythonUnusedModules) {
        $nuitkaArgs += "--nofollow-import-to=$module"
    }

    $nuitkaArgs += 'src/main.py'

    $origLinkEnv = $env:LINK
    $origClcacheHardlink = $env:CLCACHE_HARDLINK
    $origClcacheMaxsize = $env:CLCACHE_MAXSIZE
    $linkFlags = '/cgthreads:8 /OPT:REF /OPT:ICF /DYNAMICBASE /NXCOMPAT /HIGHENTROPYVA'
    $env:LINK = if ($origLinkEnv) { "$origLinkEnv $linkFlags" } else { $linkFlags }
    $env:CLCACHE_HARDLINK = '1'
    if (-not $env:CLCACHE_MAXSIZE) {
        $env:CLCACHE_MAXSIZE = '5368709120'
    }
    try {
        $buildStart = Get-Date
        & $venvPython @nuitkaArgs
        $buildExitCode = $LASTEXITCODE
        $elapsed = (Get-Date) - $buildStart
    }
    finally {
        $env:LINK = $origLinkEnv
        $env:CLCACHE_HARDLINK = $origClcacheHardlink
        $env:CLCACHE_MAXSIZE = $origClcacheMaxsize
    }

    if ($buildExitCode -ne 0) {
        throw "Nuitka build failed. ExitCode=$buildExitCode"
    }

    if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
        throw "找不到建置輸出執行檔：$executablePath"
    }
    if (-not (Test-Path -LiteralPath $pendingReportPath -PathType Leaf)) {
        throw "找不到 Nuitka 建置報告：$pendingReportPath"
    }

    $reportNormalizer = Join-Path $projectRoot 'scripts\normalize_nuitka_report.py'
    & $venvPython $reportNormalizer $pendingReportPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Nuitka 暫存 XML 報告不是有效 XML'
    }

    $reportXml = [System.Xml.XmlDocument]::new()
    $reportXml.XmlResolver = $null
    $reportXml.Load($pendingReportPath)

    $reportRoot = $reportXml.DocumentElement
    if ($null -eq $reportRoot -or $reportRoot.Name -ne 'nuitka-compilation-report') {
        throw 'Nuitka XML 報告根節點無效。'
    }
    $reportCompletion = $reportRoot.GetAttribute('completion')
    $reportMode = $reportRoot.GetAttribute('mode')
    $nuitkaVersion = $reportRoot.GetAttribute('nuitka_version')
    if ($reportCompletion -ne 'yes' -or $reportMode -ne 'onefile') {
        throw "Nuitka XML 報告狀態不符合正式 onefile 建置：completion=$reportCompletion, mode=$reportMode"
    }

    if ($null -eq $reportXml.SelectSingleNode("//data_file[@name='LICENSE']")) {
        throw 'Nuitka 建置產物缺少必要檔案：LICENSE'
    }
    [System.IO.File]::Move($pendingReportPath, $reportPath, $true)

    $minutes = [Math]::Floor($elapsed.TotalMinutes)
    $seconds = $elapsed.Seconds

    $exeSizeBytes = (Get-Item $executablePath).Length
    $exeSizeMB = [Math]::Round($exeSizeBytes / 1MB, 2)

    $sha256 = (Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash
    Write-Host '========================================================'
    Write-Host "建置完成：$($appInfo.APP_NAME) v$($appInfo.APP_VERSION)"
    Write-Host ("執行檔：{0} ({1} MB)" -f $executablePath, $exeSizeMB)
    Write-Host ("耗時：{0} 分 {1} 秒；" -f $minutes, $seconds)
    Write-Host "SHA256：$sha256"
    Write-Host '檢查：onefile、報告與 LICENSE 均符合規則'
    Write-Host '========================================================'
}
finally {
    if (Test-Path -LiteralPath $pendingReportPath -PathType Leaf) {
        Remove-Item -LiteralPath $pendingReportPath -Force
    }
    Pop-Location
}
