using MinecraftServerManager.Infrastructure.Logging;
using System.Text;
using MinecraftServerManager.Infrastructure.Utilities;

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
    DateTime LastWriteTime,
    DateTime LastWriteTimeUtc,
    DateTime CreationTimeUtc,
    FileAttributes Attributes);

public static class SafeFileSystem
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("SafeFileSystem");
    public const int DefaultMaxEntries = 100_000;
    public const long DefaultMaxTotalBytes = 128L * 1024 * 1024 * 1024;

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
        string parent = Path.GetDirectoryName(fullPath)
            ?? throw new SafeFileSystemException($"找不到路徑父資料夾： {fullPath}");
        ResolveStableDirectory(parent, createParent);
        if (File.Exists(fullPath) || Directory.Exists(fullPath))
        {
            EnsureNotReparsePoint(fullPath);
        }

        return fullPath;
    }

    /// <summary>
    /// 驗證一般檔案路徑後檢查檔案是否存在。
    /// </summary>
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

    /// <summary>
    /// 驗證目錄路徑後檢查目錄是否存在。
    /// </summary>
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

    /// <summary>
    /// 建立經過路徑穩定性檢查的目錄。
    /// </summary>
    public static string CreateDirectory(string path) => ResolveStableDirectory(path, create: true);

    /// <summary>
    /// 以受限走訪列舉目錄中的檔案。
    /// </summary>
    public static IReadOnlyList<string> EnumerateFiles(
        string directoryPath,
        string searchPattern,
        SearchOption searchOption = SearchOption.TopDirectoryOnly)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(searchPattern);
        IReadOnlyList<FileSystemEntry> entries = searchOption switch
        {
            SearchOption.TopDirectoryOnly => ListBoundedDirectory(directoryPath),
            SearchOption.AllDirectories => WalkBoundedTree(directoryPath),
            _ => throw new ArgumentOutOfRangeException(nameof(searchOption)),
        };

        return [.. entries
            .Where(entry => !entry.IsDirectory &&
                System.IO.Enumeration.FileSystemName.MatchesSimpleExpression(
                    searchPattern,
                    Path.GetFileName(entry.FullPath),
                    ignoreCase: true))
            .Select(static entry => entry.FullPath)];
    }

    /// <summary>
    /// 取得經過路徑穩定性檢查之目錄的最後修改時間。
    /// </summary>
    public static DateTime GetDirectoryLastWriteTime(string path) =>
        Directory.GetLastWriteTime(ResolveStableDirectory(path));

    /// <summary>
    /// 取得指定路徑所在磁碟之可用剩餘空間位元組數；若無法取得或路徑無效則傳回 null。
    /// </summary>
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
        }

        return null;
    }

    public static long GetFileLength(string path) => new FileInfo(ResolveStablePath(path)).Length;

    public static DateTime GetFileLastWriteTime(string path) => File.GetLastWriteTime(ResolveStablePath(path));

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
            info.LastWriteTime,
            info.LastWriteTimeUtc,
            info.CreationTimeUtc,
            info.Attributes);
    }

    public static string? ResolveFileLinkTarget(string path)
    {
        string stablePath = GetFullPath(path);
        var info = new FileInfo(stablePath);
        return info.ResolveLinkTarget(returnFinalTarget: true)?.FullName;
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
        IReadOnlyList<FileSystemEntry> entries = searchOption switch
        {
            SearchOption.TopDirectoryOnly => ListBoundedDirectory(directoryPath),
            SearchOption.AllDirectories => WalkBoundedTree(directoryPath),
            _ => throw new ArgumentOutOfRangeException(nameof(searchOption)),
        };

        return [.. entries
            .Where(entry => entry.IsDirectory &&
                System.IO.Enumeration.FileSystemName.MatchesSimpleExpression(
                    searchPattern,
                    Path.GetFileName(entry.FullPath),
                    ignoreCase: true))
            .Select(static entry => entry.FullPath)];
    }

    public static IReadOnlyList<string> EnumerateFileSystemEntries(string directoryPath) =>
        [.. ListBoundedDirectory(directoryPath, rejectReparse: false).Select(static entry => entry.FullPath)];

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

    public static string ReadAllText(string filePath, Encoding? encoding = null, long maxBytes = 16L * 1024 * 1024)
    {
        byte[] bytes = ReadRegularFile(filePath, maxBytes)
            ?? throw new FileNotFoundException("找不到或無法安全讀取檔案", filePath);
        using var reader = new StreamReader(new MemoryStream(bytes, writable: false), encoding ?? Encoding.UTF8);
        return reader.ReadToEnd();
    }

    public static string[] ReadAllLines(string filePath, Encoding? encoding = null, long maxBytes = 16L * 1024 * 1024)
    {
        if (GetFileLength(filePath) > maxBytes)
        {
            throw new IOException($"檔案大小超過安全上限：{filePath}");
        }

        using var reader = new StreamReader(OpenRead(filePath), encoding ?? Encoding.UTF8);
        var lines = new List<string>();
        while (reader.ReadLine() is { } line)
        {
            lines.Add(line);
        }

        return [.. lines];
    }

    public static Task<string> ReadAllTextAsync(
        string filePath,
        Encoding? encoding = null,
        long maxBytes = 16L * 1024 * 1024,
        CancellationToken cancellationToken = default) =>
        Task.Run(() => ReadAllText(filePath, encoding, maxBytes), cancellationToken);

    public static Task WriteAllBytesAsync(
        string filePath,
        ReadOnlyMemory<byte> content,
        CancellationToken cancellationToken = default) =>
        Task.Run(() => WriteAllBytes(filePath, content.Span), cancellationToken);

    public static Task WriteAllTextAsync(
        string filePath,
        string content,
        Encoding? encoding = null,
        CancellationToken cancellationToken = default) =>
        Task.Run(() => WriteAllText(filePath, content, encoding), cancellationToken);

    public static void WriteAllBytes(string filePath, ReadOnlySpan<byte> content)
    {
        if (!AtomicFileWriter.WriteBytes(filePath, content))
        {
            throw new IOException($"無法安全寫入檔案：{filePath}");
        }
    }

    public static void WriteAllText(string filePath, string content, Encoding? encoding = null)
    {
        ArgumentNullException.ThrowIfNull(content);
        Encoding textEncoding = encoding ?? new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        byte[] preamble = textEncoding.GetPreamble();
        byte[] body = textEncoding.GetBytes(content);
        byte[] payload = new byte[preamble.Length + body.Length];
        preamble.CopyTo(payload, 0);
        body.CopyTo(payload, preamble.Length);
        WriteAllBytes(filePath, payload);
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

    public static void MovePath(string sourcePath, string destinationPath, bool overwrite = false)
    {
        string source = ResolveStablePath(sourcePath);
        bool isDirectory = Directory.Exists(source);
        string destination = ResolveStablePath(destinationPath, createParent: true);

        if (IsReparsePoint(source) || IsReparsePoint(destination))
        {
            throw new SafeFileSystemException("移動來源與目的地不得為 reparse point");
        }

        if (isDirectory)
        {
            if (overwrite && Directory.Exists(destination))
            {
                DeleteDirectory(destination, recursive: true);
            }

            Directory.Move(source, destination);
            return;
        }

        File.Move(source, destination, overwrite);
    }

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
            string full = GetFullPath(path);
            if (!File.Exists(full) && !Directory.Exists(full))
            {
                return false;
            }

            return (File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0;
        }
        catch (FileNotFoundException)
        {
            return false;
        }
        catch (DirectoryNotFoundException)
        {
            return false;
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
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
                || (!relative.Equals("..", StringComparison.Ordinal)
                    && !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal));
            if (!within)
            {
                return false;
            }

            if (strict && !File.Exists(target) && !Directory.Exists(target))
            {
                return false;
            }

            string? existingParent = File.Exists(target) || Directory.Exists(target)
                ? target
                : Path.GetDirectoryName(target);
            if (existingParent is null)
            {
                return false;
            }

            EnsureNoReparseAlongPath(existingParent, basePath);
            return true;
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
    }

    public static IReadOnlyList<FileSystemEntry> ListBoundedDirectory(
        string directoryPath,
        int maxEntries = DefaultMaxEntries,
        long maxTotalBytes = DefaultMaxTotalBytes,
        bool rejectReparse = true)
    {
        ValidateLimits(maxEntries, maxTotalBytes);
        string directory = ResolveStableDirectory(directoryPath);
        var entries = new List<FileSystemEntry>();
        long totalBytes = 0;

        foreach (var info in new DirectoryInfo(directory).EnumerateFileSystemInfos())
        {
            AddEntry(info, entries, ref totalBytes, maxEntries, maxTotalBytes, rejectReparse);
        }

        return entries;
    }

    /// <summary>
    /// 以串流延遲列舉（Streaming）方式走訪目錄樹，支援剪枝下探謂詞（Prune Predicate）與總量上限安全防護。
    /// </summary>
    /// <param name="directoryPath">欲走訪之根目錄路徑</param>
    /// <param name="maxEntries">允許之最大項目數（預設 100,000）</param>
    /// <param name="maxTotalBytes">允許之最大檔案總位元組數（預設 128 GB）</param>
    /// <param name="rejectReparse">是否拒絕重解析點（符號連結/連接點，預設 true）</param>
    /// <param name="pruneDirectory">剪枝謂詞：傳入即將下探之目錄完整路徑與目錄名稱，若回傳 true 則略過該目錄不向下遞迴</param>
    /// <returns>檔案系統項目之延遲列舉集合</returns>
    public static IEnumerable<FileSystemEntry> EnumerateBoundedTree(
        string directoryPath,
        int maxEntries = DefaultMaxEntries,
        long maxTotalBytes = DefaultMaxTotalBytes,
        bool rejectReparse = true,
        Func<string, string, bool>? pruneDirectory = null)
    {
        ValidateLimits(maxEntries, maxTotalBytes);
        string root = ResolveStableDirectory(directoryPath);
        var pending = new Queue<string>([root]);
        int entryCount = 0;
        long totalBytes = 0;

        while (pending.Count > 0)
        {
            string current = pending.Dequeue();
            var dirInfo = new DirectoryInfo(current);
            if (!dirInfo.Exists)
            {
                continue;
            }

            foreach (var info in dirInfo.EnumerateFileSystemInfos())
            {
                bool isReparsePoint = IsReparsePoint(info.FullName);
                if (isReparsePoint && rejectReparse)
                {
                    throw new SafeFileSystemException($"路徑不可為 reparse point： {info.FullName}");
                }

                bool isDirectory = info is DirectoryInfo;
                long length = isDirectory ? 0 : ((FileInfo)info).Length;

                if (entryCount >= maxEntries)
                {
                    throw new SafeFileSystemException($"目錄項目數超過安全上限 ({maxEntries})：{directoryPath}");
                }

                if (length > maxTotalBytes - totalBytes)
                {
                    throw new SafeFileSystemException($"目錄檔案總大小超過安全上限 ({maxTotalBytes} 位元組)：{directoryPath}");
                }

                entryCount++;
                totalBytes += length;

                var entry = new FileSystemEntry(info.FullName, isDirectory, length, info.LastWriteTimeUtc, info.CreationTimeUtc);

                if (isDirectory)
                {
                    bool shouldPrune = pruneDirectory is not null && pruneDirectory(info.FullName, info.Name);
                    if (!shouldPrune)
                    {
                        pending.Enqueue(info.FullName);
                    }
                }

                yield return entry;
            }
        }
    }

    public static IReadOnlyList<FileSystemEntry> WalkBoundedTree(
        string directoryPath,
        int maxEntries = DefaultMaxEntries,
        long maxTotalBytes = DefaultMaxTotalBytes,
        bool rejectReparse = true,
        Func<string, string, bool>? pruneDirectory = null) => [.. EnumerateBoundedTree(directoryPath, maxEntries, maxTotalBytes, rejectReparse, pruneDirectory)];

    private static void AddEntry(
        FileSystemInfo info,
        List<FileSystemEntry> entries,
        ref long totalBytes,
        int maxEntries,
        long maxTotalBytes,
        bool rejectReparse)
    {
        bool isReparsePoint = IsReparsePoint(info.FullName);
        if (isReparsePoint && rejectReparse)
        {
            throw new SafeFileSystemException($"路徑不可為 reparse point： {info.FullName}");
        }

        bool isDirectory = info is DirectoryInfo;
        long length = isDirectory ? 0 : ((FileInfo)info).Length;
        if (entries.Count >= maxEntries)
        {
            throw new SafeFileSystemException("目錄項目數超過安全上限");
        }

        if (length > maxTotalBytes - totalBytes)
        {
            throw new SafeFileSystemException("目錄檔案總大小超過安全上限");
        }

        totalBytes += length;
        entries.Add(new FileSystemEntry(info.FullName, isDirectory, length, info.LastWriteTimeUtc, info.CreationTimeUtc));
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
                var fileInfo = new FileInfo(target);
                if (fileInfo.IsReadOnly)
                {
                    fileInfo.IsReadOnly = false;
                }
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
        catch
        {
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

            if (File.Exists(source))
            {
                File.Move(source, destination, overwrite: true);
                return true;
            }

            if (Directory.Exists(source))
            {
                Directory.Move(source, destination);
                return true;
            }

            return false;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// 嚴格在基準目錄內移動直接子項目（失敗時擲出例外）
    /// </summary>
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

        if (File.Exists(destination) || Directory.Exists(destination))
        {
            throw new SafeFileSystemException($"移動目的地已存在： {destination}");
        }

        if (File.Exists(source))
        {
            File.Move(source, destination);
            return;
        }

        if (Directory.Exists(source))
        {
            Directory.Move(source, destination);
            return;
        }

        throw new FileNotFoundException($"找不到移動來源項目： {source}");
    }

    /// <summary>
    /// 僅複製同一基準目錄內的一般檔案或目錄樹
    /// </summary>
    public static bool CopyWithin(string baseDirectory, string sourcePath, string destinationPath, bool overwrite = false)
    {
        try
        {
            string baseDir = ResolveStableDirectory(baseDirectory);
            string source = GetFullPath(sourcePath);
            string destination = GetFullPath(destinationPath);

            if (string.Equals(baseDir, source, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(baseDir, destination, StringComparison.OrdinalIgnoreCase) ||
                !IsPathWithin(baseDir, source, strict: false) ||
                !IsPathWithin(baseDir, destination, strict: false))
            {
                return false;
            }

            if (IsReparsePoint(source) || IsReparsePoint(destination))
            {
                return false;
            }

            if (File.Exists(source))
            {
                string? destParent = Path.GetDirectoryName(destination);
                if (!string.IsNullOrEmpty(destParent) && !Directory.Exists(destParent))
                {
                    ResolveStableDirectory(destParent, create: true);
                }

                File.Copy(source, destination, overwrite);
                return true;
            }

            if (Directory.Exists(source))
            {
                if (!Directory.Exists(destination))
                {
                    Directory.CreateDirectory(destination);
                }

                var entries = WalkBoundedTree(source);
                foreach (var entry in entries)
                {
                    string rel = Path.GetRelativePath(source, entry.FullPath);
                    string targetChild = Path.Combine(destination, rel);

                    if (entry.IsDirectory)
                    {
                        if (!Directory.Exists(targetChild))
                        {
                            Directory.CreateDirectory(targetChild);
                        }
                    }
                    else
                    {
                        string? targetDir = Path.GetDirectoryName(targetChild);
                        if (!string.IsNullOrEmpty(targetDir) && !Directory.Exists(targetDir))
                        {
                            Directory.CreateDirectory(targetDir);
                        }

                        File.Copy(entry.FullPath, targetChild, overwrite);
                    }
                }

                return true;
            }

            return false;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// 安全遞迴複製目錄樹，強制具備符號連結防護與受限走訪
    /// </summary>
    public static void CopyDirectoryTreeSafe(string source, string destination)
    {
        var entries = WalkBoundedTree(source, rejectReparse: true);
        foreach (var entry in entries)
        {
            string rel = Path.GetRelativePath(source, entry.FullPath);
            string target = Path.Combine(destination, rel);

            if (entry.IsDirectory)
            {
                Directory.CreateDirectory(target);
            }
            else
            {
                string? dir = Path.GetDirectoryName(target);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
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

            if (current.Exists && IsReparsePoint(current.FullName))
            {
                throw new SafeFileSystemException($"路徑不可包含 reparse point： {current.FullName}");
            }

            current = current.Parent;
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
        if (maxEntries < 0)
        {
            ArgumentOutOfRangeException.ThrowIfNegative(maxEntries);
        }

        if (maxTotalBytes < 0)
        {
            ArgumentOutOfRangeException.ThrowIfNegative(maxTotalBytes);
        }
    }

    private static string GetFullPath(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return Path.GetFullPath(path);
    }

    public static byte[]? ReadRegularFile(string filePath, long maxBytes = 16 * 1024 * 1024)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath) || IsReparsePoint(filePath))
        {
            return null;
        }

        var fileInfo = new FileInfo(filePath);
        if (fileInfo.Length > maxBytes)
        {
            throw new IOException($"檔案大小超過安全上限 ({fileInfo.Length} > {maxBytes})： {filePath}");
        }

        return File.ReadAllBytes(filePath);
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
            if (File.Exists(path) || Directory.Exists(path))
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
            Logger.Warning("清除唯讀屬性失敗: {0}", ex.Message);
        }
    }

    private static void RemoveReadOnlyAttributesRecursive(DirectoryInfo directory)
    {
        try
        {
            if (directory.Attributes.HasFlag(FileAttributes.ReadOnly))
            {
                directory.Attributes &= ~FileAttributes.ReadOnly;
            }

            foreach (var file in directory.EnumerateFiles())
            {
                if (file.IsReadOnly)
                {
                    file.IsReadOnly = false;
                }
            }

            foreach (var subDir in directory.EnumerateDirectories())
            {
                if (!IsReparsePoint(subDir.FullName))
                {
                    RemoveReadOnlyAttributesRecursive(subDir);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("遞迴清除目錄唯讀屬性失敗: {0}", ex.Message);
        }
    }
}
