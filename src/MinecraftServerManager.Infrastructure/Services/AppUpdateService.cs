using System.Buffers;
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
    private static readonly SearchValues<char> InvalidBatchPathChars = SearchValues.Create("%\"\r\n");

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

        // 下載端已於寫入時以 expectedHash 驗證 SHA-256，失敗即視為整體失敗，不再重複計算雜湊
        var downloadResult = await httpPort.DownloadAsync(
            downloadUri,
            targetFilePath,
            httpProgress,
            expectedHash: expectedSha256,
            expectedHashAlgorithm: "sha256",
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!downloadResult.Success)
        {
            TryDelete(targetFilePath);
            throw new InvalidOperationException($"下載或校驗更新檔案失敗: {downloadResult.Error}");
        }

        progress?.Report((95, "正在執行執行檔格式校驗..."));
        if (!VerifyPeHeader(targetFilePath))
        {
            TryDelete(targetFilePath);
            throw new InvalidDataException("更新檔案不是結構合法的 Windows 執行檔 (PE)，已拒絕更新。");
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

        // 替換前先備份舊版：複製失敗時還原並重新啟動舊版，同時留下失敗記錄，避免程式消失而使用者毫無提示
        string scriptContent = $"""
        @echo off
        chcp 65001 >nul
        set "TARGET={currentExePath}"
        set "SOURCE={verifiedInstallerPath}"
        set "BACKUP=%TARGET%.bak"
        set "FAILLOG=%~dp0update_failed.txt"
        set "PID={pid}"
        set /a WAITED=0

        :wait_loop
        tasklist /fi "pid eq %PID%" /nh 2>nul | findstr /r /c:"[ ]%PID%[ ]" >nul
        if errorlevel 1 goto do_replace
        set /a WAITED+=1
        if %WAITED% gtr 60 goto fail_wait
        timeout /t 1 /nobreak >nul
        goto wait_loop

        :do_replace
        if exist "%BACKUP%" del /f /q "%BACKUP%" >nul 2>&1
        move /y "%TARGET%" "%BACKUP%" >nul
        if errorlevel 1 goto fail_backup
        copy /y "%SOURCE%" "%TARGET%" >nul
        if errorlevel 1 goto fail_copy
        start "" "%TARGET%"
        del /f /q "%BACKUP%" >nul 2>&1
        del /f /q "%SOURCE%" >nul 2>&1
        (goto) 2>nul & del "%~f0" >nul 2>&1
        exit /b 0

        :fail_copy
        move /y "%BACKUP%" "%TARGET%" >nul
        echo 自動更新失敗：無法寫入 %TARGET%，已還原舊版。請確認檔案位置具有寫入權限，或手動下載更新。> "%FAILLOG%"
        start "" "%TARGET%"
        exit /b 1

        :fail_backup
        echo 自動更新失敗：無法備份舊版 %TARGET%。請確認檔案位置具有寫入權限，或手動下載更新。> "%FAILLOG%"
        start "" "%TARGET%"
        exit /b 1

        :fail_wait
        echo 自動更新失敗：等待舊版程式結束逾時。請手動下載更新。> "%FAILLOG%"
        exit /b 2
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
        if (path.AsSpan().IndexOfAny(InvalidBatchPathChars) >= 0)
        {
            throw new InvalidOperationException("更新路徑含有批次指令無法安全處理的字元，已拒絕自動更新。");
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            Logger.Warning("無法刪除未通過驗證的更新檔案 {Path}: {Message}", path, exception.Message);
        }
    }

    /// <summary>
    /// 檢查 DOS 標頭 'MZ' 與 e_lfanew 所指之 'PE\0\0' 簽章；僅為結構健全性檢查，完整性仍由 SHA-256 保證
    /// </summary>
    private static bool VerifyPeHeader(string filePath)
    {
        try
        {
            using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (fs.Length < 64)
            {
                return false;
            }

            Span<byte> dos = stackalloc byte[64];
            if (fs.Read(dos) != dos.Length || dos[0] != 0x4D || dos[1] != 0x5A)
            {
                return false;
            }

            int peOffset = BitConverter.ToInt32(dos[0x3C..0x40]);
            long peOffsetLimit = fs.Length - 4;
            if (peOffset < 64 || peOffset > peOffsetLimit)
            {
                return false;
            }

            fs.Seek(peOffset, SeekOrigin.Begin);
            Span<byte> signature = stackalloc byte[4];
            return fs.Read(signature) == 4 && signature[0] == 0x50 && signature[1] == 0x45 && signature[2] == 0 && signature[3] == 0;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }
}
