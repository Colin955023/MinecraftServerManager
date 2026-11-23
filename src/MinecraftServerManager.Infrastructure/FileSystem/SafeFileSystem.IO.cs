using System.Text;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static partial class SafeFileSystem
{
    /// <summary>取得經過路徑穩定性檢查之目錄的最後修改時間；目錄不存在或無法存取時回傳 null</summary>
    public static DateTimeOffset? TryGetDirectoryLastWriteTime(string path)
    {
        try
        {
            // 單一 DirectoryInfo 取得存在狀態與時間，避免檢查後目錄被刪除而取得 1601 年預設值
            var info = new DirectoryInfo(ResolveStableDirectory(path));
            return info.Exists ? new DateTimeOffset(info.LastWriteTime) : null;
        }
        catch (DirectoryNotFoundException)
        {
            return null;
        }
        catch (Exception ex) when (ex is SafeFileSystemException or IOException or UnauthorizedAccessException or ArgumentException)
        {
            Logger.Warning(ex, "讀取目錄最後修改時間失敗: {Path}", path);
            return null;
        }
    }

    /// <summary>路徑所在磁碟的可用空間；無法取得回傳 null</summary>
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

    public static FileStream OpenRead(
        string filePath,
        FileShare share = FileShare.Read,
        FileOptions options = FileOptions.SequentialScan) =>
        OpenResolvedRead(ResolveStablePath(filePath), share, options);

    private static FileStream OpenResolvedRead(string stablePath, FileShare share, FileOptions options)
    {
        if (!File.Exists(stablePath))
        {
            throw new FileNotFoundException("找不到檔案", stablePath);
        }

        return new FileStream(stablePath, FileMode.Open, FileAccess.Read, share, 4096, options);
    }

    /// <summary>UTF-8 解碼並去除開頭 BOM</summary>
    public static string DecodeUtf8WithoutBom(ReadOnlySpan<byte> bytes)
    {
        if (bytes.StartsWith(Utf8Preamble))
        {
            bytes = bytes[Utf8Preamble.Length..];
        }

        return Encoding.UTF8.GetString(bytes);
    }

    public static string ReadAllText(string filePath, Encoding? encoding = null, long maxBytes = 16L * 1024 * 1024)
    {
        byte[] bytes = ReadRegularFile(filePath, maxBytes)
            ?? throw new FileNotFoundException("找不到或無法安全讀取檔案", filePath);
        return DecodeWithoutPreamble(bytes, encoding);
    }

    /// <summary>依編碼解碼並去除相符的開頭 BOM；UTF-8 一律去除 EF BB BF</summary>
    private static string DecodeWithoutPreamble(ReadOnlySpan<byte> bytes, Encoding? encoding)
    {
        if (encoding is null or UTF8Encoding)
        {
            return DecodeUtf8WithoutBom(bytes);
        }

        ReadOnlySpan<byte> preamble = encoding.Preamble;
        if (!preamble.IsEmpty && bytes.StartsWith(preamble))
        {
            bytes = bytes[preamble.Length..];
        }

        return encoding.GetString(bytes);
    }

    public static string[] ReadAllLines(string filePath, Encoding? encoding = null, long maxBytes = 16L * 1024 * 1024)
    {
        byte[] bytes = ReadRegularFile(filePath, maxBytes)
            ?? throw new FileNotFoundException("找不到或無法安全讀取檔案", filePath);
        string text = DecodeWithoutPreamble(bytes, encoding);
        var lines = new List<string>();
        foreach (ReadOnlySpan<char> line in text.AsSpan().EnumerateLines())
        {
            lines.Add(line.ToString());
        }

        return [.. lines];
    }

    public static async Task<string> ReadAllTextAsync(
        string filePath,
        Encoding? encoding = null,
        long maxBytes = 16L * 1024 * 1024,
        CancellationToken cancellationToken = default)
    {
        ValidateMaxBytes(maxBytes);
        cancellationToken.ThrowIfCancellationRequested();
        var stream = OpenRead(filePath, options: FileOptions.Asynchronous | FileOptions.SequentialScan);
        byte[] buffer;
        await using (stream.ConfigureAwait(false))
        {
            buffer = await ReadStreamBoundedAsync(stream, maxBytes, filePath, cancellationToken).ConfigureAwait(false);
        }

        return DecodeWithoutPreamble(buffer, encoding);
    }

    private static byte[] ReadStreamBounded(Stream stream, long maxBytes, string filePath)
    {
        long length = stream.Length;
        if (length > maxBytes)
        {
            throw new IOException($"檔案大小超過安全上限 ({length} > {maxBytes})：{filePath}");
        }

        byte[] buffer = GC.AllocateUninitializedArray<byte>((int)length);
        stream.ReadExactly(buffer);
        if (stream.ReadByte() != -1)
        {
            throw new IOException($"檔案於讀取期間變更：{filePath}");
        }

        return buffer;
    }

    private static async Task<byte[]> ReadStreamBoundedAsync(Stream stream, long maxBytes, string filePath, CancellationToken cancellationToken)
    {
        long length = stream.Length;
        if (length > maxBytes)
        {
            throw new IOException($"檔案大小超過安全上限 ({length} > {maxBytes})：{filePath}");
        }

        byte[] buffer = GC.AllocateUninitializedArray<byte>((int)length);
        await stream.ReadExactlyAsync(buffer, cancellationToken).ConfigureAwait(false);
        byte[] probe = System.Buffers.ArrayPool<byte>.Shared.Rent(1);
        try
        {
            int extra = await stream.ReadAsync(probe.AsMemory(0, 1), cancellationToken).ConfigureAwait(false);
            if (extra != 0)
            {
                throw new IOException($"檔案於讀取期間變更：{filePath}");
            }
        }
        finally
        {
            System.Buffers.ArrayPool<byte>.Shared.Return(probe);
        }

        return buffer;
    }

    private static void ValidateMaxBytes(long maxBytes)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(maxBytes);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(maxBytes, Array.MaxLength);
    }

    /// <summary>讀取檔案尾端最多 <paramref name="maxBytes"/> 位元組；<paramref name="truncated"/> 表示只讀了尾端</summary>
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
        stream.Seek(Math.Max(0, length - bytesToRead), SeekOrigin.Begin);
        byte[] buffer = System.Buffers.ArrayPool<byte>.Shared.Rent(bytesToRead);
        try
        {
            int bytesRead = stream.ReadAtLeast(buffer.AsSpan(0, bytesToRead), bytesToRead, throwOnEndOfStream: false);
            ReadOnlySpan<byte> content = buffer.AsSpan(0, bytesRead);
            if (!truncated)
            {
                return DecodeUtf8WithoutBom(content);
            }

            // 從字元中間截斷：略過開頭的 UTF-8 延續位元組（10xxxxxx）
            int start = 0;
            while (start < content.Length && (content[start] & 0xC0) == 0x80)
            {
                start++;
            }

            return Encoding.UTF8.GetString(content[start..]);
        }
        finally
        {
            System.Buffers.ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    /// <summary>於背景執行緒原子寫入；失敗時擲出 <see cref="IOException"/></summary>
    public static async Task WriteAllBytesAsync(
        string filePath,
        ReadOnlyMemory<byte> content,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!await Task.Run(() => AtomicFileWriter.WriteBytes(filePath, content.Span), cancellationToken).ConfigureAwait(false))
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
        ReadOnlySpan<byte> preamble = textEncoding.Preamble;
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

    public static byte[]? ReadRegularFile(string filePath, long maxBytes = 16 * 1024 * 1024)
    {
        ValidateMaxBytes(maxBytes);
        if (string.IsNullOrWhiteSpace(filePath))
        {
            return null;
        }

        string stablePath;
        try
        {
            stablePath = ResolveStablePath(filePath);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
            // reparse point 或路徑無效時視為無法安全讀取
            return null;
        }

        if (!File.Exists(stablePath))
        {
            return null;
        }

        // 以單一串流檢查長度並讀取，避免檢查後檔案變大的競態
        using var stream = OpenResolvedRead(stablePath, FileShare.Read, FileOptions.SequentialScan);
        return ReadStreamBounded(stream, maxBytes, filePath);
    }
}
