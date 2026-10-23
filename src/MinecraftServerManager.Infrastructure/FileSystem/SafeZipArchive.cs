using System.Diagnostics;
using System.Buffers;
using System.IO.Compression;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static class SafeZipArchive
{
    public const int DefaultMaxMembers = 100_000;
    public const long DefaultMaxMemberBytes = 2L * 1024 * 1024 * 1024; // 2 GB
    public const long DefaultMaxTotalBytes = 32L * 1024 * 1024 * 1024; // 32 GB
    public const long DefaultMaxArchiveBytes = DefaultMaxTotalBytes + (64L * 1024 * 1024);
    public const int DefaultMaxCompressionRatio = 200;

    public static void WriteArchive(
        string archivePath,
        Action<BoundedZipWriter> write,
        int maxMembers = DefaultMaxMembers,
        long maxTotalBytes = DefaultMaxTotalBytes,
        long maxMemberBytes = DefaultMaxMemberBytes)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(archivePath);
        ArgumentNullException.ThrowIfNull(write);
        ArgumentOutOfRangeException.ThrowIfNegative(maxTotalBytes);
        ArgumentOutOfRangeException.ThrowIfNegative(maxMemberBytes);

        using var writer = new BoundedZipWriter(archivePath, maxMembers, maxTotalBytes, maxMemberBytes);
        write(writer);
        writer.Complete();
    }

    public static ZipArchive OpenRead(
        string archivePath,
        int maxMembers = DefaultMaxMembers,
        long maxArchiveBytes = DefaultMaxArchiveBytes)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(archivePath);
        ArgumentOutOfRangeException.ThrowIfNegative(maxMembers);
        ArgumentOutOfRangeException.ThrowIfNegative(maxArchiveBytes);

        string path = SafeFileSystem.ResolveStablePath(archivePath);
        if (!SafeFileSystem.FileExists(path))
        {
            throw new FileNotFoundException("找不到 ZIP 檔案", path);
        }

        if (SafeFileSystem.GetFileLength(path) > maxArchiveBytes)
        {
            throw new SafeArchiveException("壓縮檔大小超過安全上限");
        }

        try
        {
            var archive = ZipFile.OpenRead(path);
            try
            {
                ValidateArchive(archive, maxMembers, DefaultMaxTotalBytes);
                return archive;
            }
            catch
            {
                archive.Dispose();
                throw;
            }
        }
        catch (InvalidDataException exception)
        {
            throw new SafeArchiveException("ZIP 檔案格式無效", exception);
        }
    }

    public static ZipArchive OpenRead(
        Stream stream,
        bool leaveOpen = false,
        int maxMembers = DefaultMaxMembers,
        long maxArchiveBytes = DefaultMaxArchiveBytes)
    {
        ArgumentNullException.ThrowIfNull(stream);
        ArgumentOutOfRangeException.ThrowIfNegative(maxMembers);
        ArgumentOutOfRangeException.ThrowIfNegative(maxArchiveBytes);
        if (!stream.CanRead || !stream.CanSeek || stream.Length > maxArchiveBytes)
        {
            throw new SafeArchiveException("壓縮檔串流無法讀取或超過安全大小上限");
        }

        ZipArchive archive;
        try
        {
            archive = new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen);
        }
        catch (InvalidDataException exception)
        {
            throw new SafeArchiveException("ZIP 檔案格式無效", exception);
        }

        try
        {
            ValidateArchive(archive, maxMembers, DefaultMaxTotalBytes);
            return archive;
        }
        catch
        {
            archive.Dispose();
            throw;
        }
    }

    private static void ValidateArchive(ZipArchive archive, int maxMembers, long maxTotalBytes)
    {
        if (archive.Entries.Count > maxMembers)
        {
            throw new SafeArchiveException("壓縮檔成員數量超過安全上限");
        }

        long totalBytes = 0;
        var paths = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        var parentPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            ValidateEntry(entry, DefaultMaxMemberBytes, DefaultMaxCompressionRatio);
            string relativePath = SanitizeMemberName(entry.FullName);
            ValidatePathCollision(entry, relativePath, paths, parentPaths);
            totalBytes = checked(totalBytes + entry.Length);
            if (totalBytes > maxTotalBytes)
            {
                throw new SafeArchiveException("壓縮檔解壓縮後大小超過安全上限");
            }
        }
    }

    public static void Extract(
        string archivePath,
        string destinationDirectory,
        Action<long, long>? progress = null,
        int maxMembers = DefaultMaxMembers,
        long maxTotalUncompressedBytes = DefaultMaxTotalBytes,
        long maxMemberUncompressedBytes = DefaultMaxMemberBytes,
        int maxCompressionRatio = DefaultMaxCompressionRatio,
        long maxArchiveBytes = DefaultMaxArchiveBytes)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(destinationDirectory);
        ArgumentOutOfRangeException.ThrowIfNegative(maxTotalUncompressedBytes);
        ArgumentOutOfRangeException.ThrowIfNegative(maxMemberUncompressedBytes);
        ArgumentOutOfRangeException.ThrowIfNegative(maxCompressionRatio);

        string destination = SafeFileSystem.ResolveStableDirectory(destinationDirectory, create: true);
        using var archive = OpenRead(archivePath, maxMembers, maxArchiveBytes);
        var members = PrepareMembers(
            archive,
            destination,
            maxTotalUncompressedBytes,
            maxMemberUncompressedBytes,
            maxCompressionRatio);

        long totalBytes = members.Sum(static member => member.Entry.Length);
        EnsureSufficientDiskSpace(destination, totalBytes);
        progress?.Invoke(0, totalBytes);
        long extractedBytes = 0;
        long lastReportTicks = Stopwatch.GetTimestamp();
        long lastReportBytes = 0;
        byte[] buffer = ArrayPool<byte>.Shared.Rent(81920);

        string destinationRoot = Path.GetFullPath(destination + Path.DirectorySeparatorChar);
        try
        {
            foreach (var member in members)
            {
                string target = Path.Combine(destination, member.RelativePath);
                string resolvedTarget = Path.GetFullPath(target);
                if (!resolvedTarget.StartsWith(destinationRoot, StringComparison.OrdinalIgnoreCase))
                {
                    throw new SafeArchiveException($"壓縮檔嘗試路徑穿越： {member.Entry.FullName}");
                }

                if (member.Entry.FullName.EndsWith('/'))
                {
                    SafeFileSystem.ResolveStableDirectory(resolvedTarget, create: true);
                    continue;
                }

                string safeTarget = SafeFileSystem.ResolveStablePath(resolvedTarget, createParent: true);
                long memberBytes = 0L;
                try
                {
                    using var source = member.Entry.Open();
                    using var output = new FileStream(
                        safeTarget,
                        FileMode.Create,
                        FileAccess.Write,
                        FileShare.None,
                        81920,
                        FileOptions.SequentialScan);

                    int read;
                    while ((read = source.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        memberBytes += read;
                        extractedBytes += read;
                        if (memberBytes > maxMemberUncompressedBytes || extractedBytes > maxTotalUncompressedBytes)
                        {
                            throw new SafeArchiveException("壓縮檔實際解壓縮大小超過安全上限");
                        }

                        output.Write(buffer, 0, read);

                        long nowTicks = Stopwatch.GetTimestamp();
                        if (Stopwatch.GetElapsedTime(lastReportTicks, nowTicks).TotalMilliseconds >= 100 ||
                            (totalBytes > 0 && (extractedBytes - lastReportBytes) >= (totalBytes / 100)))
                        {
                            lastReportTicks = nowTicks;
                            lastReportBytes = extractedBytes;
                            progress?.Invoke(extractedBytes, totalBytes);
                        }
                    }
                }
                catch (IOException exception) when (exception is not SafeArchiveException)
                {
                    throw new SafeArchiveException($"無法解壓縮檔案： {member.Entry.FullName}", exception);
                }
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }

        progress?.Invoke(totalBytes > 0 ? totalBytes : extractedBytes, totalBytes);
    }

    /// <summary>
    /// 檢查目標磁碟實際剩餘空間，只要剩餘空間充足即允許解壓縮（保留 5% 或 512 MB 安全水位）。
    /// </summary>
    private static void EnsureSufficientDiskSpace(string destination, long requiredBytes)
    {
        if (requiredBytes <= 0)
        {
            return;
        }

        try
        {
            string? root = Path.GetPathRoot(Path.GetFullPath(destination));
            if (string.IsNullOrWhiteSpace(root))
            {
                return;
            }

            long? availableFreeSpace = SafeFileSystem.GetAvailableFreeSpace(destination);
            if (!availableFreeSpace.HasValue)
            {
                return;
            }

            long headroom = Math.Min(512L * 1024 * 1024, requiredBytes / 20);
            if (availableFreeSpace.Value < requiredBytes + headroom)
            {
                throw new SafeArchiveException(
                    $"目標磁碟 {root} 剩餘空間不足：需要約 {UnitFormatter.FormatBytes(requiredBytes)}，實際可用 {UnitFormatter.FormatBytes(availableFreeSpace.Value)}");
            }
        }
        catch (Exception exception) when (exception is ArgumentException or IOException or UnauthorizedAccessException)
        {
            // 無法判定磁碟資訊時不阻斷流程，交由實際寫入階段回報錯誤
        }
    }

    private static List<PreparedMember> PrepareMembers(
        ZipArchive archive,
        string destination,
        long maxTotalUncompressedBytes,
        long maxMemberUncompressedBytes,
        int maxCompressionRatio)
    {
        var members = new List<PreparedMember>(archive.Entries.Count);
        var paths = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        var parentPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        long totalBytes = 0;

        foreach (var entry in archive.Entries)
        {
            ValidateEntry(entry, maxMemberUncompressedBytes, maxCompressionRatio);
            string relativePath = SanitizeMemberName(entry.FullName);
            string target = Path.Combine(destination, relativePath);
            if (!SafeFileSystem.IsPathWithin(destination, target, strict: false))
            {
                throw new SafeArchiveException($"壓縮檔嘗試路徑穿越： {entry.FullName}");
            }

            ValidatePathCollision(entry, relativePath, paths, parentPaths);
            totalBytes += entry.Length;
            if (totalBytes > maxTotalUncompressedBytes)
            {
                throw new SafeArchiveException("壓縮檔解壓縮後大小超過安全上限");
            }

            members.Add(new PreparedMember(entry, relativePath));
        }

        return members;
    }

    private static void ValidateEntry(ZipArchiveEntry entry, long maxMemberBytes, int maxCompressionRatio)
    {
        if (IsSymlink(entry))
        {
            throw new SafeArchiveException($"壓縮檔包含不支援的符號連結： {entry.FullName}");
        }

        if (entry.Length > maxMemberBytes)
        {
            throw new SafeArchiveException($"壓縮檔成員過大： {entry.FullName}");
        }

        if (entry.Length > 0)
        {
            if (entry.CompressedLength <= 0 || entry.Length / (double)entry.CompressedLength > maxCompressionRatio)
            {
                throw new SafeArchiveException($"壓縮檔成員壓縮比例過高： {entry.FullName}");
            }
        }
    }

    private static string SanitizeMemberName(string memberName)
    {
        string normalized = memberName.Replace('\\', '/');
        if (string.IsNullOrEmpty(normalized) || normalized.StartsWith('/'))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        if (Path.IsPathRooted(normalized) || normalized.Contains(':'))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        string trimmed = normalized.TrimEnd('/');
        if (string.IsNullOrEmpty(trimmed))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        string[] parts = trimmed.Split('/', StringSplitOptions.None);
        if (parts.Any(static part => string.IsNullOrEmpty(part) || part is "." or ".." || IsReservedWindowsName(part)))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        return Path.Combine(parts);
    }

    private static void ValidatePathCollision(
        ZipArchiveEntry entry,
        string relativePath,
        Dictionary<string, bool> paths,
        HashSet<string> parentPaths)
    {
        string[] parts = relativePath.Split(Path.DirectorySeparatorChar);
        string key = relativePath;
        bool isDirectory = entry.FullName.EndsWith('/');
        if (paths.TryGetValue(key, out bool existingIsDirectory))
        {
            if (isDirectory && existingIsDirectory)
            {
                return;
            }
            throw new SafeArchiveException($"壓縮檔包含重複或路徑衝突： {entry.FullName}");
        }
        if (!isDirectory && parentPaths.Contains(key))
        {
            throw new SafeArchiveException($"壓縮檔包含重複或路徑衝突： {entry.FullName}");
        }

        for (int index = 1; index < parts.Length; index++)
        {
            string parentKey = string.Join(Path.DirectorySeparatorChar, parts[..index]);
            if (paths.TryGetValue(parentKey, out bool parentIsDirectory) && !parentIsDirectory)
            {
                throw new SafeArchiveException($"壓縮檔包含檔案／目錄路徑衝突： {entry.FullName}");
            }

            parentPaths.Add(parentKey);
        }

        paths[key] = isDirectory;
    }

    private static bool IsSymlink(ZipArchiveEntry entry)
    {
        int unixMode = (entry.ExternalAttributes >> 16) & 0xF000;
        return unixMode == 0xA000;
    }

    private static bool IsReservedWindowsName(string value)
    {
        string name = value.TrimEnd(' ', '.');
        string baseName = name.Contains('.')
            ? name[..name.IndexOf('.')]
            : name;
        return baseName.Equals("CON", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("PRN", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("AUX", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("NUL", StringComparison.OrdinalIgnoreCase)
            || (baseName.Length == 4 && (baseName.StartsWith("COM", StringComparison.OrdinalIgnoreCase)
                || baseName.StartsWith("LPT", StringComparison.OrdinalIgnoreCase)) && char.IsDigit(baseName[3]));
    }

    public sealed class BoundedZipWriter : IDisposable
    {
        private readonly string _targetPath;
        private readonly string _temporaryPath;
        private readonly FileStream _stream;
        private readonly ZipArchive _archive;
        private readonly int _maxMembers;
        private readonly long _maxTotalBytes;
        private readonly long _maxMemberBytes;
        private readonly HashSet<string> _paths = new(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _parentPaths = new(StringComparer.OrdinalIgnoreCase);
        private long _totalBytes;
        private bool _completed;
        private bool _disposed;

        internal BoundedZipWriter(string targetPath, int maxMembers, long maxTotalBytes, long maxMemberBytes)
        {
            ArgumentOutOfRangeException.ThrowIfNegative(maxMembers);
            _targetPath = SafeFileSystem.ResolveStablePath(targetPath, createParent: true);
            _temporaryPath = _targetPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
            _maxMembers = maxMembers;
            _maxTotalBytes = maxTotalBytes;
            _maxMemberBytes = maxMemberBytes;
            _stream = new FileStream(
                _temporaryPath,
                FileMode.CreateNew,
                FileAccess.ReadWrite,
                FileShare.None,
                1024 * 1024,
                FileOptions.WriteThrough);
            _archive = new ZipArchive(_stream, ZipArchiveMode.Create, leaveOpen: true);
        }

        public void SetComment(string comment)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            _archive.Comment = comment;
        }

        public void WriteBytes(string memberName, ReadOnlySpan<byte> content)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            string normalized = PrepareMember(memberName, content.Length);
            var entry = _archive.CreateEntry(normalized, CompressionLevel.Optimal);
            using var target = entry.Open();
            target.Write(content);
        }

        public long WriteFile(string memberName, string sourcePath)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            string source = SafeFileSystem.ResolveStablePath(sourcePath);
            if (!SafeFileSystem.FileExists(source))
            {
                throw new FileNotFoundException("找不到要壓縮的檔案", source);
            }

            long fileLength = SafeFileSystem.GetFileLength(source);
            string normalized = PrepareMember(memberName, fileLength);
            var entry = _archive.CreateEntry(normalized, CompressionLevel.Optimal);
            using var input = SafeFileSystem.OpenRead(source, FileShare.Read);
            using var output = entry.Open();
            byte[] buffer = ArrayPool<byte>.Shared.Rent(81920);
            long copied = 0L;
            try
            {
                while (copied < fileLength)
                {
                    long remaining = fileLength - copied;
                    int requested = (int)Math.Min(buffer.Length, remaining + 1);
                    int read = input.Read(buffer, 0, requested);
                    if (read == 0)
                    {
                        break;
                    }

                    copied += read;
                    if (copied > fileLength)
                    {
                        throw new SafeArchiveException($"壓縮來源檔案在讀取期間成長： {source}");
                    }

                    output.Write(buffer, 0, read);
                }

                if (copied != fileLength)
                {
                    throw new SafeArchiveException($"壓縮來源檔案在讀取期間縮短： {source}");
                }
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(buffer);
            }

            return copied;
        }

        public void Complete()
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            _archive.Dispose();
            _stream.Flush(true);
            _stream.Dispose();
            if (!AtomicFileWriter.ReplaceFile(_temporaryPath, _targetPath))
            {
                throw new SafeArchiveException($"無法完成 ZIP 原子替換： {_targetPath}");
            }

            _completed = true;
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            if (!_completed)
            {
                _archive.Dispose();
                _stream.Dispose();
                TryDeleteTemporaryFile();
            }
        }

        private string PrepareMember(string memberName, long size)
        {
            if (size < 0 || size > _maxMemberBytes)
            {
                throw new SafeArchiveException($"壓縮檔成員過大： {memberName}");
            }

            if (_paths.Count >= _maxMembers || _totalBytes > _maxTotalBytes - size)
            {
                throw new SafeArchiveException("壓縮檔輸出超過安全上限");
            }

            string normalized = SanitizeMemberName(memberName);
            string[] parts = normalized.Split(Path.DirectorySeparatorChar);
            string key = normalized;
            if (_paths.Contains(key) || _parentPaths.Contains(key))
            {
                throw new SafeArchiveException($"壓縮檔包含重複或路徑衝突： {memberName}");
            }

            for (int index = 1; index < parts.Length; index++)
            {
                string parentKey = string.Join(Path.DirectorySeparatorChar, parts[..index]);
                if (_paths.Contains(parentKey))
                {
                    throw new SafeArchiveException($"壓縮檔包含檔案／目錄路徑衝突： {memberName}");
                }

                _parentPaths.Add(parentKey);
            }

            _paths.Add(key);
            _totalBytes += size;
            return normalized;
        }

        private void TryDeleteTemporaryFile()
        {
            try
            {
                SafeFileSystem.DeleteFile(_temporaryPath);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
            }
        }
    }

    private sealed record PreparedMember(ZipArchiveEntry Entry, string RelativePath);
}
