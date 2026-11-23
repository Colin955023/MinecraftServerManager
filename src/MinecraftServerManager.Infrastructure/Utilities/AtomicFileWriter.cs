using Microsoft.Win32.SafeHandles;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>原子寫入：先寫同目錄暫存檔，再一次替換目標</summary>
public static class AtomicFileWriter
{
    public const string TempFileExtension = ".tmp";

    /// <summary>產生同目錄的暫存檔路徑</summary>
    public static string CreateTempSiblingPath(string targetPath) =>
        $"{targetPath}.{Guid.NewGuid():N}{TempFileExtension}";

    private const int StripeCount = 128;
    private const int CommitMaxAttempts = 3;
    private static readonly TimeSpan CommitRetryDelay = TimeSpan.FromMilliseconds(50);
    private static readonly SemaphoreSlim[] StripeGates = [.. Enumerable.Range(0, StripeCount).Select(static _ => new SemaphoreSlim(1, 1))];

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AtomicFileWriter));

    private static SemaphoreSlim GetGateForPath(string path)
    {
        uint hash = (uint)StringComparer.OrdinalIgnoreCase.GetHashCode(path);
        return StripeGates[hash % StripeCount];
    }

    public static bool WriteBytes(string filePath, ReadOnlySpan<byte> content, bool skipIfUnchanged = false)
    {
        if (TryResolveTarget(filePath) is not { } target)
        {
            return false;
        }

        var gate = GetGateForPath(target);
        gate.Wait();
        string? temporary = null;
        bool committed = false;
        try
        {
            if (skipIfUnchanged && IsUnchanged(target, content))
            {
                return true;
            }

            temporary = CreateTempSiblingPath(target);
            using (SafeFileHandle handle = File.OpenHandle(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, FileOptions.None, content.Length))
            {
                RandomAccess.Write(handle, content, fileOffset: 0);
                RandomAccess.FlushToDisk(handle);
            }

            CommitReplace(temporary, target);
            committed = true;
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "原子寫入失敗: {Path}", target);
            return false;
        }
        finally
        {
            if (!committed)
            {
                SafeFileSystem.TryDeleteFile(temporary);
            }

            gate.Release();
        }
    }

    public static async Task<bool> WriteBytesAsync(
        string filePath,
        ReadOnlyMemory<byte> content,
        bool skipIfUnchanged = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (TryResolveTarget(filePath) is not { } target)
        {
            return false;
        }

        var gate = GetGateForPath(target);
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        string? temporary = null;
        bool committed = false;
        try
        {
            if (skipIfUnchanged && IsUnchanged(target, content.Span))
            {
                return true;
            }

            temporary = CreateTempSiblingPath(target);
            using (SafeFileHandle handle = File.OpenHandle(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, FileOptions.Asynchronous, content.Length))
            {
                await RandomAccess.WriteAsync(handle, content, fileOffset: 0, cancellationToken).ConfigureAwait(false);
                RandomAccess.FlushToDisk(handle);
            }

            CommitReplace(temporary, target);
            committed = true;
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "原子寫入失敗: {Path}", target);
            return false;
        }
        finally
        {
            if (!committed)
            {
                SafeFileSystem.TryDeleteFile(temporary);
            }

            gate.Release();
        }
    }

    public static bool WriteText(string filePath, string content, bool skipIfUnchanged = false) => WriteBytes(filePath, System.Text.Encoding.UTF8.GetBytes(content), skipIfUnchanged);

    public static bool WriteJson<T>(string filePath, T? value, bool indented = true, bool skipIfUnchanged = false)
    {
        byte[]? payload = JsonCodec.SerializeToUtf8Bytes(value, indented);
        return payload is not null && WriteBytes(filePath, payload, skipIfUnchanged);
    }

    /// <summary>寫入失敗時擲出 <see cref="IOException"/></summary>
    public static void WriteTextOrThrow(string filePath, string content)
    {
        if (!WriteText(filePath, content))
        {
            throw new IOException($"無法寫入檔案：{filePath}");
        }
    }

    /// <summary>寫入失敗時擲出 <see cref="IOException"/></summary>
    public static void WriteJsonOrThrow<T>(string filePath, T? value, bool indented = true)
    {
        if (!WriteJson(filePath, value, indented))
        {
            throw new IOException($"無法寫入檔案：{filePath}");
        }
    }

    public static bool ReplaceFile(string sourcePath, string targetPath)
    {
        try
        {
            string source = SafeFileSystem.ResolveStablePath(sourcePath);
            string target = SafeFileSystem.ResolveStablePath(targetPath, createParent: true);
            if (!File.Exists(source))
            {
                return false;
            }

            var gate = GetGateForPath(target);
            gate.Wait();
            try
            {
                CommitReplace(source, target);
            }
            finally
            {
                gate.Release();
            }

            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "原子替換失敗: {SourcePath} -> {TargetPath}", sourcePath, targetPath);
            return false;
        }
    }

    private static string? TryResolveTarget(string filePath)
    {
        try
        {
            return SafeFileSystem.ResolveStablePath(filePath, createParent: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "原子寫入目標路徑無效或不安全: {Path}", filePath);
            return null;
        }
    }

    /// <summary>先比長度再比內容；長度不同即免讀取整份檔案</summary>
    private static bool IsUnchanged(string target, ReadOnlySpan<byte> content)
    {
        var info = new FileInfo(target);
        return info.Exists &&
            info.Length == content.Length &&
            SafeFileSystem.ReadRegularFile(target) is { } existing &&
            existing.AsSpan().SequenceEqual(content);
    }

    /// <summary>以單一覆寫搬移提交；目標唯讀時先清除，短暫鎖檔時輕量重試</summary>
    private static void CommitReplace(string source, string target)
    {
        SafeFileSystem.ClearReadOnlyAttribute(target);

        // ERROR_SHARING_VIOLATION (32)、ERROR_LOCK_VIOLATION (33)：防毒或索引短暫開啟目標
        SafeFileSystem.RetryOnTransientIo(
            () => File.Move(source, target, overwrite: true),
            target,
            CommitMaxAttempts,
            CommitRetryDelay,
            static (ex, _) => ex is IOException io && SafeFileSystem.IsTransientFileLock(io));
    }
}
