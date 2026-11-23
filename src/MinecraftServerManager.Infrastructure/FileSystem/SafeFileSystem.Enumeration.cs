using System.IO.Enumeration;
using FindEntry = System.IO.Enumeration.FileSystemEntry;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static partial class SafeFileSystem
{
    private static IEnumerable<FileSystemEntry> EnumerateEntries(string directoryPath, SearchOption searchOption) => searchOption switch
    {
        SearchOption.TopDirectoryOnly => EnumerateBoundedDirectory(directoryPath, DefaultMaxEntries, DefaultMaxTotalBytes, rejectReparse: true),
        SearchOption.AllDirectories => EnumerateBoundedTree(directoryPath),
        _ => throw new ArgumentOutOfRangeException(nameof(searchOption)),
    };

    private static bool MatchesPattern(FileSystemEntry entry, bool isDirectory, string searchPattern) =>
        entry.IsDirectory == isDirectory &&
        FileSystemName.MatchesSimpleExpression(searchPattern, Path.GetFileName(entry.FullPath.AsSpan()), ignoreCase: true);

    /// <summary>以受限走訪列舉目錄中的檔案</summary>
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

    /// <summary>目錄中是否有符合條件的檔案（找到即停）</summary>
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

    /// <summary>目錄是否沒有任何項目；延遲列舉，遇到第一筆即傳回，不建立完整清單</summary>
    public static bool IsDirectoryEmpty(string directoryPath) =>
        !new DirectoryInfo(ResolveStableDirectory(directoryPath)).EnumerateFileSystemInfos().Any();

    public static IReadOnlyList<string> EnumerateDirectories(
        string directoryPath,
        string searchPattern = "*",
        SearchOption searchOption = SearchOption.TopDirectoryOnly)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(searchPattern);
        return [.. EnumerateEntries(directoryPath, searchOption)
            .Where(entry => MatchesPattern(entry, isDirectory: true, searchPattern))
            .Select(static entry => entry.FullPath)];
    }

    /// <summary>列舉單一目錄，套用項目數、總大小與 reparse point 上限</summary>
    public static IReadOnlyList<FileSystemEntry> ListBoundedDirectory(
        string directoryPath,
        int maxEntries = DefaultMaxEntries,
        long maxTotalBytes = DefaultMaxTotalBytes,
        bool rejectReparse = true) =>
        [.. EnumerateBoundedDirectory(directoryPath, maxEntries, maxTotalBytes, rejectReparse)];

    /// <summary>延遲列舉單一目錄，套用與 <see cref="ListBoundedDirectory"/> 相同的上限</summary>
    private static FileSystemEnumerable<FileSystemEntry> EnumerateBoundedDirectory(
        string directoryPath,
        int maxEntries,
        long maxTotalBytes,
        bool rejectReparse)
    {
        ValidateLimits(maxEntries, maxTotalBytes);
        string directory = ResolveStableDirectory(directoryPath);
        var factory = new BoundedEntryFactory(directoryPath, maxEntries, maxTotalBytes, rejectReparse);
        return new FileSystemEnumerable<FileSystemEntry>(directory, factory.Create, FlatEnumerationOptions);
    }

    /// <summary>延遲列舉目錄樹，支援剪枝與總量上限</summary>
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
        return new FileSystemEnumerable<FileSystemEntry>(root, factory.Create, TreeEnumerationOptions)
        {
            // 不下探 reparse 目錄，避免跟隨 junction 走出邊界或形成迴圈
            ShouldRecursePredicate = (ref FindEntry entry) =>
                (entry.Attributes & FileAttributes.ReparsePoint) == 0
                && (pruneDirectory is null || !pruneDirectory(entry.ToFullPath(), entry.FileName.ToString())),
        };
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

    private static void ValidateLimits(int maxEntries, long maxTotalBytes)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(maxEntries);
        ArgumentOutOfRangeException.ThrowIfNegative(maxTotalBytes);
    }
}
