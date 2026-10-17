using System.Diagnostics;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>
/// 應用程式自動更新下載、安全性驗證與重啟安裝服務實作
/// </summary>
public sealed partial class AppUpdateService(
    IHttpPort httpPort,
    string? updatesDirectory = null) : IAppUpdateService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("AppUpdateService");

    [GeneratedRegex(@"\b[a-fA-F0-9]{64}\b")]
    private static partial Regex Sha256Regex();

    public async Task<string> DownloadAndVerifyUpdateAsync(
        UpdateCheckResult update,
        IProgress<(int Percentage, string StatusMessage)>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(update);

        if (string.IsNullOrWhiteSpace(update.DownloadUrl) || !Uri.TryCreate(update.DownloadUrl, UriKind.Absolute, out var downloadUri))
        {
            throw new InvalidOperationException("更新資訊中缺少有效的下載位址。");
        }

        if (string.IsNullOrWhiteSpace(update.Sha256ChecksumUrl)
            || !Uri.TryCreate(update.Sha256ChecksumUrl, UriKind.Absolute, out var checksumUri))
        {
            throw new InvalidDataException("更新資訊缺少有效的 SHA-256 校驗檔網址，已拒絕自動更新。");
        }

        progress?.Report((5, "正在取得安全驗證資訊 (SHA-256)..."));
        string? checksumText = await httpPort.GetTextAsync(checksumUri, cancellationToken).ConfigureAwait(false);
        Match match = string.IsNullOrWhiteSpace(checksumText) ? Match.Empty : Sha256Regex().Match(checksumText);
        if (!match.Success)
        {
            throw new InvalidDataException("無法取得有效的 SHA-256 校驗碼，已拒絕自動更新。");
        }

        string expectedSha256 = match.Value.ToLowerInvariant();
        Logger.Information("成功取得預期 SHA-256 校驗碼: {Hash}", expectedSha256);

        string targetDir = updatesDirectory ?? Path.Combine(RuntimePaths.GetUserDataDir(), "updates");
        Directory.CreateDirectory(targetDir);

        string rawFileName = Path.GetFileName(downloadUri.LocalPath);
        if (string.IsNullOrWhiteSpace(rawFileName) || !rawFileName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
        {
            rawFileName = $"MinecraftServerManager-{update.LatestVersion}.exe";
        }

        string targetFilePath = Path.Combine(targetDir, rawFileName);

        // 若本地已存在且符合 SHA-256 與 PE 結構則直接複用
        if (File.Exists(targetFilePath))
        {
            string existingHash = HashCalculator.Shared.ComputeFileHash(targetFilePath, "sha256");
            if (string.Equals(existingHash, expectedSha256, StringComparison.OrdinalIgnoreCase) && VerifyPeHeader(targetFilePath))
            {
                Logger.Information("更新檔案已存在且通過 SHA-256 校驗: {Path}", targetFilePath);
                progress?.Report((100, "更新檔案已備妥且驗證通過。"));
                return targetFilePath;
            }
        }

        progress?.Report((10, "正在下載主程式更新檔..."));
        var httpProgress = progress is null ? null : new Progress<HttpProgress>(p =>
        {
            int percent = p.TotalBytes > 0 ? (int)Math.Clamp((p.BytesDownloaded * 80 / p.TotalBytes) + 10, 10, 90) : 50;
            string msg = p.TotalBytes > 0
                ? $"正在下載主程式更新檔 ({UnitFormatter.FormatBytes(p.BytesDownloaded)} / {UnitFormatter.FormatBytes(p.TotalBytes)})..."
                : $"正在下載主程式更新檔 ({UnitFormatter.FormatBytes(p.BytesDownloaded)})...";
            progress.Report((percent, msg));
        });

        var downloadResult = await httpPort.DownloadAsync(
            downloadUri,
            targetFilePath,
            httpProgress,
            expectedHash: expectedSha256,
            expectedHashAlgorithm: "sha256",
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!downloadResult.Success)
        {
            if (File.Exists(targetFilePath))
            {
                try
                {
                    File.Delete(targetFilePath);
                }
                catch
                {
                }
            }

            throw new InvalidOperationException($"下載或校驗更新檔案失敗: {downloadResult.Error}");
        }

        progress?.Report((95, "正在執行執行檔安全性與格式校驗..."));
        if (!VerifyPeHeader(targetFilePath))
        {
            if (File.Exists(targetFilePath))
            {
                try
                {
                    File.Delete(targetFilePath);
                }
                catch
                {
                }
            }

            throw new InvalidDataException("更新檔案未具備合法的 Windows 執行檔 (PE) 標頭，為保護系統安全已拒絕更新。");
        }

        string finalHash = HashCalculator.Shared.ComputeFileHash(targetFilePath, "sha256");
        if (!string.Equals(finalHash, expectedSha256, StringComparison.OrdinalIgnoreCase))
        {
            if (File.Exists(targetFilePath))
            {
                try
                {
                    File.Delete(targetFilePath);
                }
                catch
                {
                }
            }

            throw new InvalidDataException($"更新檔案 SHA-256 校驗失敗！預期: {expectedSha256}，實際: {finalHash}。");
        }

        progress?.Report((100, "更新檔案驗證通過！"));
        Logger.Information("主程式更新檔下載並通過所有安全驗證: {Path}", targetFilePath);
        return targetFilePath;
    }

    public void ApplyUpdateAndRestart(string verifiedInstallerPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(verifiedInstallerPath);

        if (!File.Exists(verifiedInstallerPath))
        {
            throw new FileNotFoundException("找不到已驗證的更新檔案。", verifiedInstallerPath);
        }

        string? currentExePath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(currentExePath) || !File.Exists(currentExePath))
        {
            throw new InvalidOperationException("無法判斷目前應用程式的執行檔路徑，無法套用自動更新。");
        }

        int pid = Environment.ProcessId;
        string dir = Path.GetDirectoryName(verifiedInstallerPath) ?? Path.GetTempPath();
        string scriptPath = Path.Combine(dir, "apply_update.cmd");
        ValidateBatchPath(currentExePath);
        ValidateBatchPath(verifiedInstallerPath);

        string scriptContent = $"""
        @echo off
        chcp 65001 >nul
        set "TARGET={currentExePath}"
        set "SOURCE={verifiedInstallerPath}"
        set "PID={pid}"

        :wait_loop
        tasklist /fi "pid eq %PID%" 2>nul | findstr /i "%PID%" >nul
        if not errorlevel 1 (
            timeout /t 1 /nobreak >nul
            goto wait_loop
        )

        copy /y "%SOURCE%" "%TARGET%" >nul
        if errorlevel 1 (
            exit /b 1
        )

        start "" "%TARGET%"
        del "%SOURCE%" >nul 2>&1
        (goto) 2>nul & del "%~f0" >nul 2>&1
        """;

        File.WriteAllText(scriptPath, scriptContent, new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

        var startInfo = new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = $"/c \"\"{scriptPath}\"\"",
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory,
        };

        System.Diagnostics.Process.Start(startInfo);
        Logger.Information("已啟動更新替換腳本，準備重啟應用程式: PID={Pid}, Target={Target}", pid, currentExePath);
    }

    private static void ValidateBatchPath(string path)
    {
        if (path.IndexOfAny(['%', '"', '\r', '\n']) >= 0)
        {
            throw new InvalidOperationException("更新路徑含有批次指令無法安全處理的字元，已拒絕自動更新。");
        }
    }

    private static bool VerifyPeHeader(string filePath)
    {
        try
        {
            using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (fs.Length < 64)
            {
                return false;
            }

            Span<byte> buffer = stackalloc byte[2];
            if (fs.Read(buffer) != 2)
            {
                return false;
            }

            return buffer[0] == 0x4D && buffer[1] == 0x5A;
        }
        catch
        {
            return false;
        }
    }
}
