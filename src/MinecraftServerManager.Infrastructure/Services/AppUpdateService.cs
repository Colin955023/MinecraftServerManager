using System.Buffers;
using System.Reflection.PortableExecutable;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Services;

/// <summary>應用程式自動更新下載、安全性驗證與重新啟動安裝服務實作</summary>
public sealed partial class AppUpdateService : IAppUpdateService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AppUpdateService));
    private static readonly SearchValues<char> InvalidFileNameChars = SearchValues.Create(Path.GetInvalidFileNameChars());

    [GeneratedRegex(@"\b[a-fA-F0-9]{64}\b")]
    private static partial Regex Sha256Regex();

    private readonly IHttpPort _httpPort;
    private readonly string _updatesDirectory;
    private readonly IProcessRunner _processRunner;

    public AppUpdateService(
        IHttpPort httpPort,
        string updatesDirectory,
        IProcessRunner processRunner)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        ArgumentException.ThrowIfNullOrWhiteSpace(updatesDirectory);
        ArgumentNullException.ThrowIfNull(processRunner);
        _httpPort = httpPort;
        _updatesDirectory = updatesDirectory;
        _processRunner = processRunner;
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

        if (!GitHubReleaseTrustPolicy.IsTrustedAssetUrl(update.DownloadUrl))
        {
            throw new InvalidDataException("更新檔下載位址不是本專案官方 GitHub Release，已拒絕自動更新。");
        }

        if (!GitHubReleaseTrustPolicy.IsTrustedAssetUrl(update.Sha256ChecksumUrl)
            || !Uri.TryCreate(update.Sha256ChecksumUrl, UriKind.Absolute, out var checksumUri))
        {
            throw new InvalidDataException("更新資訊缺少有效的官方 SHA-256 雜湊檔網址，已拒絕自動更新。");
        }

        progress?.Report((5, "正在取得安全驗證資訊 (SHA-256)..."));
        string? checksumText = await _httpPort.GetTextAsync(checksumUri, cancellationToken).ConfigureAwait(false);
        Match match = string.IsNullOrWhiteSpace(checksumText) ? Match.Empty : Sha256Regex().Match(checksumText);
        if (!match.Success)
        {
            throw new InvalidDataException("無法取得有效的 SHA-256 雜湊值，已拒絕自動更新。");
        }

        string expectedSha256 = match.Value.ToLowerInvariant();
        Logger.Information("成功取得預期 SHA-256 雜湊值: {Hash}", expectedSha256);

        string targetDir = _updatesDirectory;
        SafeFileSystem.CreateDirectory(targetDir);

        string targetFilePath = ResolveTargetFilePath(targetDir, downloadUri, update.LatestVersion);

        // 若本機已存在且符合 SHA-256 與 x64 執行檔結構則直接沿用
        if (SafeFileSystem.FileExists(targetFilePath))
        {
            string existingHash = await HashCalculator.ComputeFileHashAsync(targetFilePath, HashAlgorithmNames.Sha256, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (string.Equals(existingHash, expectedSha256, StringComparison.OrdinalIgnoreCase) && IsX64Executable(targetFilePath))
            {
                Logger.Information("更新檔案已存在且通過 SHA-256 驗證: {Path}", targetFilePath);
                progress?.Report((100, "更新檔案已備妥且驗證通過。"));
                return targetFilePath;
            }
        }

        progress?.Report((10, "正在下載主程式更新檔..."));
        var httpProgress = progress is null ? null : new SynchronousProgress<HttpProgress>(p =>
        {
            int percent = ProgressMapping.Map(p.BytesDownloaded, p.TotalBytes, 10, 90, unknown: 50);
            string msg = p.TotalBytes > 0
                ? $"正在下載主程式更新檔 ({UnitFormatter.FormatBytes(p.BytesDownloaded)} / {UnitFormatter.FormatBytes(p.TotalBytes)})..."
                : $"正在下載主程式更新檔 ({UnitFormatter.FormatBytes(p.BytesDownloaded)})...";
            progress.Report((percent, msg));
        });

        // 下載時已驗證 SHA-256，不再重複計算
        var downloadResult = await _httpPort.DownloadAsync(
            downloadUri,
            targetFilePath,
            httpProgress,
            expectedHash: expectedSha256,
            expectedHashAlgorithm: HashAlgorithmNames.Sha256,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!downloadResult.Success)
        {
            // 一併刪除 .part，避免下次以舊片段續傳造成雜湊不符
            DeleteDownloadArtifacts(targetFilePath);
            throw new InvalidOperationException($"下載或驗證更新檔案失敗: {downloadResult.Error}");
        }

        progress?.Report((95, "正在執行執行檔格式驗證..."));
        if (!IsX64Executable(targetFilePath))
        {
            DeleteDownloadArtifacts(targetFilePath);
            throw new InvalidDataException("更新檔案不是結構合法的 x64 Windows 執行檔，已拒絕更新。");
        }

        progress?.Report((100, "更新檔案驗證通過！"));
        Logger.Information("主程式更新檔下載並通過所有安全驗證: {Path}", targetFilePath);
        return targetFilePath;
    }

    public void ApplyUpdateAndRestart(string verifiedInstallerPath, Action<Action> launchReplacement)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(verifiedInstallerPath);
        ArgumentNullException.ThrowIfNull(launchReplacement);

        if (!SafeFileSystem.FileExists(verifiedInstallerPath))
        {
            throw new FileNotFoundException("找不到已驗證的更新檔案。", verifiedInstallerPath);
        }

        string? currentExePath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(currentExePath) || !SafeFileSystem.FileExists(currentExePath))
        {
            throw new InvalidOperationException("無法判斷目前應用程式的執行檔路徑，無法套用自動更新。");
        }

        // 套用前再驗一次結構，防止驗證後檔案遭替換
        if (!IsX64Executable(verifiedInstallerPath))
        {
            throw new InvalidDataException("更新檔案不是結構合法的 x64 Windows 執行檔，已拒絕套用。");
        }

        string oldExePath = currentExePath + ".old";
        string stagedExePath = currentExePath + ".new";

        try
        {
            // 先複製到同目錄暫存檔，確保之後的交換只是同磁碟區的重新命名
            SafeFileSystem.CopyFile(verifiedInstallerPath, stagedExePath, overwrite: true);
            SafeFileSystem.DeleteFile(oldExePath);

            // Windows 支援將執行中的檔案重新命名（原檔移至 .old）
            SafeFileSystem.MovePath(currentExePath, oldExePath, overwrite: true);

            try
            {
                SafeFileSystem.MovePath(stagedExePath, currentExePath, overwrite: true);

                // 啟動新版執行檔；啟動失敗同樣還原舊版
                launchReplacement(() => _processRunner.StartDetached(new ProcessStartSpec(
                    currentExePath,
                    [],
                    WorkingDirectory: Path.GetDirectoryName(currentExePath) ?? AppDomain.CurrentDomain.BaseDirectory,
                    CreateNoWindow: false)));
            }
            catch (Exception swapEx)
            {
                RestorePreviousExecutable(currentExePath, oldExePath);
                throw new InvalidOperationException($"替換或啟動新版執行檔失敗，已嘗試復原: {swapEx.Message}", swapEx);
            }

            Logger.Information("新版主程式已成功替換並啟動: Target={Target}, OldBackup={Backup}", currentExePath, oldExePath);

            // 嘗試清理已複製的下載更新暫存檔
            SafeFileSystem.TryDeleteFile(verifiedInstallerPath);
        }
        catch (Exception ex) when (ex is not InvalidOperationException and not FileNotFoundException)
        {
            Logger.Error(ex, "套用自動更新失敗");
            throw new InvalidOperationException($"套用自動更新發生錯誤: {ex.Message}", ex);
        }
        finally
        {
            SafeFileSystem.TryDeleteFile(stagedExePath);
        }
    }

    /// <summary>以 .old 備份還原目前執行檔</summary>
    private static void RestorePreviousExecutable(string currentExePath, string oldExePath)
    {
        try
        {
            if (SafeFileSystem.FileExists(oldExePath))
            {
                SafeFileSystem.MovePath(oldExePath, currentExePath, overwrite: true);
            }
        }
        catch (Exception rollbackEx) when (rollbackEx is not OperationCanceledException)
        {
            Logger.Error(rollbackEx, "復原舊版執行檔失敗: {Path}", oldExePath);
        }
    }

    /// <summary>由下載位址取得安全檔名；非 .exe 或含無效字元時改用版本命名，並確認位於更新目錄內</summary>
    private static string ResolveTargetFilePath(string targetDir, Uri downloadUri, string latestVersion)
    {
        string fileName = Path.GetFileName(downloadUri.LocalPath);
        if (!IsSafeExecutableFileName(fileName))
        {
            fileName = $"MinecraftServerManager-{latestVersion}.exe";
        }

        if (!IsSafeExecutableFileName(fileName))
        {
            fileName = "MinecraftServerManager-update.exe";
        }

        string targetFilePath = Path.Combine(targetDir, fileName);
        if (!SafeFileSystem.IsPathWithin(targetDir, targetFilePath, strict: false))
        {
            throw new InvalidDataException("更新檔案路徑超出更新目錄，已拒絕自動更新。");
        }

        return targetFilePath;
    }

    private static bool IsSafeExecutableFileName(string? fileName) =>
        !string.IsNullOrWhiteSpace(fileName) &&
        fileName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) &&
        fileName.AsSpan().IndexOfAny(InvalidFileNameChars) < 0 &&
        fileName.Trim().Length == fileName.Length &&
        !fileName.StartsWith('.');

    /// <summary>主程式僅發布 x64；拒絕 DLL 與其他架構</summary>
    private static bool IsX64Executable(string filePath) =>
        PortableExecutableInspector.TryReadExecutableMachine(filePath) == Machine.Amd64;

    private static void DeleteDownloadArtifacts(string targetFilePath)
    {
        SafeFileSystem.TryDeleteFile(targetFilePath);
        SafeFileSystem.TryDeleteFile(targetFilePath + ".part");
    }

    /// <summary>清理前次更新時留下的 .old 備份檔案；由背景預熱呼叫，避免建構時同步 I/O</summary>
    public void CleanupPreviousUpdateBackup()
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
            Logger.Warning(ex, "暫時無法清理前次更新備份檔");
        }
    }

}
