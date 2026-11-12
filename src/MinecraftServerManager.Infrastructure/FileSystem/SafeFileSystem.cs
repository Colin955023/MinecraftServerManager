using MinecraftServerManager.Infrastructure.Logging;
using System.Text;
using MinecraftServerManager.Infrastructure.Utilities;
using System.IO.Enumeration;
using FindEntry = System.IO.Enumeration.FileSystemEntry;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public sealed record FileSystemEntry(
    string FullPath,
    bool IsDirectory,
    long Length,
    DateTime LastWriteTimeUtc = default,
    DateTime CreationTimeUtc = default);

public sealed record FileSystemMetadata(
    string FullPath,
    string Name,
    long Length,
    DateTime LastWriteTimeUtc,
    DateTime CreationTimeUtc,
    FileAttributes Attributes);

public static class SafeFileSystem
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(SafeFileSystem));
    private static readonly Encoding DefaultUtf8Encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
    public const int DefaultMaxEntries = 100_000;
    public const long DefaultMaxTotalBytes = 128L * 1024 * 1024 * 1024;

    // 與 DirectoryInfo 預設列舉一致：包含隱藏／系統項目、遇到無法存取的目錄擲出例外（不吞沒）
    private static readonly EnumerationOptions FlatEnumerationOptions = new() { AttributesToSkip = 0, IgnoreInaccessible = false, ReturnSpecialDirectories = false };
    private static readonly EnumerationOptions TreeEnumerationOptions = new() { RecurseSubdirectories = true, AttributesToSkip = 0, IgnoreInaccessible = false, ReturnSpecialDirectories = false };

    public static string ResolveStableDirectory(string path, bool create = false)
    {
        string fullPath = GetFullPath(path);
        if (create)
        {
            Directory.CreateDirectory(fullPath);
        }

        if (!Directory.Exists(fullPath))
        {
            throw new DirectoryNotFoundException(fullPath);
        }

        EnsureNoReparseAlongPath(fullPath);
        return fullPath;
    }

    public static string ResolveStablePath(string path, bool createParent = false)
    {
        string fullPath = GetFullPath(path);
        if (Path.GetDirectoryName(fullPath) is not { } parent)
        {
            // 路徑本身即根目錄（磁碟機根或 UNC 共用根）：沒有父資料夾，直接驗證根目錄存在
            return ResolveStableDirectory(fullPath);
        }

        ResolveStableDirectory(parent, createParent);
        EnsureNotReparsePoint(fullPath);
        return fullPath;
    }

    /// <summary>驗證一般檔案路徑後檢查檔案是否存在。</summary>
    public static bool FileExists(string path)
    {
        try
        {
            return File.Exists(ResolveStablePath(path));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return false;
        }
    }

    /// <summary>驗證目錄路徑後檢查目錄是否存在。</summary>
    public static bool DirectoryExists(string path)
    {
        try
        {
            return Directory.Exists(ResolveStablePath(path));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return false;
        }
    }

    /// <summary>建立經過路徑穩定性檢查的目錄。</summary>
    public static string CreateDirectory(string path) => ResolveStableDirectory(path, create: true);

    private static IEnumerable<FileSystemEntry> EnumerateEntries(string directoryPath, SearchOption searchOption) => searchOption switch
    {
        SearchOption.TopDirectoryOnly => ListBoundedDirectory(directoryPath),
        SearchOption.AllDirectories => EnumerateBoundedTree(directoryPath),
        _ => throw new ArgumentOutOfRangeException(nameof(searchOption)),
    };

    private static bool MatchesPattern(FileSystemEntry entry, bool isDirectory, string searchPattern) =>
        entry.IsDirectory == isDirectory &&
        FileSystemName.MatchesSimpleExpression(searchPattern, Path.GetFileName(entry.FullPath), ignoreCase: true);

    /// <summary>以受限走訪列舉目錄中的檔案。</summary>
    public static IReadOnlyList<string> EnumerateFiles(
        string directoryPath,
        string searchPattern,
        SearchOption searchOption = SearchOption.TopDirectoryOnly)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(searchPattern);
        return [.. EnumerateEntries(directoryPath, searchOption)
            .Where(entry => MatchesPattern(entry, isDirectory: false, searchPattern))
            .Select(static entry => entry.FullPath)];
    }

    /// <summary>檢查目錄中是否存在符合條件之檔案，支援提早短路傳回以避免完整樹狀走訪與集合配置。</summary>
    public static bool HasAnyFile(
        string directoryPath,
        string searchPattern,
        SearchOption searchOption = SearchOption.TopDirectoryOnly)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(searchPattern);
        if (string.IsNullOrWhiteSpace(directoryPath) || !DirectoryExists(directoryPath))
        {
            return false;
        }

        try
        {
            return EnumerateEntries(directoryPath, searchOption)
                .Any(entry => MatchesPattern(entry, isDirectory: false, searchPattern));
        }
        catch (Exception ex) when (ex is SafeFileSystemException or IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    /// <summary>取得經過路徑穩定性檢查之目錄的最後修改時間。</summary>
    public static DateTime GetDirectoryLastWriteTime(string path) =>
        Directory.GetLastWriteTime(ResolveStableDirectory(path));

    /// <summary>判斷目錄是否沒有任何項目；延遲列舉，遇到第一筆即傳回，不建立完整清單。</summary>
    public static bool IsDirectoryEmpty(string directoryPath) =>
        !new DirectoryInfo(ResolveStableDirectory(directoryPath)).EnumerateFileSystemInfos().Any();

    /// <summary>取得指定路徑所在磁碟之可用剩餘空間位元組數；若無法取得或路徑無效則傳回 null。</summary>
    public static long? GetAvailableFreeSpace(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        try
        {
            string? root = Path.GetPathRoot(Path.GetFullPath(path));
            if (string.IsNullOrWhiteSpace(root))
            {
                return null;
            }

            var drive = new DriveInfo(root);
            if (drive.IsReady)
            {
                return drive.AvailableFreeSpace;
            }
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "查詢路徑 {Path} 磁碟剩餘空間失敗", path);
        }

        return null;
    }

    public static long GetFileLength(string path) => new FileInfo(ResolveStablePath(path)).Length;

    public static DateTime GetFileLastWriteTimeUtc(string path) => File.GetLastWriteTimeUtc(ResolveStablePath(path));

    public static FileSystemMetadata GetFileMetadata(string path)
    {
        string stablePath = ResolveStablePath(path);
        var info = new FileInfo(stablePath);
        info.Refresh();
        if (!info.Exists)
        {
            throw new FileNotFoundException("找不到檔案", stablePath);
        }

        return new FileSystemMetadata(
            info.FullName,
            info.Name,
            info.Length,
            info.LastWriteTimeUtc,
            info.CreationTimeUtc,
            info.Attributes);
    }

    public static void SetDirectoryHidden(string path, bool hidden)
    {
        string stablePath = ResolveStableDirectory(path);
        FileAttributes attributes = File.GetAttributes(stablePath);
        FileAttributes updated = hidden ? attributes | FileAttributes.Hidden : attributes & ~FileAttributes.Hidden;
        if (updated != attributes)
        {
            File.SetAttributes(stablePath, updated);
        }
    }

    public static IReadOnlyList<string> EnumerateDirectories(
        string directoryPath,
        string searchPattern = "*",
        SearchOption searchOption = SearchOption.TopDirectoryOnly)
    {
        return [.. EnumerateEntries(directoryPath, searchOption)
            .Where(entry => MatchesPattern(entry, isDirectory: true, searchPattern))
            .Select(static entry => entry.FullPath)];
    }

    public static FileStream OpenRead(
        string filePath,
        FileShare share = FileShare.Read,
        FileOptions options = FileOptions.SequentialScan)
    {
        string stablePath = ResolveStablePath(filePath);
        if (!File.Exists(stablePath))
        {
            throw new FileNotFoundException("找不到檔案", stablePath);
        }

        return new FileStream(stablePath, FileMode.Open, FileAccess.Read, share, 4096, options);
    }

    /// <summary>將 UTF-8 位元組解碼為字串，並自動剝除開頭的 UTF-8 BOM（避免首字元殘留 \uFEFF）</summary>
    public static string DecodeUtf8WithoutBom(ReadOnlySpan<byte> bytes)
    {
        if (bytes.StartsWith(Encoding.UTF8.Preamble))
        {
            bytes = bytes[Encoding.UTF8.Preamble.Length..];
        }

        return Encoding.UTF8.GetString(bytes);
    }

    public static string ReadAllText(string filePath, Encoding? encoding = null, long maxBytes = 16L * 1024 * 1024)
    {
        byte[] bytes = ReadRegularFile(filePath, maxBytes)
            ?? throw new FileNotFoundException("找不到或無法安全讀取檔案", filePath);
        return (encoding ?? Encoding.UTF8).GetString(bytes);
    }

    public static string[] ReadAllLines(string filePath, Encoding? encoding = null, long maxBytes = 16L * 1024 * 1024)
    {
        byte[] bytes = ReadRegularFile(filePath, maxBytes)
            ?? throw new FileNotFoundException("找不到或無法安全讀取檔案", filePath);
        using var reader = new StreamReader(new MemoryStream(bytes, writable: false), encoding ?? Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
        var lines = new List<string>();
        while (reader.ReadLine() is { } line)
        {
            lines.Add(line);
        }

        return [.. lines];
    }

    public static async Task<string> ReadAllTextAsync(
        string filePath,
        Encoding? encoding = null,
        long maxBytes = 16L * 1024 * 1024,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        string stablePath = ResolveStablePath(filePath);
        var info = new FileInfo(stablePath);
        if (!info.Exists || (info.Attributes & FileAttributes.Directory) != 0)
        {
            throw new FileNotFoundException("找不到或無法安全讀取檔案", filePath);
        }

        if (info.Length > maxBytes)
        {
            throw new IOException($"檔案大小超過安全上限：{filePath}");
        }

        return await File.ReadAllTextAsync(stablePath, encoding ?? Encoding.UTF8, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// 讀取檔案尾端最多 <paramref name="maxBytes"/> 位元組並以 UTF-8 解碼（允許對方持續寫入／刪除）；
    /// <paramref name="truncated"/> 表示檔案較大而僅讀取尾端，首行可能不完整
    /// </summary>
    public static string ReadTailText(string filePath, int maxBytes, out bool truncated)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(maxBytes);
        using var stream = OpenRead(filePath, FileShare.ReadWrite | FileShare.Delete);
        long length = stream.Length;
        truncated = length > maxBytes;
        if (length == 0)
        {
            return string.Empty;
        }

        int bytesToRead = (int)Math.Min(length, maxBytes);
        stream.Seek(-bytesToRead, SeekOrigin.End);
        byte[] buffer = System.Buffers.ArrayPool<byte>.Shared.Rent(bytesToRead);
        try
        {
            int bytesRead = stream.ReadAtLeast(buffer.AsSpan(0, bytesToRead), bytesToRead, throwOnEndOfStream: false);
            return Encoding.UTF8.GetString(buffer, 0, bytesRead);
        }
        finally
        {
            System.Buffers.ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    public static async Task WriteAllBytesAsync(
        string filePath,
        ReadOnlyMemory<byte> content,
        CancellationToken cancellationToken = default)
    {
        if (!await AtomicFileWriter.WriteBytesAsync(filePath, content, cancellationToken: cancellationToken).ConfigureAwait(false))
        {
            throw new IOException($"無法安全寫入檔案：{filePath}");
        }
    }

    public static Task WriteAllTextAsync(
        string filePath,
        string content,
        Encoding? encoding = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(content);
        Encoding textEncoding = encoding ?? DefaultUtf8Encoding;
        ReadOnlySpan<byte> preamble = textEncoding.GetPreamble();
        byte[] body = textEncoding.GetBytes(content);
        if (preamble.IsEmpty)
        {
            return WriteAllBytesAsync(filePath, body, cancellationToken);
        }

        byte[] payload = new byte[preamble.Length + body.Length];
        preamble.CopyTo(payload);
        body.CopyTo(payload.AsSpan(preamble.Length));
        return WriteAllBytesAsync(filePath, payload, cancellationToken);
    }

    public static void DeleteFile(string filePath)
    {
        string stablePath = ResolveStablePath(filePath);
        if (File.Exists(stablePath))
        {
            ClearReadOnlyAttribute(stablePath);
            File.Delete(stablePath);
        }
    }

    /// <summary>盡力刪除檔案（暫存檔清理用）：路徑為空或檔案不存在視為成功；IO／權限失敗時記錄警告並回傳 false，不擲出例外</summary>
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
        if (string.Equals(stablePath, Path.GetPathRoot(stablePath), StringComparison.OrdinalIgnoreCase))
        {
            throw new SafeFileSystemException("不得刪除磁碟根目錄");
        }

        if (recursive)
        {
            RemoveReadOnlyAttributesRecursive(stablePath);
        }
        else
        {
            ClearReadOnlyAttribute(stablePath);
        }

        Directory.Delete(stablePath, recursive);
    }

    /// <summary>
    /// 將來源目錄的第一層項目逐一搬移至目的目錄（同名保留原檔名）。
    /// <paramref name="skip"/> 回傳 true 的項目不搬移；<paramref name="beforeMove"/> 於每次搬移前以（項目, 目的路徑）呼叫。
    /// </summary>
    public static void MoveChildren(
        string sourceDirectory,
        string destinationDirectory,
        Func<FileSystemEntry, bool>? skip = null,
        Action<FileSystemEntry, string>? beforeMove = null)
    {
        foreach (FileSystemEntry entry in ListBoundedDirectory(sourceDirectory, rejectReparse: false))
        {
            if (skip?.Invoke(entry) == true)
            {
                continue;
            }

            string destination = Path.Combine(destinationDirectory, Path.GetFileName(entry.FullPath));
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
            DeleteDirectory(destination, recursive: true);
        }

        MoveCore(source, destination, isDirectory, overwrite);
    }

    /// <summary>所有移動入口共用的實際搬移：邊界與 reparse 檢查由呼叫端負責，此處統一套用防毒／索引短暫鎖檔的重試</summary>
    private static void MoveCore(string source, string destination, bool isDirectory, bool overwrite)
    {
        if (isDirectory)
        {
            RetryTransientMove(() => Directory.Move(source, destination));
        }
        else
        {
            RetryTransientMove(() => File.Move(source, destination, overwrite));
        }
    }

    // 剛解壓或寫入的檔案常被防毒或索引短暫開啟，稍候重試即可成功
    private const int TransientMoveMaxAttempts = 8;
    private static readonly TimeSpan TransientMoveBaseDelay = TimeSpan.FromMilliseconds(150);

    private static void RetryTransientMove(Action move)
    {
        for (int attempt = 1; ; attempt++)
        {
            try
            {
                move();
                return;
            }
            catch (Exception ex) when (attempt < TransientMoveMaxAttempts && IsTransientMoveFailure(ex))
            {
                Logger.Warning(ex, "移動路徑暫時遭拒（第 {Attempt} 次），稍後重試", attempt);
                Thread.Sleep(TransientMoveBaseDelay * attempt);
            }
        }
    }

    private static bool IsTransientMoveFailure(Exception ex) => ex switch
    {
        UnauthorizedAccessException => true,
        FileNotFoundException or DirectoryNotFoundException or PathTooLongException => false,
        // ERROR_ACCESS_DENIED (5)、ERROR_SHARING_VIOLATION (32)、ERROR_LOCK_VIOLATION (33)
        IOException io => (io.HResult & 0xFFFF) is 5 or 32 or 33,
        _ => false,
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

    public static bool IsReparsePoint(string path)
    {
        try
        {
            // FileInfo.Attributes 對不存在的路徑回傳 -1 而不擲例外：單次系統呼叫，且不以例外作為常態流程
            FileAttributes attributes = new FileInfo(GetFullPath(path)).Attributes;
            return attributes != (FileAttributes)(-1) && (attributes & FileAttributes.ReparsePoint) != 0;
        }
        catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException)
        {
            return false;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // 無法讀取屬性時視為 reparse point（失敗即拒絕）
            return true;
        }
    }

    public static bool IsPathWithin(string baseDirectory, string targetPath, bool strict = true)
    {
        try
        {
            string basePath = ResolveStableDirectory(baseDirectory);
            string target = GetFullPath(targetPath);
            string relative = Path.GetRelativePath(basePath, target);
            bool within = relative is "."
                || (!Path.IsPathFullyQualified(relative)
                    && !relative.Equals("..", StringComparison.Ordinal)
                    && !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal));
            if (!within)
            {
                return false;
            }

            if (strict && !Path.Exists(target))
            {
                return false;
            }

            string? existingParent = Path.Exists(target)
                ? target
                : Path.GetDirectoryName(target);
            if (existingParent is null)
            {
                return false;
            }

            EnsureNoReparseAlongPath(existingParent, basePath);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    /// <summary>列舉單一目錄（不下探）並套用項目數、總位元組與 reparse point 安全上限；結果為即時清單。</summary>
    public static IReadOnlyList<FileSystemEntry> ListBoundedDirectory(
        string directoryPath,
        int maxEntries = DefaultMaxEntries,
        long maxTotalBytes = DefaultMaxTotalBytes,
        bool rejectReparse = true)
    {
        ValidateLimits(maxEntries, maxTotalBytes);
        string directory = ResolveStableDirectory(directoryPath);
        var factory = new BoundedEntryFactory(directoryPath, maxEntries, maxTotalBytes, rejectReparse);
        return [.. new FileSystemEnumerable<FileSystemEntry>(directory, factory.Create, FlatEnumerationOptions)];
    }

    /// <summary>以串流延遲列舉走訪目錄樹，支援剪枝述詞（pruneDirectory 回傳 true 則不向下遞迴）與總量安全上限</summary>
    public static IEnumerable<FileSystemEntry> EnumerateBoundedTree(
        string directoryPath,
        int maxEntries = DefaultMaxEntries,
        long maxTotalBytes = DefaultMaxTotalBytes,
        bool rejectReparse = true,
        Func<string, string, bool>? pruneDirectory = null)
    {
        ValidateLimits(maxEntries, maxTotalBytes);
        string root = ResolveStableDirectory(directoryPath);
        var factory = new BoundedEntryFactory(directoryPath, maxEntries, maxTotalBytes, rejectReparse);
        var walk = new FileSystemEnumerable<FileSystemEntry>(root, factory.Create, TreeEnumerationOptions)
        {
            // 不下探 reparse 目錄，避免跟隨 junction 走出邊界或形成迴圈
            ShouldRecursePredicate = (ref FindEntry entry) =>
                (entry.Attributes & FileAttributes.ReparsePoint) == 0
                && (pruneDirectory is null || !pruneDirectory(entry.ToFullPath(), entry.FileName.ToString())),
        };

        foreach (FileSystemEntry entry in walk)
        {
            yield return entry;
        }
    }

    private sealed class BoundedEntryFactory(string directoryPath, int maxEntries, long maxTotalBytes, bool rejectReparse)
    {
        private int _entryCount;
        private long _totalBytes;

        public FileSystemEntry Create(ref FindEntry entry)
        {
            if (rejectReparse && (entry.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new SafeFileSystemException($"路徑不可為 reparse point： {entry.ToFullPath()}");
            }

            bool isDirectory = entry.IsDirectory;
            long length = isDirectory ? 0 : entry.Length;
            if (_entryCount >= maxEntries)
            {
                throw new SafeFileSystemException($"目錄項目數超過安全上限 ({maxEntries})：{directoryPath}", isLimitExceeded: true);
            }

            if (length > maxTotalBytes - _totalBytes)
            {
                throw new SafeFileSystemException($"目錄檔案總大小超過安全上限 ({maxTotalBytes} 位元組)：{directoryPath}", isLimitExceeded: true);
            }

            _entryCount++;
            _totalBytes += length;
            return new FileSystemEntry(entry.ToFullPath(), isDirectory, length, entry.LastWriteTimeUtc.UtcDateTime, entry.CreationTimeUtc.UtcDateTime);
        }
    }
    public static bool DeleteWithin(string baseDirectory, string targetPath)
    {
        try
        {
            string baseDir = ResolveStableDirectory(baseDirectory);
            string target = GetFullPath(targetPath);

            if (string.Equals(baseDir, target, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            if (!IsPathWithin(baseDir, target, strict: false))
            {
                return false;
            }

            if (IsReparsePoint(target))
            {
                return false;
            }

            if (File.Exists(target))
            {
                ClearReadOnlyAttribute(target);
                File.Delete(target);
                return true;
            }

            if (Directory.Exists(target))
            {
                RemoveReadOnlyAttributesRecursive(new DirectoryInfo(target));
                Directory.Delete(target, recursive: true);
                return true;
            }

            return false;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "受限路徑刪除失敗");
            return false;
        }
    }

    public static bool MoveWithin(string baseDirectory, string sourcePath, string destinationPath)
    {
        try
        {
            string baseDir = ResolveStableDirectory(baseDirectory);
            string source = GetFullPath(sourcePath);
            string destination = GetFullPath(destinationPath);

            if (string.Equals(baseDir, source, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(baseDir, destination, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            if (!IsPathWithin(baseDir, source, strict: false) ||
                !IsPathWithin(baseDir, destination, strict: false))
            {
                return false;
            }

            if (IsReparsePoint(source) || IsReparsePoint(destination))
            {
                return false;
            }

            string? destParent = Path.GetDirectoryName(destination);
            if (!string.IsNullOrEmpty(destParent) && !Directory.Exists(destParent))
            {
                ResolveStableDirectory(destParent, create: true);
            }

            bool isDirectory = Directory.Exists(source);
            if (!isDirectory && !File.Exists(source))
            {
                return false;
            }

            MoveCore(source, destination, isDirectory, overwrite: true);
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "受限路徑移動失敗");
            return false;
        }
    }

    /// <summary>嚴格在基準目錄內移動直接子項目（失敗時擲出例外）</summary>
    public static void MoveWithinStrict(string baseDirectory, string sourcePath, string destinationPath)
    {
        string baseDir = ResolveStableDirectory(baseDirectory);
        string source = GetFullPath(sourcePath);
        string destination = GetFullPath(destinationPath);

        if (string.Equals(baseDir, source, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(baseDir, destination, StringComparison.OrdinalIgnoreCase) ||
            !IsPathWithin(baseDir, source, strict: false) ||
            !IsPathWithin(baseDir, destination, strict: false))
        {
            throw new SafeFileSystemException("移動來源與目的地必須在基準目錄內");
        }

        string? sourceParent = Path.GetDirectoryName(source);
        string? destParent = Path.GetDirectoryName(destination);

        if (!string.Equals(sourceParent, baseDir, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(destParent, baseDir, StringComparison.OrdinalIgnoreCase))
        {
            throw new SafeFileSystemException("移動來源與目的地必須是基準目錄的直接子項目");
        }

        if (IsReparsePoint(source))
        {
            throw new SafeFileSystemException($"移動來源不可為 reparse point： {source}");
        }

        if (Path.Exists(destination))
        {
            throw new SafeFileSystemException($"移動目的地已存在： {destination}");
        }

        bool isDirectory = Directory.Exists(source);
        if (!isDirectory && !File.Exists(source))
        {
            throw new FileNotFoundException($"找不到移動來源項目： {source}");
        }

        MoveCore(source, destination, isDirectory, overwrite: false);
    }

    /// <summary>安全遞迴複製目錄樹，強制具備符號連結防護與受限走訪</summary>
    public static void CopyDirectoryTreeSafe(string source, string destination, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // 先完整具體化再複製，避免目的地位於來源內時走訪到剛複製的項目
        var entries = EnumerateBoundedTree(source, rejectReparse: true).ToList();
        foreach (var entry in entries)
        {
            cancellationToken.ThrowIfCancellationRequested();
            string rel = Path.GetRelativePath(source, entry.FullPath);
            string target = Path.Combine(destination, rel);

            if (entry.IsDirectory)
            {
                Directory.CreateDirectory(target);
            }
            else
            {
                string? dir = Path.GetDirectoryName(target);
                if (!string.IsNullOrEmpty(dir))
                {
                    Directory.CreateDirectory(dir);
                }
                File.Copy(entry.FullPath, target, overwrite: true);
            }
        }
    }

    private static void EnsureNoReparseAlongPath(string path, string? stopBoundary = null)
    {
        string? boundary = string.IsNullOrEmpty(stopBoundary) ? null : GetFullPath(stopBoundary);
        var current = new DirectoryInfo(GetFullPath(path));
        while (current is not null)
        {
            if (boundary is not null && string.Equals(current.FullName, boundary, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }

            if (current.Parent is null)
            {
                break;
            }

            if (IsExistingReparsePoint(current))
            {
                throw new SafeFileSystemException($"路徑不可包含 reparse point： {current.FullName}");
            }

            current = current.Parent;
        }
    }

    /// <summary>單次屬性讀取判斷既有目錄是否為 reparse point（不存在回傳 -1 屬性，不需額外 stat）；讀取失敗時退回逐步檢查以維持原語意</summary>
    private static bool IsExistingReparsePoint(DirectoryInfo directory)
    {
        try
        {
            FileAttributes attributes = directory.Attributes;
            return attributes != (FileAttributes)(-1) && (attributes & FileAttributes.ReparsePoint) != 0;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return directory.Exists && IsReparsePoint(directory.FullName);
        }
    }

    private static void EnsureNotReparsePoint(string path)
    {
        if (IsReparsePoint(path))
        {
            throw new SafeFileSystemException($"路徑不可為 reparse point： {path}");
        }
    }

    private static void ValidateLimits(int maxEntries, long maxTotalBytes)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(maxEntries);
        ArgumentOutOfRangeException.ThrowIfNegative(maxTotalBytes);
    }

    private static string GetFullPath(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return Path.GetFullPath(path);
    }

    public static byte[]? ReadRegularFile(string filePath, long maxBytes = 16 * 1024 * 1024)
    {
        // FileExists 經 ResolveStablePath 驗證整條路徑，reparse point 或超出邊界時回傳 false
        if (string.IsNullOrWhiteSpace(filePath) || !FileExists(filePath))
        {
            return null;
        }

        // 以單一串流檢查長度並讀取，避免檢查後檔案變大的競態
        using var stream = OpenRead(filePath);
        long length = stream.Length;
        if (length > maxBytes)
        {
            throw new IOException($"檔案大小超過安全上限 ({length} > {maxBytes})： {filePath}");
        }

        byte[] buffer = GC.AllocateUninitializedArray<byte>((int)length);
        stream.ReadExactly(buffer);
        if (stream.ReadByte() != -1)
        {
            throw new IOException($"檔案於讀取期間變更：{filePath}");
        }

        return buffer;
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
                if ((attributes & FileAttributes.ReadOnly) != 0)
                {
                    File.SetAttributes(path, attributes & ~FileAttributes.ReadOnly);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清除唯讀屬性失敗");
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

    private static void RemoveReadOnlyAttributesRecursive(DirectoryInfo directory)
    {
        try
        {
            ClearReadOnly(directory);

            // 預設會略過隱藏／系統項目，故僅排除 reparse point：不下探連結目錄，且含隱藏檔
            var options = new EnumerationOptions { RecurseSubdirectories = true, AttributesToSkip = FileAttributes.ReparsePoint };
            foreach (var info in directory.EnumerateFileSystemInfos("*", options))
            {
                ClearReadOnly(info);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "遞迴清除目錄唯讀屬性失敗");
        }
    }
}
