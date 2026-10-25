using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>
/// 應用程式自動更新下載、安全性驗證與重啟安裝服務實作
/// </summary>
public sealed partial class AppUpdateService : IAppUpdateService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("AppUpdateService");

    [GeneratedRegex(@"\b[a-fA-F0-9]{64}\b")]
    private static partial Regex Sha256Regex();

    private readonly IHttpPort _httpPort;
    private readonly string? _updatesDirectory;
    private readonly IProcessRunner? _processRunner;

    public AppUpdateService(
        IHttpPort httpPort,
        string? updatesDirectory = null,
        IProcessRunner? processRunner = null)
    {
        _httpPort = httpPort ?? throw new ArgumentNullException(nameof(httpPort));
        _updatesDirectory = updatesDirectory;
        _processRunner = processRunner;

        TryCleanupPreviousUpdateBackup();
    }

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
        string? checksumText = await _httpPort.GetTextAsync(checksumUri, cancellationToken).ConfigureAwait(false);
        Match match = string.IsNullOrWhiteSpace(checksumText) ? Match.Empty : Sha256Regex().Match(checksumText);
        if (!match.Success)
        {
            throw new InvalidDataException("無法取得有效的 SHA-256 校驗碼，已拒絕自動更新。");
        }

        string expectedSha256 = match.Value.ToLowerInvariant();
        Logger.Information("成功取得預期 SHA-256 校驗碼: {Hash}", expectedSha256);

        string targetDir = _updatesDirectory ?? Path.Combine(RuntimePaths.GetUserDataDir(), "updates");
        SafeFileSystem.CreateDirectory(targetDir);

        string rawFileName = Path.GetFileName(downloadUri.LocalPath);
        if (string.IsNullOrWhiteSpace(rawFileName) || !rawFileName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
        {
            rawFileName = $"MinecraftServerManager-{update.LatestVersion}.exe";
        }

        string targetFilePath = Path.Combine(targetDir, rawFileName);

        // 若本地已存在且符合 SHA-256 與 PE 結構則直接複用
        if (SafeFileSystem.FileExists(targetFilePath))
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
        var downloadResult = await _httpPort.DownloadAsync(
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

        if (!SafeFileSystem.FileExists(verifiedInstallerPath))
        {
            throw new FileNotFoundException("找不到已驗證的更新檔案。", verifiedInstallerPath);
        }

        string? currentExePath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(currentExePath) || !SafeFileSystem.FileExists(currentExePath))
        {
            throw new InvalidOperationException("無法判斷目前應用程式的執行檔路徑，無法套用自動更新。");
        }

        if (_processRunner is null)
        {
            throw new InvalidOperationException("未設定共用行程管理服務，無法啟動新版應用程式。");
        }

        string oldExePath = currentExePath + ".old";

        try
        {
            if (SafeFileSystem.FileExists(oldExePath))
            {
                SafeFileSystem.DeleteFile(oldExePath);
            }

            // Windows 支援將執行中的檔案重新命名（原檔移至 .old）
            SafeFileSystem.MovePath(currentExePath, oldExePath, overwrite: true);

            try
            {
                // 將已驗證的更新檔複製為正式執行檔
                SafeFileSystem.CopyFile(verifiedInstallerPath, currentExePath, overwrite: true);
            }
            catch (Exception copyEx)
            {
                // 若複製失敗，立即復原舊版執行檔
                try
                {
                    if (SafeFileSystem.FileExists(oldExePath) && !SafeFileSystem.FileExists(currentExePath))
                    {
                        SafeFileSystem.MovePath(oldExePath, currentExePath, overwrite: true);
                    }
                }
                catch (Exception rollbackEx)
                {
                    Logger.Error("復原舊版執行檔失敗: {Message}", rollbackEx.Message);
                }

                throw new InvalidOperationException($"替換新版執行檔失敗，已嘗試復原: {copyEx.Message}", copyEx);
            }

            // 啟動新版執行檔
            _processRunner.StartDetached(new ProcessStartSpec(
                currentExePath,
                [],
                WorkingDirectory: AppDomain.CurrentDomain.BaseDirectory,
                CreateNoWindow: false));

            Logger.Information("新版主程式已成功替換並啟動: Target={Target}, OldBackup={Backup}", currentExePath, oldExePath);

            // 嘗試清理已複製的下載更新暫存檔
            TryDelete(verifiedInstallerPath);
        }
        catch (Exception ex) when (ex is not InvalidOperationException and not FileNotFoundException)
        {
            Logger.Error("套用自動更新失敗: {Message}", ex.Message);
            throw new InvalidOperationException($"套用自動更新發生錯誤: {ex.Message}", ex);
        }
    }

    /// <summary>
    /// 清理前次更新時留下的 .old 備份檔案
    /// </summary>
    public static void TryCleanupPreviousUpdateBackup()
    {
        try
        {
            string? currentExePath = Environment.ProcessPath;
            if (!string.IsNullOrWhiteSpace(currentExePath))
            {
                string oldExePath = currentExePath + ".old";
                if (SafeFileSystem.FileExists(oldExePath))
                {
                    SafeFileSystem.DeleteFile(oldExePath);
                    Logger.Information("已清理前次更新備份檔: {Path}", oldExePath);
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning("暫時無法清理前次更新備份檔: {Message}", ex.Message);
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (SafeFileSystem.FileExists(path))
            {
                SafeFileSystem.DeleteFile(path);
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
            using var fs = SafeFileSystem.OpenRead(filePath, FileShare.Read);
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
