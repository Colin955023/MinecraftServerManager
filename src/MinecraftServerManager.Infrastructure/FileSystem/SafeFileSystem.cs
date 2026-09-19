namespace MinecraftServerManager.Infrastructure.FileSystem;

public sealed record FileSystemEntry(string FullPath, bool IsDirectory, long Length);

public static class SafeFileSystem
{
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

    public static bool IsReparsePoint(string path)
    {
        try
        {
            return (File.GetAttributes(GetFullPath(path)) & FileAttributes.ReparsePoint) != 0;
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
            return true;
        }
        catch (UnauthorizedAccessException)
        {
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

            EnsureNoReparseAlongPath(existingParent);
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

    public static IReadOnlyList<FileSystemEntry> WalkBoundedTree(
        string directoryPath,
        int maxEntries = DefaultMaxEntries,
        long maxTotalBytes = DefaultMaxTotalBytes,
        bool rejectReparse = true)
    {
        ValidateLimits(maxEntries, maxTotalBytes);
        string root = ResolveStableDirectory(directoryPath);
        var entries = new List<FileSystemEntry>();
        var pending = new Queue<string>([root]);
        long totalBytes = 0;

        while (pending.Count > 0)
        {
            string current = pending.Dequeue();
            foreach (var info in new DirectoryInfo(current).EnumerateFileSystemInfos())
            {
                AddEntry(info, entries, ref totalBytes, maxEntries, maxTotalBytes, rejectReparse);
                if (info is DirectoryInfo)
                {
                    pending.Enqueue(info.FullName);
                }
            }
        }

        return entries;
    }

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
        entries.Add(new FileSystemEntry(info.FullName, isDirectory, length));
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
                File.Delete(target);
                return true;
            }

            if (Directory.Exists(target))
            {
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
    /// 嚴格在基準目錄內移動直接子項目（失敗時拋出例外）
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

    private static void EnsureNoReparseAlongPath(string path)
    {
        var current = new DirectoryInfo(GetFullPath(path));
        while (current is not null)
        {
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
}
