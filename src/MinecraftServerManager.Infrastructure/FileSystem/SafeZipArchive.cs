using System.Buffers;
using System.IO.Compression;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static partial class SafeZipArchive
{
    private const int DefaultMaxMembers = 100_000;
    private const long DefaultMaxMemberBytes = 2L * 1024 * 1024 * 1024; // 2 GB
    private const long DefaultMaxTotalBytes = 32L * 1024 * 1024 * 1024; // 32 GB
    private const long DefaultMaxArchiveBytes = DefaultMaxTotalBytes + (64L * 1024 * 1024);
    private const int DefaultMaxCompressionRatio = 200;
    private const long RatioCheckMinMemberBytes = 64L * 1024 * 1024;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(SafeZipArchive));

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

        var stream = SafeFileSystem.OpenRead(archivePath);
        try
        {
            if (stream.Length > maxArchiveBytes)
            {
                throw new SafeArchiveException("壓縮檔大小超過安全上限");
            }

            return ValidateOrDispose(new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen: false), maxMembers);
        }
        catch (InvalidDataException exception)
        {
            stream.Dispose();
            throw new SafeArchiveException("ZIP 檔案格式無效", exception);
        }
        catch (Exception)
        {
            stream.Dispose();
            throw;
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

    /// <summary>驗證已開啟之壓縮檔；驗證失敗時先釋放再重新擲出，避免洩漏檔案控制代碼</summary>
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

    /// <summary>讀取壓縮檔成員；超過 <paramref name="maxBytes"/> 回傳 null</summary>
    public static byte[]? ReadEntryBytesBounded(ZipArchiveEntry entry, int maxBytes)
    {
        ArgumentNullException.ThrowIfNull(entry);
        ArgumentOutOfRangeException.ThrowIfNegative(maxBytes);

        long declaredLength = entry.Length;
        if (declaredLength < 0 || declaredLength > maxBytes)
        {
            return null;
        }

        // 依宣告長度精確讀取；實際解壓量不符一律拒絕
        int targetLength = (int)declaredLength;
        byte[] buffer = targetLength == 0 ? [] : new byte[targetLength];
        using var stream = entry.Open();
        int read = stream.ReadAtLeast(buffer, targetLength, throwOnEndOfStream: false);
        return read == targetLength && stream.ReadByte() == -1 ? buffer : null;
    }

    /// <summary>讀取壓縮檔成員為 UTF-8 文字；超過 <paramref name="maxBytes"/> 回傳 null</summary>
    public static string? ReadEntryTextBounded(ZipArchiveEntry entry, int maxBytes) =>
        ReadEntryBytesBounded(entry, maxBytes) is { } bytes ? SafeFileSystem.DecodeUtf8WithoutBom(bytes) : null;

    private static void ValidateArchive(ZipArchive archive, int maxMembers, long maxTotalBytes)
    {
        if (archive.Entries.Count > maxMembers)
        {
            throw new SafeArchiveException("壓縮檔成員數量超過安全上限");
        }

        long totalBytes = 0;
        long totalCompressedBytes = 0;
        var collisions = new PathCollisionTracker();
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            ValidateEntry(entry);
            string relativePath = SanitizeMemberName(entry.FullName);
            collisions.Add(relativePath, IsDirectoryEntry(entry), entry.FullName);
            totalBytes = AddChecked(totalBytes, entry.Length);
            totalCompressedBytes = AddChecked(totalCompressedBytes, entry.CompressedLength);
            if (totalBytes > maxTotalBytes)
            {
                throw new SafeArchiveException("壓縮檔解壓縮後大小超過安全上限");
            }
        }

        // 全檔總壓縮比：防止大量成員各自低於門檻、合計卻極度膨脹
        if (totalBytes > RatioCheckMinMemberBytes &&
            (totalCompressedBytes <= 0 || totalBytes / (double)totalCompressedBytes > DefaultMaxCompressionRatio))
        {
            throw new SafeArchiveException("壓縮檔整體壓縮比例過高");
        }
    }

    private static long AddChecked(long total, long value)
    {
        try
        {
            return checked(total + value);
        }
        catch (OverflowException exception)
        {
            throw new SafeArchiveException("壓縮檔大小資訊溢位", exception);
        }
    }

    /// <summary>名稱以分隔字元結尾且長度為 0 的成員才是目錄</summary>
    private static bool IsDirectoryEntry(ZipArchiveEntry entry) =>
        entry.Length == 0 && (entry.FullName.EndsWith('/') || entry.FullName.EndsWith('\\'));

    public static void Extract(
        string archivePath,
        string destinationDirectory,
        Action<long, long>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(destinationDirectory);
        cancellationToken.ThrowIfCancellationRequested();

        string destination = SafeFileSystem.ResolveStableDirectory(destinationDirectory, create: true);

        // OpenRead 已完成驗證，這裡只正規化成員路徑
        using var archive = OpenRead(archivePath);
        var members = new List<PreparedMember>(archive.Entries.Count);
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            members.Add(new PreparedMember(entry, SanitizeMemberName(entry.FullName)));
        }

        long totalBytes = members.Aggregate(0L, static (sum, member) => AddChecked(sum, member.Entry.Length));
        EnsureSufficientDiskSpace(destination, totalBytes);
        progress?.Invoke(0, totalBytes);
        long extractedBytes = 0;
        var progressThrottle = new ProgressThrottle(TimeSpan.FromMilliseconds(100), TimeProvider.System);
        byte[] buffer = ArrayPool<byte>.Shared.Rent(81920);

        string destinationRoot = Path.GetFullPath(destination + Path.DirectorySeparatorChar);
        var validatedDirectories = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { destination };
        try
        {
            foreach (var member in members)
            {
                cancellationToken.ThrowIfCancellationRequested();
                string target = Path.Combine(destination, member.RelativePath);
                string resolvedTarget = Path.GetFullPath(target);
                if (!resolvedTarget.StartsWith(destinationRoot, StringComparison.OrdinalIgnoreCase))
                {
                    throw new SafeArchiveException($"壓縮檔嘗試路徑穿越： {member.Entry.FullName}");
                }

                if (IsDirectoryEntry(member.Entry))
                {
                    if (validatedDirectories.Add(resolvedTarget))
                    {
                        SafeFileSystem.ResolveStableDirectory(resolvedTarget, create: true);
                    }

                    continue;
                }

                string parentDir = Path.GetDirectoryName(resolvedTarget)!;
                if (validatedDirectories.Add(parentDir))
                {
                    SafeFileSystem.ResolveStableDirectory(parentDir, create: true);
                }

                SafeFileSystem.EnsureNotReparsePoint(resolvedTarget);
                string safeTarget = resolvedTarget;
                long declaredBytes = member.Entry.Length;
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
                        cancellationToken.ThrowIfCancellationRequested();
                        memberBytes += read;
                        extractedBytes += read;
                        if (memberBytes > declaredBytes || memberBytes > DefaultMaxMemberBytes || extractedBytes > DefaultMaxTotalBytes)
                        {
                            throw new SafeArchiveException($"壓縮檔實際解壓縮大小超過宣告值或安全上限： {member.Entry.FullName}");
                        }

                        output.Write(buffer, 0, read);

                        if (progress is not null && ShouldReportExtractProgress(progressThrottle, extractedBytes, totalBytes))
                        {
                            progress.Invoke(extractedBytes, totalBytes);
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

    private static bool ShouldReportExtractProgress(ProgressThrottle progressThrottle, long extractedBytes, long totalBytes)
    {
        if (totalBytes <= 0)
        {
            return progressThrottle.ShouldReport();
        }

        int percent = ProgressMapping.Map(extractedBytes, totalBytes, 0, 100);
        return progressThrottle.ShouldReport(percent);
    }

    /// <summary>檢查剩餘空間（保留 5% 或 512 MB）</summary>
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
        catch (Exception exception) when (exception is (ArgumentException or IOException or UnauthorizedAccessException) and not SafeArchiveException)
        {
            Logger.Warning(exception, "預估解壓縮磁碟剩餘空間失敗，降級由寫入階段處理: {Path}", destination);
        }
    }
}
