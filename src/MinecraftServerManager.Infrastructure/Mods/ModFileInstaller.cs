using System.Buffers;
using System.Collections.Frozen;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>模組檔案異動、啟停、批次刪除與原子交易安裝實作</summary>
public sealed class ModFileInstaller
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModFileInstaller));
    private static readonly FrozenSet<string> ModrinthHosts = TrustedHostPolicy.Hosts("cdn.modrinth.com", "modrinth.com");

    private readonly IHttpPort _httpPort;

    public ModFileInstaller(IHttpPort httpPort)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        _httpPort = httpPort;
    }

    public static async Task<LocalModMutationResult> SetModStateAsync(
        string modsDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(modId);
        cancellationToken.ThrowIfCancellationRequested();

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        var (enabledFile, disabledFile) = ResolveModFilePaths(stableModsDir, modId);
        string cleanModId = ModHelpers.ModFilenameStem(Path.GetFileName(enabledFile));

        string srcFile = enable ? disabledFile : enabledFile;
        string dstFile = enable ? enabledFile : disabledFile;
        string action = enable ? "啟用" : "停用";

        if (SafeFileSystem.FileExists(dstFile) && !SafeFileSystem.FileExists(srcFile))
        {
            return LocalModMutationResult.Success($"模組已處於{action}狀態");
        }

        if (SafeFileSystem.FileExists(dstFile) && SafeFileSystem.FileExists(srcFile))
        {
            if (SafeFileSystem.GetFileLength(srcFile) == SafeFileSystem.GetFileLength(dstFile) && await HasSameContentAsync(srcFile, dstFile, cancellationToken).ConfigureAwait(false))
            {
                return SafeFileSystem.DeleteWithin(stableModsDir, srcFile)
                    ? LocalModMutationResult.Success($"模組已處於{action}狀態並已清理重複檔案")
                    : LocalModMutationResult.Failure($"{action}失敗", $"無法清理重複的模組檔案：{Path.GetFileName(srcFile)}");
            }

            string bakFile = Path.Combine(stableModsDir, $"{cleanModId}.conflict.bak");
            if (SafeFileSystem.FileExists(bakFile))
            {
                bakFile = Path.Combine(stableModsDir, $"{cleanModId}.conflict.{DateTimeOffset.UtcNow.ToUnixTimeSeconds()}.bak");
            }
            return SafeFileSystem.MoveWithin(stableModsDir, srcFile, bakFile)
                ? LocalModMutationResult.Success($"偵測到衝突檔案，已改名保留備份：{Path.GetFileName(bakFile)}")
                : LocalModMutationResult.Failure($"{action}失敗", $"無法改名衝突的模組檔案：{Path.GetFileName(srcFile)}");
        }

        if (SafeFileSystem.FileExists(srcFile))
        {
            return SafeFileSystem.MoveWithin(stableModsDir, srcFile, dstFile)
                ? LocalModMutationResult.Success($"已成功{action}模組：{Path.GetFileName(dstFile)}")
                : LocalModMutationResult.Failure($"{action}失敗", $"無法移動模組檔案（可能被其他程式占用）：{Path.GetFileName(srcFile)}");
        }

        return LocalModMutationResult.Failure($"{action}失敗", $"找不到模組檔案：{Path.GetFileName(srcFile)}");
    }

    public static Task<LocalModMutationResult> DeleteModsAsync(
        string modsDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        cancellationToken.ThrowIfCancellationRequested();

        if (modIds is null || modIds.Count == 0)
        {
            return Task.FromResult(LocalModMutationResult.Failure("刪除失敗", "沒有可刪除的模組清單"));
        }

        return Task.Run(() =>
        {
            string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
            // 目錄只列舉一次，供所有識別碼比對
            var modStems = ListModStems(stableModsDir);
            int deletedCount = 0;
            int missingCount = 0;
            int failedCount = 0;

            foreach (string modId in modIds)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var (enabledPath, disabledPath) = ResolveModFilePaths(stableModsDir, modId, modStems);
                var (found, allSucceeded) = ModFileVariants.DeleteVariants(stableModsDir, enabledPath, disabledPath);

                if (!found)
                {
                    missingCount++;
                }
                else if (!allSucceeded)
                {
                    failedCount++;
                }
                else
                {
                    deletedCount++;
                }
            }

            if (deletedCount > 0 && missingCount == 0 && failedCount == 0)
            {
                return LocalModMutationResult.Success($"已成功刪除 {deletedCount} 個模組檔案", affectedCount: deletedCount);
            }

            if (deletedCount > 0)
            {
                string detail = failedCount > 0
                    ? $"已刪除 {deletedCount} 個模組，但有 {missingCount} 個未找到、{failedCount} 個無法刪除"
                    : $"已刪除 {deletedCount} 個模組，但有 {missingCount} 個未找到";
                return new LocalModMutationResult(ModOperationStatus.Partial, "部分刪除成功", detail, deletedCount);
            }

            return failedCount > 0
                ? LocalModMutationResult.Failure("刪除失敗", $"有 {failedCount} 個模組檔案無法刪除（可能被其他程式占用）")
                : LocalModMutationResult.Failure("刪除失敗", "找不到任何可刪除的模組檔案");
        }, cancellationToken);
    }

    public static Task<LocalModMutationResult> ImportLocalModAsync(
        string modsDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(sourceFilePath);
        cancellationToken.ThrowIfCancellationRequested();

        return Task.Run(() =>
        {
            if (!SafeFileSystem.FileExists(sourceFilePath))
            {
                return LocalModMutationResult.Failure("匯入失敗", $"來源檔案不存在：{sourceFilePath}");
            }

            string fileName = Path.GetFileName(sourceFilePath);
            if (!ModHelpers.IsJarFileName(fileName))
            {
                return LocalModMutationResult.Failure("匯入失敗", "僅支援 .jar 格式模組檔案");
            }

            string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
            string targetPath = Path.Combine(stableModsDir, fileName);
            if (!SafeFileSystem.IsPathWithin(stableModsDir, targetPath, strict: false))
            {
                return LocalModMutationResult.Failure("匯入失敗", "目標路徑超出模組資料夾邊界");
            }

            if (string.Equals(Path.GetFullPath(sourceFilePath), targetPath, StringComparison.OrdinalIgnoreCase))
            {
                return LocalModMutationResult.Success($"模組「{fileName}」已位於模組資料夾");
            }

            // 先複製至同目錄暫存檔再原子替換，避免中斷時留下不完整的 jar
            string tempPath = AtomicFileWriter.CreateTempSiblingPath(targetPath);
            try
            {
                SafeFileSystem.CopyFile(sourceFilePath, tempPath, overwrite: true);
                if (!AtomicFileWriter.ReplaceFile(tempPath, targetPath))
                {
                    return LocalModMutationResult.Failure("匯入失敗", $"無法寫入模組檔案（可能被其他程式占用）：{fileName}");
                }
            }
            finally
            {
                if (SafeFileSystem.FileExists(tempPath))
                {
                    SafeFileSystem.DeleteWithin(stableModsDir, tempPath);
                }
            }

            return LocalModMutationResult.Success($"模組「{fileName}」已成功匯入");
        }, cancellationToken);
    }

    public async Task<ModFileOperationResult> InstallRemoteModAsync(
        string modsDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        ArgumentException.ThrowIfNullOrWhiteSpace(downloadUrl);
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);
        cancellationToken.ThrowIfCancellationRequested();

        if (!IsOfficialModrinthSource(downloadUrl))
        {
            return ModFileOperationResult.Fail("模組下載來源非官方 Modrinth CDN，已拒絕下載");
        }

        if (string.IsNullOrWhiteSpace(expectedHash))
        {
            return ModFileOperationResult.Fail("線上模組缺少校驗雜湊值，已拒絕下載");
        }

        string safeFileName = Path.GetFileName(fileName);
        if (!ModHelpers.IsJarFileName(safeFileName))
        {
            return ModFileOperationResult.Fail("僅支援 .jar 格式模組檔案");
        }

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        string stagingRoot = Path.Combine(stableModsDir, ".download_staging");
        SafeFileSystem.ResolveStableDirectory(stagingRoot, create: true);
        string stagingDir = Path.Combine(stagingRoot, Guid.NewGuid().ToString("N"));
        SafeFileSystem.ResolveStableDirectory(stagingDir, create: true);

        string tempFilePath = AtomicFileWriter.CreateTempSiblingPath(Path.Combine(stagingDir, safeFileName));
        string finalTargetPath = Path.Combine(stableModsDir, safeFileName);
        string? backupFilePath = null;
        string algo = !string.IsNullOrEmpty(hashAlgorithm) ? hashAlgorithm : ModHelpers.PreferredHashAlgorithm;

        try
        {
            // 下載並於串流管線中即時增量驗證雜湊（消除下載後二次全檔磁碟讀取 I/O）
            var downloadResult = await _httpPort.DownloadAsync(
                new Uri(downloadUrl),
                tempFilePath,
                progress: progress is not null ? new SynchronousProgress<HttpProgress>(p =>
                {
                    if (p.TotalBytes > 0)
                    {
                        progress.Report(ProgressMapping.Map(p.BytesDownloaded, p.TotalBytes, 0, 100));
                    }
                }) : null,
                expectedHash: expectedHash,
                expectedHashAlgorithm: algo,
                cancellationToken: cancellationToken).ConfigureAwait(false);

            if (!downloadResult.Success)
            {
                Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
                return ModFileOperationResult.Fail($"下載或雜湊驗證失敗：{downloadResult.Error}");
            }

            // 備份舊檔案（若存在）
            if (SafeFileSystem.FileExists(finalTargetPath))
            {
                backupFilePath = Path.Combine(stagingDir, $"{safeFileName}.bak");
                if (!SafeFileSystem.MoveWithin(stableModsDir, finalTargetPath, backupFilePath))
                {
                    backupFilePath = null;
                    Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
                    return ModFileOperationResult.Fail("無法備份既有模組檔案");
                }
            }

            // 移動新檔案至目標路徑
            if (!SafeFileSystem.MoveWithin(stableModsDir, tempFilePath, finalTargetPath))
            {
                Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
                return ModFileOperationResult.Fail("無法移動模組檔案至目標位置");
            }

            // 清理備份
            if (backupFilePath is not null && SafeFileSystem.FileExists(backupFilePath))
            {
                SafeFileSystem.DeleteWithin(stagingDir, backupFilePath);
            }

            return ModFileOperationResult.Success("安裝成功");
        }
        catch (OperationCanceledException)
        {
            Logger.Information("線上模組安裝已取消，已回滾暫存檔案: {FileName}", safeFileName);
            Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
            return ModFileOperationResult.Cancel("已取消安裝");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "安裝線上模組失敗: {FileName}", safeFileName);
            Rollback(stableModsDir, tempFilePath, finalTargetPath, backupFilePath);
            return ModFileOperationResult.Fail($"安裝失敗：{ex.Message}");
        }
        finally
        {
            TryCleanupStagingDir(stableModsDir, stagingDir);
        }
    }

    /// <summary>清理模組目錄中的 .download_staging 暫存資料夾（避免誤刪併發進行中的下載子項）</summary>
    public static void CleanupStagingDirectory(string modsDirectory)
    {
        try
        {
            string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory);
            string stagingRoot = Path.Combine(stableModsDir, ".download_staging");
            if (!SafeFileSystem.DirectoryExists(stagingRoot))
            {
                return;
            }

            var now = DateTimeOffset.UtcNow;
            foreach (var entry in SafeFileSystem.ListBoundedDirectory(stagingRoot, rejectReparse: true))
            {
                if (entry.IsDirectory)
                {
                    if (SafeFileSystem.IsDirectoryEmpty(entry.FullPath) ||
                        (now - entry.LastWriteTimeUtc) > TimeSpan.FromMinutes(30))
                    {
                        SafeFileSystem.DeleteWithin(stagingRoot, entry.FullPath);
                    }
                }
                else
                {
                    SafeFileSystem.DeleteWithin(stagingRoot, entry.FullPath);
                }
            }

            if (SafeFileSystem.IsDirectoryEmpty(stagingRoot))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, stagingRoot);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清理模組暫存目錄失敗");
        }
    }

    private static void TryCleanupStagingDir(string stableModsDir, string stagingDir)
    {
        try
        {
            if (SafeFileSystem.DirectoryExists(stagingDir) && SafeFileSystem.IsDirectoryEmpty(stagingDir))
            {
                SafeFileSystem.DeleteWithin(stableModsDir, stagingDir);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清理暫存子目錄失敗");
        }
    }

    private static void Rollback(string stableModsDir, string tempPath, string targetPath, string? backupPath)
    {
        try
        {
            foreach (string leftover in (ReadOnlySpan<string>)[tempPath, tempPath + ".part"])
            {
                if (SafeFileSystem.FileExists(leftover))
                {
                    SafeFileSystem.DeleteWithin(stableModsDir, leftover);
                }
            }
            if (backupPath is not null && SafeFileSystem.FileExists(backupPath))
            {
                if (!SafeFileSystem.MoveWithin(stableModsDir, backupPath, targetPath))
                {
                    Logger.Error("模組安裝復原失敗，原檔保留於: {BackupPath}", backupPath);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "模組安裝復原（Rollback）失敗");
        }
    }

    /// <summary>列出模組目錄中所有模組檔的檔名主幹（不拒絕 reparse point，僅讀取名稱）</summary>
    private static List<string> ListModStems(string stableModsDir)
    {
        var stems = new List<string>();
        foreach (FileSystemEntry entry in SafeFileSystem.ListBoundedDirectory(stableModsDir, rejectReparse: false))
        {
            ReadOnlySpan<char> fileName = Path.GetFileName(entry.FullPath.AsSpan());
            if (!entry.IsDirectory && ModHelpers.IsModFileName(fileName))
            {
                stems.Add(ModHelpers.ModFilenameStem(fileName).ToString());
            }
        }

        return stems;
    }

    private static (string EnabledPath, string DisabledPath) ResolveModFilePaths(string stableModsDir, string modId, IReadOnlyList<string>? modStems = null)
    {
        ReadOnlySpan<char> raw = modId.AsSpan().Trim();
        int hashIdx = raw.IndexOf('#');
        if (hashIdx >= 0)
        {
            raw = raw[..hashIdx];
        }

        ReadOnlySpan<char> cleanSpan = ModHelpers.ModFilenameStem(Path.GetFileName(raw.Trim("'\" \r\n\t")));
        string cleanModId = cleanSpan.ToString();

        if (!ModFileVariants.TryGetPaths(stableModsDir, cleanModId, out string? enabledPath, out string? disabledPath, requireModExtension: false))
        {
            enabledPath = Path.Combine(stableModsDir, ModHelpers.ToEnabledModFileName(cleanModId));
            disabledPath = Path.Combine(stableModsDir, ModHelpers.ToDisabledModFileName(cleanModId));
        }

        if (SafeFileSystem.FileExists(enabledPath) || SafeFileSystem.FileExists(disabledPath))
        {
            return (enabledPath, disabledPath);
        }

        // 完全相符優先；前綴相符須唯一，避免 sodium 誤中 sodium-extra
        string? exact = null;
        var prefixed = new List<string>();
        foreach (string stem in modStems ?? ListModStems(stableModsDir))
        {
            if (stem.Equals(cleanModId, StringComparison.OrdinalIgnoreCase))
            {
                exact = stem;
                break;
            }

            if (stem.Length > cleanModId.Length
                && stem.StartsWith(cleanModId, StringComparison.OrdinalIgnoreCase)
                && stem[cleanModId.Length] is '-' or '_')
            {
                prefixed.Add(stem);
            }
        }

        string? matchedStem = exact ?? (prefixed.Distinct(StringComparer.OrdinalIgnoreCase).Count() == 1 ? prefixed[0] : null);
        if (matchedStem is not null && ModFileVariants.TryGetPaths(stableModsDir, matchedStem, out string? mEnabled, out string? mDisabled, requireModExtension: false))
        {
            return (mEnabled, mDisabled);
        }

        if (prefixed.Count > 1)
        {
            Logger.Warning("模組識別碼對應到多個檔案，略過以免誤動: {ModId}", cleanModId);
        }

        return (enabledPath, disabledPath);
    }

    /// <summary>是否為官方 Modrinth 來源（HTTPS、預設埠、無使用者資訊）</summary>
    public static bool IsOfficialModrinthSource(string? url) => TrustedHostPolicy.IsTrusted(url, ModrinthHosts);

    /// <summary>逐塊比對內容（呼叫端已確認長度相同）；讀取失敗視為不同</summary>
    private static async Task<bool> HasSameContentAsync(string firstFile, string secondFile, CancellationToken cancellationToken)
    {
        const int ChunkSize = 81920;
        byte[] firstBuffer = ArrayPool<byte>.Shared.Rent(ChunkSize);
        byte[] secondBuffer = ArrayPool<byte>.Shared.Rent(ChunkSize);
        try
        {
            using var first = SafeFileSystem.OpenRead(firstFile, FileShare.Read, FileOptions.SequentialScan | FileOptions.Asynchronous);
            using var second = SafeFileSystem.OpenRead(secondFile, FileShare.Read, FileOptions.SequentialScan | FileOptions.Asynchronous);
            while (true)
            {
                int firstRead = await first.ReadAtLeastAsync(firstBuffer.AsMemory(0, ChunkSize), ChunkSize, throwOnEndOfStream: false, cancellationToken).ConfigureAwait(false);
                int secondRead = await second.ReadAtLeastAsync(secondBuffer.AsMemory(0, ChunkSize), ChunkSize, throwOnEndOfStream: false, cancellationToken).ConfigureAwait(false);
                if (!firstBuffer.AsSpan(0, firstRead).SequenceEqual(secondBuffer.AsSpan(0, secondRead)))
                {
                    return false;
                }

                if (firstRead < ChunkSize)
                {
                    return true;
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "比對模組檔案內容失敗: {FilePath}", firstFile);
            return false;
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(firstBuffer);
            ArrayPool<byte>.Shared.Return(secondBuffer);
        }
    }
}
