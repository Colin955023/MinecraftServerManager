using System.Diagnostics;
using System.Buffers;
using System.IO.Compression;
using System.Text;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static class SafeZipArchive
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(SafeZipArchive));
    private const int DefaultMaxMembers = 100_000;
    private const long DefaultMaxMemberBytes = 2L * 1024 * 1024 * 1024; // 2 GB
    private const long DefaultMaxTotalBytes = 32L * 1024 * 1024 * 1024; // 32 GB
    private const long DefaultMaxArchiveBytes = DefaultMaxTotalBytes + (64L * 1024 * 1024);
    private const int DefaultMaxCompressionRatio = 200;

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
            return ValidateOrDispose(ZipFile.OpenRead(path), maxMembers);
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

        try
        {
            return ValidateOrDispose(new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen), maxMembers);
        }
        catch (InvalidDataException exception)
        {
            throw new SafeArchiveException("ZIP 檔案格式無效", exception);
        }
    }

    /// <summary>
    /// 驗證已開啟之壓縮檔；驗證失敗時先釋放再重新擲出，避免洩漏檔案控制代碼
    /// </summary>
    private static ZipArchive ValidateOrDispose(ZipArchive archive, int maxMembers)
    {
        try
        {
            ValidateArchive(archive, maxMembers, DefaultMaxTotalBytes);
            return archive;
        }
        catch (Exception)
        {
            archive.Dispose();
            throw;
        }
    }

    /// <summary>
    /// 受限讀取單一壓縮檔成員之位元組陣列（若超過 <paramref name="maxBytes"/> 則回傳 <see langword="null"/>，防止記憶體解壓縮炸彈）。
    /// </summary>
    public static byte[]? ReadEntryBytesBounded(ZipArchiveEntry entry, int maxBytes)
    {
        ArgumentNullException.ThrowIfNull(entry);
        ArgumentOutOfRangeException.ThrowIfNegative(maxBytes);

        long declaredLength = entry.Length;
        if (declaredLength < 0 || declaredLength > maxBytes)
        {
            return null;
        }

        // 依中央目錄宣告長度精確讀取；實際解壓量與宣告不符（含宣告 0 卻有資料）一律拒絕，防止長度造假之解壓縮炸彈
        int targetLength = (int)declaredLength;
        byte[] buffer = targetLength == 0 ? [] : new byte[targetLength];
        using var stream = entry.Open();
        int read = stream.ReadAtLeast(buffer, targetLength, throwOnEndOfStream: false);
        return read == targetLength && stream.ReadByte() == -1 ? buffer : null;
    }

    /// <summary>
    /// 受限讀取單一壓縮檔成員之 UTF-8 文字（自動剝除 UTF-8 BOM；若超過 <paramref name="maxBytes"/> 則回傳 <see langword="null"/>）。
    /// </summary>
    public static string? ReadEntryTextBounded(ZipArchiveEntry entry, int maxBytes) =>
        ReadEntryBytesBounded(entry, maxBytes) is { } bytes ? DecodeUtf8WithoutBom(bytes) : null;

    private static string DecodeUtf8WithoutBom(ReadOnlySpan<byte> span)
    {
        if (span.StartsWith(Encoding.UTF8.Preamble))
        {
            span = span[Encoding.UTF8.Preamble.Length..];
        }

        return Encoding.UTF8.GetString(span);
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
            ValidateEntry(entry);
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
        Action<long, long>? progress = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(destinationDirectory);

        string destination = SafeFileSystem.ResolveStableDirectory(destinationDirectory, create: true);

        // OpenRead 已完成成員數、總量、單檔大小、壓縮比、符號連結與路徑衝突驗證，這裡只需正規化成員相對路徑
        using var archive = OpenRead(archivePath);
        var members = new List<PreparedMember>(archive.Entries.Count);
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            members.Add(new PreparedMember(entry, SanitizeMemberName(entry.FullName)));
        }

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
                        0,
                        FileOptions.SequentialScan);

                    int read;
                    while ((read = source.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        memberBytes += read;
                        extractedBytes += read;
                        if (memberBytes > DefaultMaxMemberBytes || extractedBytes > DefaultMaxTotalBytes)
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
            Logger.Warning(exception, "預估解壓縮磁碟剩餘空間失敗，降級由寫入階段處理");
        }
    }

    private static void ValidateEntry(ZipArchiveEntry entry)
    {
        if (IsSymlink(entry))
        {
            throw new SafeArchiveException($"壓縮檔包含不支援的符號連結： {entry.FullName}");
        }

        if (entry.Length > DefaultMaxMemberBytes)
        {
            throw new SafeArchiveException($"壓縮檔成員過大： {entry.FullName}");
        }

        if (entry.Length > 0)
        {
            if (entry.CompressedLength <= 0 || entry.Length / (double)entry.CompressedLength > DefaultMaxCompressionRatio)
            {
                throw new SafeArchiveException($"壓縮檔成員壓縮比例過高： {entry.FullName}");
            }
        }
    }

    private static string SanitizeMemberName(string memberName)
    {
        if (string.IsNullOrEmpty(memberName))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        ReadOnlySpan<char> span = memberName.AsSpan();
        if (span[0] is '/' or '\\' || span.Contains(':'))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        ReadOnlySpan<char> trimmed = span.TrimEnd("/\\");
        if (trimmed.IsEmpty || Path.IsPathRooted(trimmed))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        foreach (Range range in trimmed.SplitAny("/\\"))
        {
            ReadOnlySpan<char> part = trimmed[range];
            if (part.IsEmpty || part is "." or ".." || ServerName.IsWindowsDeviceName(part))
            {
                throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
            }
        }

        return string.Create(trimmed.Length, trimmed, static (dst, src) =>
        {
            src.CopyTo(dst);
            dst.Replace('/', Path.DirectorySeparatorChar);
            dst.Replace('\\', Path.DirectorySeparatorChar);
        });
    }

    private static void ValidatePathCollision(
        ZipArchiveEntry entry,
        string relativePath,
        Dictionary<string, bool> paths,
        HashSet<string> parentPaths)
    {
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

        for (int separatorIndex = relativePath.IndexOf(Path.DirectorySeparatorChar); separatorIndex >= 0; separatorIndex = relativePath.IndexOf(Path.DirectorySeparatorChar, separatorIndex + 1))
        {
            string parentKey = relativePath[..separatorIndex];
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
            _temporaryPath = AtomicFileWriter.CreateTempSiblingPath(_targetPath);
            _maxMembers = maxMembers;
            _maxTotalBytes = maxTotalBytes;
            _maxMemberBytes = maxMemberBytes;
            _stream = new FileStream(
                _temporaryPath,
                FileMode.CreateNew,
                FileAccess.ReadWrite,
                FileShare.None,
                1024 * 1024,
                FileOptions.None);
            _archive = new ZipArchive(_stream, ZipArchiveMode.Create, leaveOpen: true);
        }

        public void SetComment(string comment)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            _archive.Comment = comment;
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
                SafeFileSystem.TryDeleteFile(_temporaryPath);
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
            string key = normalized;
            if (_paths.Contains(key) || _parentPaths.Contains(key))
            {
                throw new SafeArchiveException($"壓縮檔包含重複或路徑衝突： {memberName}");
            }

            for (int separatorIndex = normalized.IndexOf(Path.DirectorySeparatorChar); separatorIndex >= 0; separatorIndex = normalized.IndexOf(Path.DirectorySeparatorChar, separatorIndex + 1))
            {
                string parentKey = normalized[..separatorIndex];
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
    }

    private sealed record PreparedMember(ZipArchiveEntry Entry, string RelativePath);
}
