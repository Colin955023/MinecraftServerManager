[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..'))
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Push-Location $projectRoot
try {
    Write-Host '========================================================'
    Write-Host 'Nuitka Build'
    Write-Host '========================================================'

    Write-Host '[1/4] Cleaning build environment...'
    foreach ($path in @('.venv', 'dist')) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
    Write-Host '[2/4] Synchronizing build environment...'
    & uv sync --group build --locked
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed. ExitCode=$LASTEXITCODE"
    }

    Write-Host '[3/4] Loading application information...'
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
    "APP_DESCRIPTION": APP_DESCRIPTION,
    "APP_NAME": APP_NAME,
    "APP_VERSION": APP_VERSION,
    "GITHUB_OWNER": GITHUB_OWNER,
    "GITHUB_REPO": GITHUB_REPO,
}))
'@

    $metadataJson = & $venvPython -c $metadataCode
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to load application information. ExitCode=$LASTEXITCODE"
    }
    $appInfo = $metadataJson | ConvertFrom-Json

    $qtUnusedModules = @(
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtSql',
        'PySide6.QtNetwork',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQuick3D',
        'PySide6.Qt3DCore',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtLocation',
        'PySide6.QtSerialPort',
        'PySide6.QtSerialBus',
        'PySide6.QtSensors',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtStateMachine',
        'PySide6.QtTextToSpeech',
        'PySide6.QtSpatialAudio',
        'PySide6.QtHelp',
        'PySide6.QtDesigner',
        'PySide6.QtUiTools',
        'PySide6.QtTest',
        'PySide6.QtWebSockets',
        'PySide6.QtWebChannel',
        'PySide6.iconengines'
    )

    $qtPluginExcludeFamilies = @(
        'iconengines',
        'imageformats',
        'printsupport',
        'tls',
        'generic',
        'platforminputcontexts'
    )

    $numJobs = [Math]::Max(1, [System.Environment]::ProcessorCount - 1)

    Write-Host '[4/4] Building executable with Nuitka...'
    $nuitkaArgs = @(
        '-m',
        'nuitka',
        '--onefile',
        '--enable-plugin=pyside6',
        '--assume-yes-for-downloads',
        '--remove-output',
        '--output-dir=dist',
        "--output-filename=$($appInfo.GITHUB_REPO).exe",
        '--include-package=src',
        '--include-data-files=LICENSE=LICENSE',
        '--include-data-dir=assets=assets',
        '--python-flag=no_docstrings',
        '--windows-console-mode=attach',
        '--noinclude-qt-translations',
        '--noinclude-setuptools-mode=nofollow',
        '--noinclude-pytest-mode=nofollow',
        '--noinclude-unittest-mode=nofollow',
        '--noinclude-pydoc-mode=nofollow',
        '--noinclude-IPython-mode=nofollow',
        '--include-qt-plugins=platforms',
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

    foreach ($module in $qtUnusedModules) {
        $nuitkaArgs += "--nofollow-import-to=$module"
    }

    foreach ($family in $qtPluginExcludeFamilies) {
        $nuitkaArgs += "--noinclude-qt-plugins=$family"
    }

    $nuitkaArgs += 'src/main.py'

    $buildStart = Get-Date
    & $venvPython @nuitkaArgs
    $buildExitCode = $LASTEXITCODE
    $elapsed = (Get-Date) - $buildStart

    if ($buildExitCode -ne 0) {
        throw "Nuitka build failed. ExitCode=$buildExitCode"
    }

    $minutes = [Math]::Floor($elapsed.TotalMinutes)
    $seconds = $elapsed.Seconds
    $executablePath = Join-Path $projectRoot "dist\$($appInfo.GITHUB_REPO).exe"

    Write-Host '========================================================'
    Write-Host 'Build completed successfully.'
    Write-Host "Application: $($appInfo.APP_NAME)"
    Write-Host "Version: $($appInfo.APP_VERSION)"
    Write-Host "Executable: $executablePath"
    Write-Host ("Build time: {0} min {1} sec" -f $minutes, $seconds)
    Write-Host '========================================================'
}
finally {
    Pop-Location
}