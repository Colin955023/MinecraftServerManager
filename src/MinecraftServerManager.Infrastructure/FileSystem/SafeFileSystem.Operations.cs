using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static partial class SafeFileSystem
{
    /// <summary>是否為 Windows 短暫檔案鎖定錯誤（ERROR_SHARING_VIOLATION / ERROR_LOCK_VIOLATION）</summary>
    internal static bool IsTransientFileLock(IOException ex) => (ex.HResult & 0xFFFF) is 32 or 33;

    /// <summary>將無法讀取或損毀的檔案複製為同目錄 <c>.bad</c> 備份；失敗時僅記錄警告</summary>
    internal static bool TryPreserveCorruptFile(string path, ComponentLogger? logger = null)
    {
        try
        {
            CopyFile(path, path + ".bad", overwrite: true);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            (logger ?? Logger).Warning(ex, "無法備份損毀的檔案: {Path}", path);
            return false;
        }
    }

    private static bool DeleteValidatedEntry(string path, bool isDirectory, bool recursive = true)
    {
        if (isDirectory)
        {
            if (recursive)
            {
                RemoveReadOnlyAttributesRecursive(path);
            }
            else
            {
                ClearReadOnlyAttribute(path);
            }

            Directory.Delete(path, recursive);
            return true;
        }

        ClearReadOnlyAttribute(path);
        File.Delete(path);
        return true;
    }

    public static void DeleteFile(string filePath)
    {
        string stablePath = ResolveStablePath(filePath);
        if (File.Exists(stablePath))
        {
            DeleteValidatedEntry(stablePath, isDirectory: false);
        }
    }

    /// <summary>盡力刪除檔案；失敗記錄警告並回傳 false</summary>
    public static bool TryDeleteFile(string? filePath)
    {
        if (string.IsNullOrEmpty(filePath))
        {
            return true;
        }

        try
        {
            DeleteFile(filePath);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "清理檔案失敗（已忽略）: {Path}", filePath);
            return false;
        }
    }

    public static void DeleteDirectory(string directoryPath, bool recursive = false)
    {
        string stablePath = ResolveStableDirectory(directoryPath);
        if (string.Equals(
                Path.TrimEndingDirectorySeparator(stablePath),
                Path.TrimEndingDirectorySeparator(Path.GetPathRoot(stablePath) ?? string.Empty),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new SafeFileSystemException("不得刪除磁碟根目錄");
        }

        DeleteValidatedEntry(stablePath, isDirectory: true, recursive);
    }

    /// <summary>搬移來源目錄的第一層項目；<paramref name="skip"/> 回傳 true 者略過</summary>
    public static void MoveChildren(
        string sourceDirectory,
        string destinationDirectory,
        Func<FileSystemEntry, bool>? skip = null,
        Action<FileSystemEntry, string>? beforeMove = null)
    {
        string destinationRoot = ResolveStableDirectory(destinationDirectory);
        foreach (FileSystemEntry entry in ListBoundedDirectory(sourceDirectory, rejectReparse: false))
        {
            if (skip?.Invoke(entry) == true)
            {
                continue;
            }

            string destination = Path.Combine(destinationRoot, Path.GetFileName(entry.FullPath));
            if (IsReparsePoint(entry.FullPath) || IsReparsePoint(destination))
            {
                throw new SafeFileSystemException($"移動來源與目的地不得為 reparse point： {entry.FullPath}");
            }

            beforeMove?.Invoke(entry, destination);
            MovePath(entry.FullPath, destination);
        }
    }

    public static void MovePath(string sourcePath, string destinationPath, bool overwrite = false)
    {
        string source = ResolveStablePath(sourcePath);
        bool isDirectory = Directory.Exists(source);
        string destination = ResolveStablePath(destinationPath, createParent: true);

        if (IsReparsePoint(source) || IsReparsePoint(destination))
        {
            throw new SafeFileSystemException("移動來源與目的地不得為 reparse point");
        }

        if (isDirectory && overwrite && Directory.Exists(destination))
        {
            ReplaceDirectory(source, destination);
            return;
        }

        MoveCore(source, destination, isDirectory, overwrite);
    }

    /// <summary>舊目標先改名暫存再搬入新目錄；搬移失敗時還原舊目標</summary>
    private static void ReplaceDirectory(string source, string destination)
    {
        string backup = $"{destination}.msm-old-{Guid.NewGuid():N}";
        MoveCore(destination, backup, isDirectory: true, overwrite: false);
        try
        {
            MoveCore(source, destination, isDirectory: true, overwrite: false);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            try
            {
                MoveCore(backup, destination, isDirectory: true, overwrite: false);
            }
            catch (Exception restoreEx) when (restoreEx is IOException or UnauthorizedAccessException)
            {
                Logger.Error(restoreEx, "還原被覆寫的目錄失敗，舊內容保留於 {Backup}", backup);
            }

            throw;
        }

        try
        {
            DeleteDirectory(backup, recursive: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or SafeFileSystemException)
        {
            Logger.Warning(ex, "清理覆寫前的舊目錄失敗（已忽略）: {Path}", backup);
        }
    }

    /// <summary>實際搬移，套用短暫鎖檔重試；邊界檢查由呼叫端負責</summary>
    private static void MoveCore(string source, string destination, bool isDirectory, bool overwrite)
    {
        if (isDirectory)
        {
            RetryOnTransientIo(() => Directory.Move(source, destination), source, TransientMoveMaxAttempts, TransientMoveBaseDelay, (ex, attempt) => attempt < GetMaxMoveAttempts(ex));
        }
        else
        {
            RetryOnTransientIo(() => File.Move(source, destination, overwrite), source, TransientMoveMaxAttempts, TransientMoveBaseDelay, (ex, attempt) => attempt < GetMaxMoveAttempts(ex));
        }
    }

    /// <summary>同步重試暫時性 I/O 動作（<paramref name="target"/> 為日誌用路徑）；僅在 attempt &lt; <paramref name="maxAttempts"/> 且 <paramref name="shouldRetry"/> 為真時，等待 <paramref name="baseDelay"/> × attempt 後重試，其餘原樣擲出</summary>
    public static void RetryOnTransientIo(Action action, string target, int maxAttempts, TimeSpan baseDelay, Func<Exception, int, bool> shouldRetry)
    {
        ArgumentNullException.ThrowIfNull(action);
        RetryOnTransientIo(
            () =>
            {
                action();
                return true;
            },
            target,
            maxAttempts,
            baseDelay,
            shouldRetry);
    }

    /// <summary>同步重試暫時性 I/O 函式，規則同 <see cref="RetryOnTransientIo{T}"/></summary>
    public static T RetryOnTransientIo<T>(Func<T> action, string target, int maxAttempts, TimeSpan baseDelay, Func<Exception, int, bool> shouldRetry)
    {
        ArgumentNullException.ThrowIfNull(action);
        ArgumentNullException.ThrowIfNull(shouldRetry);
        for (int attempt = 1; ; attempt++)
        {
            try
            {
                return action();
            }
            catch (Exception ex) when (attempt < maxAttempts && shouldRetry(ex, attempt))
            {
                Logger.Warning(ex, "暫時性 I/O 失敗（第 {Attempt} 次），稍後重試: {Target}", attempt, target);
                Thread.Sleep(baseDelay * attempt);
            }
        }
    }

    /// <summary>依失敗類型決定最多嘗試次數；不可重試者回傳 0</summary>
    private static int GetMaxMoveAttempts(Exception ex) => ex switch
    {
        // 存取遭拒多半為 ACL 或唯讀限制，僅短暫重試以涵蓋防毒掃描
        UnauthorizedAccessException => AccessDeniedMoveMaxAttempts,
        FileNotFoundException or DirectoryNotFoundException or PathTooLongException => 0,
        IOException io when IsTransientFileLock(io) => TransientMoveMaxAttempts,
        // ERROR_ACCESS_DENIED (5)
        IOException io when (io.HResult & 0xFFFF) == ErrorAccessDenied => AccessDeniedMoveMaxAttempts,
        _ => 0,
    };

    public static void CopyFile(string sourcePath, string destinationPath, bool overwrite = false)
    {
        string source = ResolveStablePath(sourcePath);
        if (!File.Exists(source) || IsReparsePoint(source))
        {
            throw new FileNotFoundException("找不到一般檔案來源", source);
        }

        string destination = ResolveStablePath(destinationPath, createParent: true);
        if (IsReparsePoint(destination))
        {
            throw new SafeFileSystemException("複製目的地不得為 reparse point");
        }

        File.Copy(source, destination, overwrite);
    }

    public static bool DeleteWithin(string baseDirectory, string targetPath)
    {
        try
        {
            string baseDir = ResolveStableDirectory(baseDirectory);
            if (!TryResolveWithinBase(baseDir, targetPath, strict: false, out string target) ||
                string.Equals(baseDir, target, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            if (IsReparsePoint(target))
            {
                return false;
            }

            bool isDir = Directory.Exists(target);
            if (!isDir && !File.Exists(target))
            {
                return false;
            }

            return DeleteValidatedEntry(target, isDirectory: isDir, recursive: true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "受限路徑刪除失敗: {Path}", targetPath);
            return false;
        }
    }

    private static bool MoveWithinCore(string baseDirectory, string sourcePath, string destinationPath, bool strict)
    {
        string baseDir = ResolveStableDirectory(baseDirectory);
        if (!TryResolveWithinBase(baseDir, sourcePath, strict: false, out string source) ||
            !TryResolveWithinBase(baseDir, destinationPath, strict: false, out string destination) ||
            string.Equals(baseDir, source, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(baseDir, destination, StringComparison.OrdinalIgnoreCase))
        {
            if (strict)
            {
                throw new SafeFileSystemException("移動來源與目的地必須在基準目錄內");
            }

            return false;
        }

        if (strict)
        {
            string? sourceParent = Path.GetDirectoryName(source);
            string? destParent = Path.GetDirectoryName(destination);
            if (!string.Equals(sourceParent, baseDir, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(destParent, baseDir, StringComparison.OrdinalIgnoreCase))
            {
                throw new SafeFileSystemException("移動來源與目的地必須是基準目錄的直接子項目");
            }
        }

        if (IsReparsePoint(source))
        {
            if (strict)
            {
                throw new SafeFileSystemException($"移動來源不可為 reparse point： {source}");
            }

            return false;
        }

        if (strict && Path.Exists(destination))
        {
            throw new SafeFileSystemException($"移動目的地已存在： {destination}");
        }

        if (!strict && IsReparsePoint(destination))
        {
            return false;
        }

        if (!strict)
        {
            string? destParent = Path.GetDirectoryName(destination);
            if (!string.IsNullOrEmpty(destParent) && !Directory.Exists(destParent))
            {
                ResolveStableDirectory(destParent, create: true);
            }
        }

        bool isDirectory = Directory.Exists(source);
        if (!isDirectory && !File.Exists(source))
        {
            if (strict)
            {
                throw new FileNotFoundException($"找不到移動來源項目： {source}");
            }

            return false;
        }

        MoveCore(source, destination, isDirectory, overwrite: !strict);
        return true;
    }

    public static bool MoveWithin(string baseDirectory, string sourcePath, string destinationPath)
    {
        try
        {
            return MoveWithinCore(baseDirectory, sourcePath, destinationPath, strict: false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "受限路徑移動失敗: {Source} -> {Destination}", sourcePath, destinationPath);
            return false;
        }
    }

    /// <summary>嚴格在基準目錄內移動直接子項目（失敗時擲出例外）</summary>
    public static void MoveWithinStrict(string baseDirectory, string sourcePath, string destinationPath) =>
        MoveWithinCore(baseDirectory, sourcePath, destinationPath, strict: true);

    /// <summary>安全遞迴複製目錄樹，強制具備符號連結防護與受限走訪</summary>
    public static void CopyDirectoryTreeSafe(string source, string destination, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        string sourceRoot = ResolveStableDirectory(source);
        string destinationRoot = GetFullPath(destination);
        if (IsSameOrDescendant(sourceRoot, destinationRoot))
        {
            throw new SafeFileSystemException($"複製目的地不可位於來源目錄內： {destinationRoot}");
        }

        var entries = EnumerateBoundedTree(sourceRoot, rejectReparse: true).ToList();
        EnsureNoReparseAlongPath(destinationRoot);
        foreach (var entry in entries)
        {
            cancellationToken.ThrowIfCancellationRequested();
            string rel = Path.GetRelativePath(sourceRoot, entry.FullPath);
            string target = Path.Combine(destinationRoot, rel);

            // 目的端與來源端一致，經穩定路徑檢查（不得含 reparse point）
            if (entry.IsDirectory)
            {
                ResolveStableDirectory(target, create: true);
            }
            else
            {
                string stableTarget = ResolveStablePath(target, createParent: true);
                ClearReadOnlyAttribute(stableTarget);
                File.Copy(entry.FullPath, stableTarget, overwrite: true);
            }
        }
    }

    public static void RemoveReadOnlyAttributesRecursive(string directoryPath)
    {
        if (string.IsNullOrWhiteSpace(directoryPath) || !Directory.Exists(directoryPath) || IsReparsePoint(directoryPath))
        {
            return;
        }

        RemoveReadOnlyAttributesRecursive(new DirectoryInfo(directoryPath));
    }

    public static void ClearReadOnlyAttribute(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        try
        {
            if (Path.Exists(path))
            {
                FileAttributes attributes = File.GetAttributes(path);
                if ((attributes & FileAttributes.ReparsePoint) == 0 && (attributes & FileAttributes.ReadOnly) != 0)
                {
                    File.SetAttributes(path, attributes & ~FileAttributes.ReadOnly);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清除唯讀屬性失敗: {Path}", path);
        }
    }

    private static void ClearReadOnly(FileSystemInfo info)
    {
        try
        {
            if ((info.Attributes & FileAttributes.ReadOnly) != 0)
            {
                info.Attributes &= ~FileAttributes.ReadOnly;
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // 單一項目失敗不得中斷其餘項目，後續刪除若仍被擋會明確回報
            Logger.Warning(ex, "清除唯讀屬性失敗: {Path}", info.FullName);
        }
    }

    // 只排除 reparse point：不下探連結目錄，且含隱藏檔
    private static readonly EnumerationOptions ClearReadOnlyEnumerationOptions = new()
    {
        RecurseSubdirectories = true,
        AttributesToSkip = FileAttributes.ReparsePoint,
    };

    private static void RemoveReadOnlyAttributesRecursive(DirectoryInfo directory)
    {
        try
        {
            ClearReadOnly(directory);

            foreach (var info in directory.EnumerateFileSystemInfos("*", ClearReadOnlyEnumerationOptions))
            {
                ClearReadOnly(info);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "遞迴清除目錄唯讀屬性失敗: {Path}", directory.FullName);
        }
    }
}
