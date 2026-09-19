using System.IO.Compression;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static class SafeZipArchive
{
    public const int DefaultMaxMembers = 100_000;
    public const long DefaultMaxMemberBytes = 512L * 1024 * 1024;
    public const long DefaultMaxTotalBytes = 2L * 1024 * 1024 * 1024;
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
        var fileInfo = new FileInfo(path);
        if (!fileInfo.Exists)
        {
            throw new FileNotFoundException("找不到 ZIP 檔案", path);
        }

        if (fileInfo.Length > maxArchiveBytes)
        {
            throw new SafeArchiveException("壓縮檔大小超過安全上限");
        }

        try
        {
            var archive = ZipFile.OpenRead(path);
            if (archive.Entries.Count > maxMembers)
            {
                archive.Dispose();
                throw new SafeArchiveException("壓縮檔成員數量超過安全上限");
            }

            return archive;
        }
        catch (InvalidDataException exception)
        {
            throw new SafeArchiveException("ZIP 檔案格式無效", exception);
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
        progress?.Invoke(0, totalBytes);
        long extractedBytes = 0;

        foreach (var member in members)
        {
            string target = Path.Combine(destination, member.RelativePath);
            if (member.Entry.FullName.EndsWith('/'))
            {
                SafeFileSystem.ResolveStableDirectory(target, create: true);
                continue;
            }

            string safeTarget = SafeFileSystem.ResolveStablePath(target, createParent: true);
            long memberBytes = 0L;
            try
            {
                using var source = member.Entry.Open();
                using var output = new FileStream(
                    safeTarget,
                    FileMode.Create,
                    FileAccess.Write,
                    FileShare.None,
                    1024 * 1024,
                    FileOptions.SequentialScan | FileOptions.WriteThrough);

                byte[] buffer = new byte[1024 * 1024];
                int read;
                while ((read = source.Read(buffer, 0, buffer.Length)) > 0)
                {
                    memberBytes += read;
                    extractedBytes += read;
                    if (memberBytes > maxMemberUncompressedBytes || extractedBytes > maxTotalUncompressedBytes)
                    {
                        throw new SafeArchiveException("壓縮檔實際解壓大小超過安全上限");
                    }

                    output.Write(buffer, 0, read);
                    progress?.Invoke(extractedBytes, totalBytes);
                }

                output.Flush(true);
            }
            catch (IOException exception) when (exception is not SafeArchiveException)
            {
                throw new SafeArchiveException($"無法解壓縮檔案： {member.Entry.FullName}", exception);
            }
        }

        progress?.Invoke(totalBytes > 0 ? totalBytes : extractedBytes, totalBytes);
    }

    public static byte[]? ReadMetadataBytes(ZipArchive archive, string memberName, long maxBytes = 2L * 1024 * 1024)
    {
        ArgumentNullException.ThrowIfNull(archive);
        ArgumentException.ThrowIfNullOrWhiteSpace(memberName);
        ArgumentOutOfRangeException.ThrowIfNegative(maxBytes);

        var entry = archive.GetEntry(memberName);
        if (entry is null || entry.FullName.EndsWith('/') || entry.Length > maxBytes)
        {
            return null;
        }

        using var source = entry.Open();
        using var buffer = new MemoryStream();
        source.CopyTo(buffer, 1024 * 1024);
        return buffer.Length <= maxBytes ? buffer.ToArray() : null;
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
                throw new SafeArchiveException("壓縮檔解壓後大小超過安全上限");
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
        string key = string.Join(Path.DirectorySeparatorChar, parts);
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

        public void WriteBytes(string memberName, ReadOnlySpan<byte> content)
        {
            ThrowIfDisposed();
            string normalized = PrepareMember(memberName, content.Length);
            var entry = _archive.CreateEntry(normalized, CompressionLevel.Optimal);
            using var target = entry.Open();
            target.Write(content);
        }

        public long WriteFile(string memberName, string sourcePath)
        {
            ThrowIfDisposed();
            string source = SafeFileSystem.ResolveStablePath(sourcePath);
            var info = new FileInfo(source);
            if (!info.Exists)
            {
                throw new FileNotFoundException("找不到要壓縮的檔案", source);
            }

            string normalized = PrepareMember(memberName, info.Length);
            var entry = _archive.CreateEntry(normalized, CompressionLevel.Optimal);
            using var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024, FileOptions.SequentialScan);
            using var output = entry.Open();
            byte[] buffer = new byte[1024 * 1024];
            long copied = 0L;
            while (copied < info.Length)
            {
                long remaining = info.Length - copied;
                int requested = (int)Math.Min(buffer.Length, remaining + 1);
                int read = input.Read(buffer, 0, requested);
                if (read == 0)
                {
                    break;
                }

                copied += read;
                if (copied > info.Length)
                {
                    throw new SafeArchiveException($"壓縮來源檔案在讀取期間成長： {source}");
                }

                output.Write(buffer, 0, read);
            }

            if (copied != info.Length)
            {
                throw new SafeArchiveException($"壓縮來源檔案在讀取期間縮短： {source}");
            }

            return copied;
        }

        public void Complete()
        {
            ThrowIfDisposed();
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
            string key = string.Join(Path.DirectorySeparatorChar, parts);
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

        private void ThrowIfDisposed() => ObjectDisposedException.ThrowIf(_disposed, this);

        private void TryDeleteTemporaryFile()
        {
            try
            {
                if (File.Exists(_temporaryPath))
                {
                    File.Delete(_temporaryPath);
                }
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }

    private sealed record PreparedMember(ZipArchiveEntry Entry, string RelativePath);
}
